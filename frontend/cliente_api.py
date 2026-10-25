"""
NM-27 — Cliente HTTP de la API de NuevaMente. No importa Streamlit: se testea sin levantar la interfaz.

Toda falla se traduce a `ErrorDeApi` con un mensaje en español apto para el usuario. Nunca se propaga una
excepción de httpx ni se copia texto crudo de una respuesta que no sea del formato de error de la API.
"""

from dataclasses import dataclass, field

import httpx

RUTA_ADAPTAR = "/api/v1/adaptar"

MENSAJE_CONEXION = "No pudimos conectarnos con el servidor. Verificá que la API esté levantada e intentá de nuevo."
MENSAJE_TIMEOUT = "La generación tardó más de lo esperado y se cortó. Probá de nuevo en un momento."
MENSAJE_MODELO = "El modelo no respondió o no pudo generar un resultado válido. Probá de nuevo en un momento."
MENSAJE_GENERICO = "Ocurrió un error inesperado. Probá de nuevo en un momento."
MENSAJE_RESPUESTA_INVALIDA = "El servidor devolvió una respuesta que no pudimos interpretar. Probá de nuevo."

# Tipos de error: la UI los usa para decidir el ícono/tono, no para mostrar texto.
CONEXION, TIMEOUT, VALIDACION, SERVIDOR = "conexion", "timeout", "validacion", "servidor"


# Solo estos errores pueden resolverse reintentando con el mismo documento; un 4xx (VALIDACION) no.
TIPOS_REINTENTABLES = (CONEXION, TIMEOUT, SERVIDOR)


@dataclass
class ErrorDeApi(Exception):
    mensaje: str
    tipo: str
    status: int | None = None
    detalles: list[dict] = field(default_factory=list)  # [{"campo": ..., "problema": ...}]

    def __str__(self) -> str:
        return self.mensaje

    @property
    def reintentable(self) -> bool:
        return self.tipo in TIPOS_REINTENTABLES


def _cuerpo_de_error(respuesta: httpx.Response) -> dict | None:
    """El cuerpo, solo si tiene el formato de error de la API ({"status": "error", "mensaje": ...})."""
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return None
    if isinstance(cuerpo, dict) and cuerpo.get("status") == "error" and isinstance(cuerpo.get("mensaje"), str):
        return cuerpo
    return None


def _detalles(cuerpo: dict) -> list[dict]:
    detalles = cuerpo.get("detalles")
    if not isinstance(detalles, list):
        return []
    return [
        {"campo": str(d.get("campo", "")), "problema": str(d.get("problema", ""))}
        for d in detalles
        if isinstance(d, dict)
    ]


def _error_http(respuesta: httpx.Response) -> ErrorDeApi:
    status = respuesta.status_code
    cuerpo = _cuerpo_de_error(respuesta)
    if status < 500:
        mensaje = cuerpo["mensaje"] if cuerpo else "No se pudo procesar la solicitud. Revisá los datos e intentá de nuevo."
        return ErrorDeApi(mensaje, VALIDACION, status, _detalles(cuerpo) if cuerpo else [])
    if status in (502, 503, 504):
        return ErrorDeApi(MENSAJE_MODELO, SERVIDOR, status)
    # 500 y otros 5xx: el mensaje de la API ya es amigable y sin detalles internos; si no vino, uno genérico.
    return ErrorDeApi(cuerpo["mensaje"] if cuerpo else MENSAJE_GENERICO, SERVIDOR, status)


def adaptar(
    base_url: str,
    perfil: str,
    formato: str,
    *,
    texto: str | None = None,
    archivo: tuple[str, bytes] | None = None,
    titulo: str | None = None,
    timeout_s: float = 150.0,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """
    POST /api/v1/adaptar. `perfil` y `formato` son los valores del enum del backend. Exactamente uno entre
    `texto` y `archivo` (nombre, bytes). Devuelve el JSON de éxito; ante cualquier falla lanza ErrorDeApi.

    `transport` permite inyectar un httpx.MockTransport en los tests.
    """
    if (texto is None) == (archivo is None):
        raise ValueError("Indicá texto o archivo, no ambos ni ninguno.")

    datos = {"perfil_destinatario": perfil, "formato_salida": formato}
    if titulo:
        datos["documento_titulo"] = titulo
    if texto is not None:
        datos["documento_contenido"] = texto
    archivos = {"archivo": (archivo[0], archivo[1])} if archivo else None

    try:
        with httpx.Client(
            base_url=base_url.rstrip("/"), timeout=httpx.Timeout(timeout_s, connect=10.0), transport=transport
        ) as cliente:
            respuesta = cliente.post(RUTA_ADAPTAR, data=datos, files=archivos)
    except httpx.TimeoutException as e:
        raise ErrorDeApi(MENSAJE_TIMEOUT, TIMEOUT) from e
    except httpx.TransportError as e:  # ConnectError, red caída, etc. (lo que no es timeout)
        raise ErrorDeApi(MENSAJE_CONEXION, CONEXION) from e
    except httpx.InvalidURL as e:
        raise ErrorDeApi("La URL de la API no es válida. Revisá API_BASE_URL.", CONEXION) from e

    if respuesta.status_code >= 400:
        raise _error_http(respuesta)
    try:
        cuerpo = respuesta.json()
    except ValueError as e:
        raise ErrorDeApi(MENSAJE_RESPUESTA_INVALIDA, SERVIDOR, respuesta.status_code) from e
    if not isinstance(cuerpo, dict) or "contenido_adaptado" not in cuerpo:
        raise ErrorDeApi(MENSAJE_RESPUESTA_INVALIDA, SERVIDOR, respuesta.status_code)
    return cuerpo
