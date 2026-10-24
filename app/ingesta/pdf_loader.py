"""
NM-03 — Ingesta de PDF (PyPDF).

Extrae el texto de un archivo PDF, concatenando el contenido de todas las
páginas en orden. Maneja PDFs corruptos, vacíos y escaneados (sin capa de
texto) sin romper el pipeline.

Decisión de diseño (ver NM-03 en Trello): se preserva un separador de
página explícito en vez de entregar texto continuo, porque el chunking
(NM-09) puede necesitar saber dónde termina una página para no partir un
concepto a la mitad en el borde. El separador es configurable.
"""

import logging
import unicodedata
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.ingesta.models import DocumentoIngerido, ErrorDeIngesta, FormatoOrigen

logger = logging.getLogger(__name__)

SEPARADOR_PAGINA = "\n\n"


def cargar_pdf(ruta_archivo: str | Path) -> DocumentoIngerido:
    """
    Lee un archivo PDF y devuelve su texto concatenado.

    Args:
        ruta_archivo: path al archivo .pdf

    Returns:
        DocumentoIngerido con el texto extraído y metadata (num_paginas,
        paginas_sin_texto: lista de índices de páginas donde no se pudo
        extraer texto, útil para detectar PDFs escaneados).

    Raises:
        ErrorDeIngesta: si el archivo no existe, no es un PDF válido,
            está corrupto, o está encriptado sin contraseña provista.
    """
    ruta = Path(ruta_archivo)

    if not ruta.exists():
        raise ErrorDeIngesta(f"El archivo no existe: {ruta}")

    if ruta.suffix.lower() != ".pdf":
        raise ErrorDeIngesta(f"Extensión no soportada por pdf_loader: {ruta.suffix}")

    try:
        reader = PdfReader(str(ruta))
    except PdfReadError as e:
        raise ErrorDeIngesta(f"PDF corrupto o ilegible: {ruta.name} ({e})") from e
    except Exception as e:  # noqa: BLE001 — cualquier error de parseo se trata como ingesta fallida
        raise ErrorDeIngesta(f"No se pudo abrir el PDF: {ruta.name} ({e})") from e

    if reader.is_encrypted:
        try:
            # Intenta abrir con contraseña vacía (PDFs "encriptados" sin password real)
            reader.decrypt("")
        except Exception as e:
            raise ErrorDeIngesta(f"PDF encriptado, no se pudo desencriptar: {ruta.name}") from e

    num_paginas = len(reader.pages)
    if num_paginas == 0:
        raise ErrorDeIngesta(f"El PDF no tiene páginas: {ruta.name}")

    textos_por_pagina: list[str] = []
    paginas_sin_texto: list[int] = []

    for i, pagina in enumerate(reader.pages):
        try:
            texto_pagina = pagina.extract_text() or ""
        except Exception as e:  # noqa: BLE001 — una página rota no debe tumbar todo el documento
            logger.warning("No se pudo extraer texto de la página %d de %s: %s", i, ruta.name, e)
            texto_pagina = ""

        if not texto_pagina.strip():
            paginas_sin_texto.append(i)

        textos_por_pagina.append(texto_pagina.strip())

    # NFC: une letra + tilde descompuestas (NFD) en un solo carácter.
    texto_completo = unicodedata.normalize("NFC", SEPARADOR_PAGINA.join(textos_por_pagina).strip())

    documento = DocumentoIngerido(
        texto=texto_completo,
        nombre_archivo=ruta.name,
        formato_origen=FormatoOrigen.PDF,
        metadata={
            "num_paginas": num_paginas,
            "paginas_sin_texto": paginas_sin_texto,
            "posible_escaneado_sin_ocr": len(paginas_sin_texto) == num_paginas,
        },
    )

    if documento.esta_vacio:
        logger.warning(
            "PDF ingerido sin texto extraíble (probable escaneo sin OCR): %s", ruta.name
        )

    return documento
