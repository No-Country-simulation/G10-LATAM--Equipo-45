"""
Interfaz de salida común para todos los loaders de ingesta (NM-03, NM-04).

Cualquier loader nuevo que se agregue (ej. DOCX, HTML) debe devolver un
DocumentoIngerido para que el resto del pipeline (chunking, embeddings)
sea agnóstico al formato de origen.
"""

from dataclasses import dataclass, field
from enum import Enum


class FormatoOrigen(str, Enum):
    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXTO_PLANO = "texto_plano"


@dataclass
class DocumentoIngerido:
    """Resultado de ingestar un documento, sea cual sea su formato original."""

    texto: str
    nombre_archivo: str
    formato_origen: FormatoOrigen
    # Metadatos opcionales específicos del formato (ej. num_paginas para PDF)
    metadata: dict = field(default_factory=dict)

    @property
    def esta_vacio(self) -> bool:
        """True si no se pudo extraer ningún texto útil (ej. PDF escaneado sin OCR)."""
        return len(self.texto.strip()) == 0

    @property
    def longitud(self) -> int:
        return len(self.texto)


class ErrorDeIngesta(Exception):
    """Error al ingerir un documento: archivo corrupto, vacío, o extensión no soportada."""
