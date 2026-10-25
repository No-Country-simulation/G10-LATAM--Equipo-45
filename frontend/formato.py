"""
NM-25 / NM-26 — Lógica pura de la interfaz (sin Streamlit): opciones, validación previa y formateo del resultado.
"""

import csv
import io
import json
import re
import unicodedata
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


def slug_titulo(titulo, maximo: int = 60) -> str:
    """Título saneado para un nombre de archivo: solo letras (sin tildes), números y guiones."""
    ascii_ = unicodedata.normalize("NFKD", str(titulo or "")).encode("ascii", "ignore").decode("ascii")
    limpio = re.sub(r"[^A-Za-z0-9]+", "-", ascii_).strip("-")[:maximo].strip("-")
    return limpio or "resultado"


def nombre_descarga(respuesta: dict, extension: str = "json") -> str:
    """'nuevamente-<título saneado>.<extensión>' para cualquiera de las descargas."""
    titulo = (respuesta.get("metadatos") or {}).get("documento_titulo")
    return f"nuevamente-{slug_titulo(titulo)}.{extension}"


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


def comparacion_umbral(score, umbral, propio: bool = False) -> tuple[str, str] | None:
    """
    (estado, frase) de comparar el score con el umbral, o None si falta alguno de los dos.
    Un score igual al umbral cuenta como que lo supera. Con `propio` el umbral es el que eligió la persona
    con el slider, no el oficial de la API.
    """
    if porcentaje_barra(score) is None or porcentaje_barra(umbral) is None:
        return None
    supera = score >= umbral
    estado = "supera" if supera else "debajo"
    if propio:
        return estado, f"Con tu umbral ({texto_umbral(umbral)}): " + ("lo supera" if supera else "queda por debajo")
    if supera:
        return estado, f"Supera el umbral mínimo ({texto_umbral(umbral)})"
    return estado, f"Queda por debajo del umbral mínimo ({texto_umbral(umbral)})"

# --------------------------------------------------------------------------------------
# Explicación de la nota, slider de umbral, descargas y tiempo
# --------------------------------------------------------------------------------------

SLIDER_MIN, SLIDER_MAX, SLIDER_PASO = 0.50, 0.95, 0.01


def unidades_de(contenido) -> int:
    """Cantidad de unidades del contenido generado: flashcards o pasos de la guía."""
    return len(items_guia(contenido)) if es_guia(contenido) else len(items_flashcards(contenido))


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def explicacion_nota(calidad: dict, unidades: int, fragmentos) -> list[str]:
    """
    Párrafos (markdown) del desplegable "¿Por qué esta nota?". La nota mide anclaje temático: nunca se presenta como
    porcentaje de verdad ni de aciertos.
    """
    baja = bool(calidad.get("baja_confianza"))
    if porcentaje_barra(calidad.get("anclaje_fuente_score")) is None:
        parrafos = [
            "Esta vez no se pudo calcular la nota. Puede pasar, por ejemplo, si falla el servicio de embeddings, que es el "
            "que permite comparar el contenido con el documento. El resultado se devuelve igual, pero sin nota: "
            "revisalo contra la fuente."
        ]
    else:
        parrafos = [
            "El contenido generado se divide en unidades (cada flashcard o cada paso). Cada unidad se compara con los "
            "fragmentos del documento que el sistema recuperó, y se toma la similitud más alta. La nota es el promedio "
            "de esas similitudes."
        ]
        if isinstance(fragmentos, int) and not isinstance(fragmentos, bool) and fragmentos > 0 and unidades > 0:
            parrafos.append(
                f"En este resultado se compararon {_plural(unidades, 'unidad', 'unidades')} contra "
                f"{_plural(fragmentos, 'fragmento', 'fragmentos')} del documento."
            )
        parrafos.append(
            "Una nota cercana a 1 indica que el contenido trata los mismos temas que el documento. Mide anclaje "
            "temático: **no verifica** que cada dato sea verdadero. Revisá siempre contra la fuente."
        )
    if baja:
        parrafos.append(
            "La nota quedó por debajo del umbral, así que conviene que una persona revise el contenido antes de usarlo."
        )
    return parrafos


def umbral_para_slider(umbral) -> float | None:
    """Valor inicial del slider: el umbral oficial a dos decimales, dentro del rango del slider. None si no hay umbral."""
    if porcentaje_barra(umbral) is None:
        return None
    return round(min(max(float(umbral), SLIDER_MIN), SLIDER_MAX), 2)


def _celda_segura(valor) -> str:
    """Evita la inyección de fórmulas en hojas de cálculo: una celda que empieza con = + - @ (o tab / CR) lleva un apóstrofo."""
    texto = str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def csv_flashcards(tarjetas: list[tuple[str, str]]) -> str:
    """CSV de dos columnas (pregunta, respuesta), sin encabezado, para importar en Anki. Lo escapa el módulo csv."""
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    for pregunta, respuesta in tarjetas:
        escritor.writerow([_celda_segura(pregunta), _celda_segura(respuesta)])
    return salida.getvalue()


def markdown_guia(titulo, pasos: list[tuple[str, str]]) -> str:
    """Guía en Markdown: título del documento y un encabezado por paso numerado, con su detalle."""
    def una_linea(texto) -> str:
        return " ".join(str(texto or "").split())

    lineas = [f"# {una_linea(titulo) or 'Guía práctica'}", ""]
    for numero, (paso, detalle) in enumerate(pasos, start=1):
        lineas += [f"## {numero}. {una_linea(paso)}", "", str(detalle).strip(), ""]
    return "\n".join(lineas).rstrip("\n") + "\n"


def texto_duracion(segundos) -> str:
    """'12,3 s', o 'No disponible' si no hay medición."""
    if isinstance(segundos, bool) or not isinstance(segundos, (int, float)) or segundos < 0:
        return "No disponible"
    return f"{segundos:.1f}".replace(".", ",") + " s"
