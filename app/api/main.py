"""
NM-18 — Aplicación FastAPI de NuevaMente.

    uvicorn app.api.main:app --reload

Los endpoints son funciones síncronas (`def`, no `async def`): el pipeline usa librerías bloqueantes
(Chroma, SDK de OCI, Gemini). FastAPI ejecuta las `def` en un pool de hilos; con `async def` cada
solicitud bloquearía el event loop y el servidor no atendería nada más mientras tanto.
"""

import logging

from fastapi import Depends, FastAPI, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.dependencias import obtener_servicio
from app.api.errores import ErrorDeTamano, registrar_manejadores
from app.api.schemas import ErrorRespuesta, FormatoSalida, PerfilDestinatario, RespuestaAdaptacion, SolicitudAdaptacion
from app.api.servicio import ServicioDeAdaptacion
from app.config import settings
from app.logging_config import configurar_logging

configurar_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="NuevaMente API",
    description="Adapta documentación técnica a un perfil y formato pedagógico, anclada a la fuente.",
    version="1.0.0",
)
registrar_manejadores(app)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: no toca ningún servicio externo."""
    return {"status": "ok"}


@app.post(
    "/api/v1/adaptar",
    response_model=RespuestaAdaptacion,
    responses={status: {"model": ErrorRespuesta} for status in (413, 422, 500, 502, 503)},
)
def adaptar(
    perfil_destinatario: PerfilDestinatario = Form(...),
    formato_salida: FormatoSalida = Form(...),
    archivo: UploadFile | None = File(default=None, description="Documento .pdf, .md o .txt"),
    documento_contenido: str | None = Form(default=None, description="Texto del documento (alternativo a 'archivo')"),
    documento_titulo: str | None = Form(default=None),
    nicho_sector: str | None = Form(default=None),
    nivel_detalle: str | None = Form(default=None),
    servicio: ServicioDeAdaptacion = Depends(obtener_servicio),
) -> RespuestaAdaptacion:
    """Adapta un documento (archivo O texto, exactamente uno) al perfil y formato pedidos."""
    limite = settings.max_upload_bytes

    nombre_archivo, contenido_archivo = None, None
    if archivo is not None:
        nombre_archivo = archivo.filename or None
        # Se lee a lo sumo limite+1 bytes: alcanza para saber si se pasó sin cargar un archivo enorme.
        contenido_archivo = archivo.file.read(limite + 1)
        if len(contenido_archivo) > limite:
            raise ErrorDeTamano(settings.max_upload_mb, campo="archivo")
    if documento_contenido is not None and len(documento_contenido.encode("utf-8")) > limite:
        raise ErrorDeTamano(settings.max_upload_mb, campo="documento_contenido")

    try:
        solicitud = SolicitudAdaptacion(
            perfil_destinatario=perfil_destinatario,
            formato_salida=formato_salida,
            documento_titulo=documento_titulo,
            documento_contenido=documento_contenido,
            nombre_archivo=nombre_archivo,
            contenido_archivo=contenido_archivo,
            nicho_sector=nicho_sector,
            nivel_detalle=nivel_detalle,
        )
    except ValidationError as e:
        # Se re-lanza como RequestValidationError para que lo formatee el mismo manejador que el 422 de FastAPI.
        raise RequestValidationError(e.errors()) from e

    return servicio.adaptar(solicitud)
