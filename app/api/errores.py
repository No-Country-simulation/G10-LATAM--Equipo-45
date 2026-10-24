"""
NM-19 — Manejo de errores del API.

Regla de oro: el usuario ve un mensaje en español, amigable y accionable; el detalle técnico (tipo de
excepción, mensaje original, stack trace, rutas) va SOLO al log. Los mensajes de las excepciones del
pipeline pueden contener rutas, nombres internos o fragmentos de la respuesta del proveedor, así que
ninguno se copia a la respuesta.

Mapeo:
    entrada inválida / archivo ilegible / documento sin texto ..... 422
    archivo o texto por encima del límite ......................... 413
    ErrorDeLLM, ErrorDeEmbeddings (proveedor caído, rate limit) ... 503
    ErrorDeOrquestacion (JSON inválido tras el reintento) ......... 502
    ErrorDeAlmacenamiento y cualquier otra excepción .............. 500
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import DetalleError, ErrorRespuesta
from app.ingesta.models import ErrorDeIngesta
from app.llm.gemini_client import ErrorDeLLM
from app.llm.orquestador import ErrorDeOrquestacion
from app.oci.almacenamiento import ErrorDeAlmacenamiento
from app.rag.embeddings import ErrorDeEmbeddings

logger = logging.getLogger(__name__)

# Los campos internos del modelo de entrada se muestran con el nombre que ve el usuario en el formulario.
_CAMPO_VISIBLE = {"contenido_archivo": "archivo", "nombre_archivo": "archivo"}
_CAMPO_DOCUMENTO = "archivo / documento_contenido"


class ErrorDeEntrada(Exception):
    """El pedido no se puede procesar por culpa de la entrada (422). El mensaje es apto para el usuario."""

    def __init__(self, mensaje: str, campo: str | None = None, codigo: str = "entrada_invalida"):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.campo = campo
        self.codigo = codigo


class ErrorDeTamano(ErrorDeEntrada):
    """El archivo o el texto supera `max_upload_mb` (413)."""

    def __init__(self, limite_mb: int, campo: str):
        super().__init__(
            f"El documento supera el tamaño máximo permitido ({limite_mb} MB).",
            campo=campo,
            codigo="documento_demasiado_grande",
        )


def _respuesta(status: int, codigo: str, mensaje: str, detalles: list[DetalleError] | None = None) -> JSONResponse:
    cuerpo = ErrorRespuesta(codigo=codigo, mensaje=mensaje, detalles=detalles)
    return JSONResponse(status_code=status, content=cuerpo.model_dump(mode="json", exclude_none=True))


def _traducir_problema(error: dict) -> str:
    """Pasa un error de Pydantic/FastAPI (en inglés) a un mensaje en español, sin eco del valor enviado."""
    tipo = error.get("type", "")
    ctx = error.get("ctx") or {}
    if tipo == "entrada_invalida":
        return ctx.get("mensaje", "Valor inválido.")
    if tipo == "missing":
        return "Este campo es obligatorio."
    if tipo == "enum":
        permitidos = str(ctx.get("expected", "")).replace(" or ", ", ")
        return f"Valor no permitido. Valores válidos: {permitidos}."
    if tipo == "string_too_long":
        return f"Supera el máximo de {ctx.get('max_length')} caracteres."
    return "Valor inválido."


def _campo_de(error: dict) -> str:
    loc = [str(parte) for parte in error.get("loc", ()) if parte not in ("body", "form")]
    if not loc:
        return _CAMPO_DOCUMENTO
    return _CAMPO_VISIBLE.get(loc[-1], loc[-1])


async def _validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
    detalles = [DetalleError(campo=_campo_de(e), problema=_traducir_problema(e)) for e in exc.errors()]
    logger.info("Entrada inválida en %s: %s", request.url.path, [(d.campo, d.problema) for d in detalles])
    return _respuesta(422, "entrada_invalida", "Revisá los datos enviados: hay campos con problemas.", detalles)


async def _entrada(request: Request, exc: ErrorDeEntrada) -> JSONResponse:
    logger.info("Entrada rechazada en %s: %s", request.url.path, exc.mensaje)
    detalles = [DetalleError(campo=exc.campo, problema=exc.mensaje)] if exc.campo else None
    estado = 413 if isinstance(exc, ErrorDeTamano) else 422
    return _respuesta(estado, exc.codigo, exc.mensaje, detalles)


async def _ingesta(request: Request, exc: ErrorDeIngesta) -> JSONResponse:
    logger.warning("Fallo de ingesta: %s", exc)  # el mensaje original puede traer rutas: solo al log
    return _respuesta(
        422,
        "documento_ilegible",
        "No pudimos leer el documento. Verificá que no esté corrupto y que sea un .pdf, .md o .txt (UTF-8).",
        [DetalleError(campo="archivo", problema="Archivo ilegible o con formato inválido.")],
    )


async def _llm(request: Request, exc: ErrorDeLLM) -> JSONResponse:
    logger.error("Fallo del LLM: %s", exc)
    return _respuesta(
        503, "servicio_no_disponible", "El servicio de generación no está disponible en este momento. Probá de nuevo en unos minutos."
    )


async def _embeddings(request: Request, exc: ErrorDeEmbeddings) -> JSONResponse:
    logger.error("Fallo de embeddings: %s", exc)
    return _respuesta(
        503, "servicio_no_disponible", "El servicio de análisis de documentos no está disponible en este momento. Probá de nuevo en unos minutos."
    )


async def _orquestacion(request: Request, exc: ErrorDeOrquestacion) -> JSONResponse:
    logger.error("Salida inválida del modelo: %s", exc)
    return _respuesta(
        502, "respuesta_invalida_del_modelo", "No pudimos generar un resultado válido a partir del documento. Probá de nuevo."
    )


async def _almacenamiento(request: Request, exc: ErrorDeAlmacenamiento) -> JSONResponse:
    logger.error("Fallo de almacenamiento: %s", exc)
    return _respuesta(500, "error_interno", "Ocurrió un problema al guardar los archivos. Probá de nuevo más tarde.")


async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """404, 405, etc. de Starlette: mismo formato de error, sin el {"detail": ...} por defecto."""
    if exc.status_code == 404:
        return _respuesta(404, "no_encontrado", "La ruta solicitada no existe.")
    if exc.status_code == 405:
        return _respuesta(405, "metodo_no_permitido", "Ese método no está permitido en esta ruta.")
    return _respuesta(exc.status_code, "error_http", "No se pudo procesar la solicitud.")


async def _inesperado(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Error inesperado en %s %s", request.method, request.url.path, exc_info=exc)
    return _respuesta(500, "error_interno", "Ocurrió un error inesperado. Probá de nuevo más tarde.")


def registrar_manejadores(app: FastAPI) -> None:
    """Instala todos los manejadores en la app."""
    app.add_exception_handler(RequestValidationError, _validacion)
    app.add_exception_handler(ErrorDeEntrada, _entrada)
    app.add_exception_handler(ErrorDeIngesta, _ingesta)
    app.add_exception_handler(ErrorDeLLM, _llm)
    app.add_exception_handler(ErrorDeEmbeddings, _embeddings)
    app.add_exception_handler(ErrorDeOrquestacion, _orquestacion)
    app.add_exception_handler(ErrorDeAlmacenamiento, _almacenamiento)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(Exception, _inesperado)
