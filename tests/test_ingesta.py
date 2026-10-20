"""
Tests de ingesta (NM-03, NM-04), cubriendo los casos del test plan (NM-07):
PDF válido, PDF corrupto, PDF escaneado sin texto, Markdown, texto plano,
archivo vacío, extensión no soportada.
"""

import pytest

from app.ingesta.models import ErrorDeIngesta, FormatoOrigen
from app.ingesta.pdf_loader import cargar_pdf
from app.ingesta.text_loader import cargar_texto


class TestCargarPdf:
    def test_pdf_valido_extrae_texto_de_todas_las_paginas(self, pdf_valido):
        documento = cargar_pdf(pdf_valido)

        assert documento.formato_origen == FormatoOrigen.PDF
        assert "Introduccion a la Arquitectura" in documento.texto
        assert "Segunda pagina" in documento.texto
        assert documento.metadata["num_paginas"] == 2
        assert not documento.esta_vacio

    def test_pdf_corrupto_lanza_error_de_ingesta(self, pdf_corrupto):
        with pytest.raises(ErrorDeIngesta):
            cargar_pdf(pdf_corrupto)

    def test_pdf_sin_paginas_lanza_error_de_ingesta(self, pdf_vacio_sin_paginas):
        with pytest.raises(ErrorDeIngesta):
            cargar_pdf(pdf_vacio_sin_paginas)

    def test_pdf_escaneado_sin_texto_no_rompe_pero_queda_marcado(self, pdf_escaneado_sin_texto):
        documento = cargar_pdf(pdf_escaneado_sin_texto)

        assert documento.esta_vacio
        assert documento.metadata["posible_escaneado_sin_ocr"] is True

    def test_archivo_inexistente_lanza_error_de_ingesta(self, tmp_path):
        with pytest.raises(ErrorDeIngesta):
            cargar_pdf(tmp_path / "no_existe.pdf")

    def test_extension_incorrecta_lanza_error_de_ingesta(self, texto_plano_valido):
        with pytest.raises(ErrorDeIngesta):
            cargar_pdf(texto_plano_valido)


class TestCargarTexto:
    def test_markdown_valido_preserva_encabezados(self, markdown_valido):
        documento = cargar_texto(markdown_valido)

        assert documento.formato_origen == FormatoOrigen.MARKDOWN
        assert "## Seccion 1" in documento.texto
        assert documento.metadata["num_encabezados"] == 3  # 1 titulo + 2 secciones
        assert not documento.esta_vacio

    def test_texto_plano_valido(self, texto_plano_valido):
        documento = cargar_texto(texto_plano_valido)

        assert documento.formato_origen == FormatoOrigen.TEXTO_PLANO
        assert "Segunda linea" in documento.texto
        assert documento.metadata["num_lineas"] == 3

    def test_texto_con_tildes_y_enie_se_lee_sin_alterar(self, tmp_path):
        ruta = tmp_path / "acentos.txt"
        ruta.write_text("Configuración de la niña: año, señal, ¿qué?", encoding="utf-8")

        documento = cargar_texto(ruta)

        assert documento.texto == "Configuración de la niña: año, señal, ¿qué?"

    def test_bom_utf8_se_descarta(self, tmp_path):
        ruta = tmp_path / "con_bom.txt"
        ruta.write_bytes(b"\xef\xbb\xbf" + "Hola ñandú".encode("utf-8"))

        documento = cargar_texto(ruta)

        assert documento.texto == "Hola ñandú"

    def test_markdown_con_solo_encabezados_no_se_considera_vacio(self, tmp_path):
        ruta = tmp_path / "solo_titulos.md"
        ruta.write_text("# Titulo\n\n## Sub\n", encoding="utf-8")

        documento = cargar_texto(ruta)

        assert not documento.esta_vacio
        assert documento.metadata["num_encabezados"] == 2

    def test_archivo_vacio_devuelve_documento_vacio_sin_error(self, archivo_vacio):
        documento = cargar_texto(archivo_vacio)

        assert documento.esta_vacio
        assert documento.texto == ""

    def test_extension_no_soportada_lanza_error_de_ingesta(self, archivo_extension_no_soportada):
        with pytest.raises(ErrorDeIngesta):
            cargar_texto(archivo_extension_no_soportada)

    def test_archivo_inexistente_lanza_error_de_ingesta(self, tmp_path):
        with pytest.raises(ErrorDeIngesta):
            cargar_texto(tmp_path / "no_existe.md")

    def test_pdf_y_markdown_devuelven_la_misma_interfaz(self, pdf_valido, markdown_valido):
        """NM-03 y NM-04 deben ser intercambiables para el resto del pipeline."""
        doc_pdf = cargar_pdf(pdf_valido)
        doc_md = cargar_texto(markdown_valido)

        assert type(doc_pdf) is type(doc_md)
        assert hasattr(doc_pdf, "texto") and hasattr(doc_md, "texto")
        assert hasattr(doc_pdf, "esta_vacio") and hasattr(doc_md, "esta_vacio")


class TestNormalizacionNFC:
    A_DESCOMPUESTA = "á"  # 'a' + tilde combinante (NFD): 2 code points

    def test_texto_con_tilde_descompuesta_se_normaliza_a_un_solo_caracter(self, tmp_path):
        ruta = tmp_path / "nfd.txt"
        ruta.write_bytes(self.A_DESCOMPUESTA.encode("utf-8"))

        doc = cargar_texto(ruta)

        assert doc.texto == "á"
        assert len(doc.texto) == 1

    def test_pdf_con_tilde_descompuesta_se_normaliza_a_un_solo_caracter(self, tmp_path, monkeypatch):
        class _Pagina:
            def extract_text(self):
                return TestNormalizacionNFC.A_DESCOMPUESTA

        class _Reader:
            is_encrypted = False
            pages = [_Pagina()]

            def __init__(self, _ruta):
                pass

        monkeypatch.setattr("app.ingesta.pdf_loader.PdfReader", _Reader)
        ruta = tmp_path / "nfd.pdf"
        ruta.write_bytes(b"%PDF-falso")

        doc = cargar_pdf(ruta)

        assert doc.texto == "á"
        assert len(doc.texto) == 1
