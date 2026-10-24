"""
NM-04 — Ingesta de Markdown / texto plano.

Misma interfaz de salida que pdf_loader (NM-03): devuelve un
DocumentoIngerido, para que chunking y el resto del pipeline no necesiten
saber de qué formato vino el texto.

Decisión de diseño: se conserva el formato Markdown tal cual (no se
"limpia" a texto plano). El chunking puede aprovechar los encabezados
(#, ##) como puntos de corte naturales, y perderlos acá sería tirar
información gratis.
"""

import unicodedata
from pathlib import Path

from app.ingesta.models import DocumentoIngerido, ErrorDeIngesta, FormatoOrigen

EXTENSIONES_SOPORTADAS = {
    ".md": FormatoOrigen.MARKDOWN,
    ".markdown": FormatoOrigen.MARKDOWN,
    ".txt": FormatoOrigen.TEXTO_PLANO,
}


def cargar_texto(ruta_archivo: str | Path) -> DocumentoIngerido:
    """
    Lee un archivo .md, .markdown o .txt y devuelve su contenido.

    Args:
        ruta_archivo: path al archivo

    Returns:
        DocumentoIngerido con el texto leído y metadata (num_lineas,
        num_encabezados si es Markdown).

    Raises:
        ErrorDeIngesta: si el archivo no existe, la extensión no está
            soportada, o no se puede decodificar como UTF-8.
    """
    ruta = Path(ruta_archivo)

    if not ruta.exists():
        raise ErrorDeIngesta(f"El archivo no existe: {ruta}")

    extension = ruta.suffix.lower()
    if extension not in EXTENSIONES_SOPORTADAS:
        raise ErrorDeIngesta(
            f"Extensión no soportada por text_loader: '{extension}'. "
            f"Soportadas: {sorted(EXTENSIONES_SOPORTADAS)}"
        )

    try:
        # utf-8-sig: igual que utf-8, pero descarta el BOM si el editor (ej. Bloc de notas) lo agregó.
        contenido = ruta.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise ErrorDeIngesta(
            f"El archivo no está codificado en UTF-8: {ruta.name} ({e})"
        ) from e

    # NFC: une letra + tilde descompuestas (NFD) en un solo carácter.
    contenido = unicodedata.normalize("NFC", contenido)
    formato = EXTENSIONES_SOPORTADAS[extension]
    texto = contenido.strip()

    lineas = contenido.splitlines()
    metadata = {"num_lineas": len(lineas)}

    if formato == FormatoOrigen.MARKDOWN:
        metadata["num_encabezados"] = sum(
            1 for linea in lineas if linea.strip().startswith("#")
        )

    return DocumentoIngerido(
        texto=texto,
        nombre_archivo=ruta.name,
        formato_origen=formato,
        metadata=metadata,
    )
