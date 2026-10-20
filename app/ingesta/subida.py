"""
NM-12 — Ingesta + subida del documento original a OCI.

Orden deliberado: primero se ingiere y recién después se sube. Un archivo corrupto, de extensión
no soportada o sin texto útil (ej. PDF escaneado sin OCR) no llega al pipeline, así que guardarlo
en el bucket solo acumularía basura que nadie va a poder usar.
"""

from pathlib import Path

from app.ingesta.models import DocumentoIngerido
from app.ingesta.pdf_loader import cargar_pdf
from app.ingesta.text_loader import cargar_texto
from app.oci.almacenamiento import Almacenamiento, ResultadoSubida

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def ingerir_y_subir(
    ruta: str | Path, almacenamiento: Almacenamiento
) -> tuple[DocumentoIngerido, ResultadoSubida | None]:
    """
    Ingiere el archivo con el loader que corresponde a su extensión y sube el original.

    Returns:
        (documento, resultado). Si el documento no tiene texto útil, `resultado` es None y no se
        sube nada: el llamador decide qué hacer con un documento vacío (ej. 422 en el endpoint).

    Raises:
        ErrorDeIngesta: archivo inexistente, corrupto o de extensión no soportada (no se sube nada).
        ErrorDeAlmacenamiento: falló OCI y también el guardado local.
    """
    ruta = Path(ruta)
    extension = ruta.suffix.lower()
    documento = cargar_pdf(ruta) if extension == ".pdf" else cargar_texto(ruta)

    if documento.esta_vacio:
        return documento, None

    resultado = almacenamiento.subir_documento(ruta.name, ruta.read_bytes(), CONTENT_TYPES.get(extension))
    return documento, resultado
