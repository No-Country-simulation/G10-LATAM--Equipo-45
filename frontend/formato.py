"""
NM-25 / NM-26 — Lógica pura de la interfaz (sin Streamlit): opciones, validación previa y formateo del resultado.
"""

import json
from datetime import datetime, timezone

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


def texto_fecha(valor) -> str:
    """Fecha ISO 8601 de la API (UTC) como '24/10/2026 15:30 UTC'; si no se puede interpretar, 'No disponible'."""
    try:
        fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return "No disponible"
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


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
