"""
NM-25 / NM-26 — Lógica pura de la interfaz (sin Streamlit): opciones, validación previa y formateo del resultado.
"""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Etiqueta amigable -> valor EXACTO del enum del backend (app/llm/prompts.py). Hay un test que lo cruza con el enum.
PERFILES = {
    "Principiante": "Principiante",
    "Líder técnico / Arquitecto": "Lider Tecnico / Arquitecto",
}
FORMATOS = {
    "Flashcards": "Flashcards",
    "Guía práctica paso a paso": "Guia Practica Paso a Paso",
}

MENSAJE_SCORE_NO_DISPONIBLE = "No disponible"
AVISO_ANCLAJE = (
    "El puntaje mide qué tan anclado temáticamente está el contenido al documento, no si los datos son verdaderos. "
    "Revisá siempre el resultado contra la fuente."
)

_ESTADOS_ALMACENAMIENTO = {
    "exito": "Guardado en OCI",
    "pendiente_oci": "Pendiente de subir a OCI",
    "error": "No se pudo guardar",
}


def validar_entrada(
    *,
    texto: str | None,
    archivo: tuple[str, bytes] | None,
    max_bytes: int,
    extensiones: tuple[str, ...],
) -> list[str]:
    """Problemas de la entrada antes de llamar a la API (lista vacía = válida). Mismos límites que el backend."""
    limite_mb = max_bytes // (1024 * 1024)
    if archivo is not None:
        nombre, contenido = archivo
        extension = "." + nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
        problemas = []
        if extension not in extensiones:
            problemas.append(f"Formato de archivo no soportado. Subí un archivo {', '.join(extensiones)}.")
        if not contenido.strip():
            problemas.append("El archivo está vacío.")
        elif len(contenido) > max_bytes:
            problemas.append(f"El archivo supera el tamaño máximo permitido ({limite_mb} MB).")
        return problemas
    if texto is None or not texto.strip():
        return ["Subí un archivo o pegá el texto del documento."]
    if len(texto.encode("utf-8")) > max_bytes:
        return [f"El texto supera el tamaño máximo permitido ({limite_mb} MB)."]
    return []


def es_guia(contenido) -> bool:
    return isinstance(contenido, dict)


def items_flashcards(contenido) -> list[tuple[str, str]]:
    """[(pregunta, respuesta)] de una lista de flashcards; ignora entradas mal formadas."""
    if not isinstance(contenido, list):
        return []
    return [(str(c["pregunta"]), str(c["respuesta"])) for c in contenido if isinstance(c, dict) and "pregunta" in c and "respuesta" in c]


def items_guia(contenido) -> list[tuple[str, str]]:
    """[(titulo, detalle)] de una guía {"pasos": [...]}; ignora entradas mal formadas."""
    pasos = contenido.get("pasos") if isinstance(contenido, dict) else None
    if not isinstance(pasos, list):
        return []
    return [(str(p["titulo"]), str(p["detalle"])) for p in pasos if isinstance(p, dict) and "titulo" in p and "detalle" in p]


def texto_score(score) -> str:
    """Score de anclaje (0-1) con dos decimales, o "No disponible" si es null / no numérico."""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return MENSAJE_SCORE_NO_DISPONIBLE
    return f"{score:.2f}"


def texto_umbral(umbral) -> str:
    return texto_score(umbral)


def _zona(nombre: str):
    """ZoneInfo para `nombre`, o None si es inválida (el llamador cae a UTC)."""
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def texto_fecha(valor, zona: str = "UTC") -> str:
    """
    Fecha ISO 8601 de la API (UTC) en la zona IANA `zona`, con la zona en la etiqueta:
    '24/10/2026 12:30 (America/Asuncion)'. Si la zona es inválida o es UTC: '24/10/2026 15:30 UTC'.
    Si la fecha no se puede interpretar, 'No disponible'.
    """
    try:
        fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return "No disponible"
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    destino = None if zona.strip().upper() == "UTC" else _zona(zona.strip())
    if destino is None:
        return fecha.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    return f"{fecha.astimezone(destino):%d/%m/%Y %H:%M} ({zona.strip()})"


def texto_almacenamiento(resultado) -> str:
    """Estado de una subida a OCI en palabras, sin bucket, ruta ni objeto_id. None = todavía no existe."""
    if not isinstance(resultado, dict):
        return "No disponible"
    return _ESTADOS_ALMACENAMIENTO.get(resultado.get("status_upload"), "No disponible")


def json_formateado(respuesta: dict) -> str:
    return json.dumps(respuesta, ensure_ascii=False, indent=2)


def nombre_descarga(respuesta: dict) -> str:
    """Nombre de archivo seguro para el JSON descargado, derivado del título del documento."""
    titulo = str((respuesta.get("metadatos") or {}).get("documento_titulo") or "resultado")
    limpio = "".join(c if c.isalnum() else "_" for c in titulo).strip("_")[:50] or "resultado"
    return f"nuevamente_{limpio}.json"


def porcentaje_barra(score) -> float | None:
    """Ancho (0-100) de la barra de score; None si el score es null / no numérico. Se acota a [0, 100]."""
    if isinstance(score, bool) or not isinstance(score, (int, float)) or score != score:
        return None
    return round(min(max(score, 0.0), 1.0) * 100, 1)


def estado_confianza(baja_confianza) -> tuple[str, str]:
    """(clave de estilo, texto de la píldora). El texto va siempre: el color no es la única señal."""
    if baja_confianza:
        return "baja", "Baja confianza"
    return "normal", "Confianza normal"


def texto_caracteres(cantidad: int) -> str:
    """'1 carácter' / '12.345 caracteres' (separador de miles con punto)."""
    if cantidad == 1:
        return "1 carácter"
    return f"{cantidad:,}".replace(",", ".") + " caracteres"


def etiqueta_de(mapa: dict[str, str], valor) -> str:
    """Etiqueta amigable del valor del enum (inverso de PERFILES / FORMATOS); si no se conoce, el valor tal cual."""
    for etiqueta, enum in mapa.items():
        if enum == valor:
            return etiqueta
    return str(valor) if valor else "No disponible"


def posicion_umbral(umbral) -> float | None:
    """Posición (0-100) de la marca del umbral sobre la barra: el mismo cálculo y los mismos límites que el score."""
    return porcentaje_barra(umbral)


def posicion_etiqueta_umbral(umbral, minimo: float = 12.0, maximo: float = 88.0) -> float | None:
    """
    Posición (0-100) del centro de la etiqueta "Umbral 0.72", limitada a [minimo, maximo] para que el texto,
    centrado en ese punto, no se salga de la tarjeta cuando el umbral está cerca de 0 o de 1.
    La marca usa `posicion_umbral` (sin limitar); la etiqueta usa esta.
    """
    posicion = posicion_umbral(umbral)
    if posicion is None:
        return None
    return min(max(posicion, minimo), maximo)


def comparacion_umbral(score, umbral) -> tuple[str, str] | None:
    """
    (estado, frase) de comparar el score con el umbral, o None si falta alguno de los dos.
    Un score igual al umbral cuenta como que lo supera.
    """
    if porcentaje_barra(score) is None or porcentaje_barra(umbral) is None:
        return None
    if score >= umbral:
        return "supera", f"Supera el umbral mínimo ({texto_umbral(umbral)})"
    return "debajo", f"Queda por debajo del umbral mínimo ({texto_umbral(umbral)})"
