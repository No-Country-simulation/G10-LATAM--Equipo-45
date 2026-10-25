"""Fixtures compartidas para los tests de NuevaMente."""

import io

import pytest
from pypdf import PdfWriter
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


@pytest.fixture(autouse=True)
def minimo_de_caracteres_bajo(monkeypatch):
    """
    Los fixtures históricos son textos de pocas líneas. Se baja el mínimo de MIN_CHARS_DOCUMENTO para que
    no choquen con la validación de largo; los tests de esa validación fijan su propio valor.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "min_chars_documento", 1)


@pytest.fixture
def pdf_valido(tmp_path):
    """Un PDF de 2 páginas con texto real extraíble."""
    ruta = tmp_path / "documento_valido.pdf"

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    c.drawString(72, 700, "Introduccion a la Arquitectura de Redes VCN en OCI")
    c.drawString(72, 680, "Una VCN es una red privada virtual dentro de Oracle Cloud.")
    c.showPage()
    c.drawString(72, 700, "Segunda pagina: subredes publicas y privadas.")
    c.showPage()
    c.save()

    ruta.write_bytes(buffer.getvalue())
    return ruta


@pytest.fixture
def pdf_corrupto(tmp_path):
    """Un archivo .pdf que no es un PDF válido (bytes arbitrarios)."""
    ruta = tmp_path / "documento_corrupto.pdf"
    ruta.write_bytes(b"esto no es un PDF valido, son bytes cualquiera \x00\x01\x02")
    return ruta


@pytest.fixture
def pdf_vacio_sin_paginas(tmp_path):
    """Un PDF técnicamente válido pero sin ninguna página."""
    ruta = tmp_path / "documento_sin_paginas.pdf"
    writer = PdfWriter()
    with open(ruta, "wb") as f:
        writer.write(f)
    return ruta


@pytest.fixture
def pdf_escaneado_sin_texto(tmp_path):
    """
    Simula un PDF escaneado: tiene una página pero sin ningún texto
    extraíble (en la realidad sería una imagen sin capa OCR).
    """
    ruta = tmp_path / "documento_escaneado.pdf"
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    # Página en blanco, sin drawString: no hay texto que extraer.
    c.showPage()
    c.save()
    ruta.write_bytes(buffer.getvalue())
    return ruta


@pytest.fixture
def markdown_valido(tmp_path):
    ruta = tmp_path / "documento.md"
    ruta.write_text(
        "# Titulo principal\n\n"
        "## Seccion 1\n"
        "Contenido de la seccion 1.\n\n"
        "## Seccion 2\n"
        "Contenido de la seccion 2.\n",
        encoding="utf-8",
    )
    return ruta


@pytest.fixture
def texto_plano_valido(tmp_path):
    ruta = tmp_path / "documento.txt"
    ruta.write_text("Primera linea.\nSegunda linea.\nTercera linea.", encoding="utf-8")
    return ruta


@pytest.fixture
def archivo_vacio(tmp_path):
    ruta = tmp_path / "vacio.txt"
    ruta.write_text("", encoding="utf-8")
    return ruta


@pytest.fixture
def archivo_extension_no_soportada(tmp_path):
    ruta = tmp_path / "documento.docx"
    ruta.write_text("contenido irrelevante", encoding="utf-8")
    return ruta
