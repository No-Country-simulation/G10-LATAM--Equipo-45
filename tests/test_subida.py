"""
NM-12 — Tests de ingerir_y_subir: solo se sube el original si la ingesta produjo texto útil.

Usa un cliente falso de OCI (el mismo patrón de fakes que test_almacenamiento.py): sin red.
"""

import pytest

from app.ingesta.models import ErrorDeIngesta
from app.ingesta.subida import ingerir_y_subir
from app.oci.almacenamiento import Almacenamiento
from tests.test_almacenamiento import BUCKET, NAMESPACE, FakeClienteDeObjetos


@pytest.fixture
def cliente():
    return FakeClienteDeObjetos()


@pytest.fixture
def almacenamiento(tmp_path, cliente):
    return Almacenamiento(
        cliente=cliente, carpeta_local=tmp_path / "local", bucket=BUCKET, namespace=NAMESPACE
    )


def test_pdf_valido_se_ingiere_y_se_sube_el_original(pdf_valido, almacenamiento, cliente):
    documento, resultado = ingerir_y_subir(pdf_valido, almacenamiento)

    assert "VCN" in documento.texto
    assert resultado.status_upload == "exito"
    assert resultado.objeto_id.startswith("documentos/")
    assert resultado.objeto_id.endswith("-documento_valido.pdf")
    assert cliente.objetos[resultado.objeto_id] == pdf_valido.read_bytes()
    assert cliente.llamadas_put[0]["content_type"] == "application/pdf"


def test_markdown_valido_se_sube_con_su_content_type(markdown_valido, almacenamiento, cliente):
    _, resultado = ingerir_y_subir(markdown_valido, almacenamiento)

    assert resultado.status_upload == "exito"
    assert cliente.llamadas_put[0]["content_type"] == "text/markdown; charset=utf-8"


def test_pdf_corrupto_lanza_error_de_ingesta_y_no_sube(pdf_corrupto, almacenamiento, cliente, tmp_path):
    with pytest.raises(ErrorDeIngesta):
        ingerir_y_subir(pdf_corrupto, almacenamiento)

    assert cliente.llamadas_put == []
    assert not (tmp_path / "local").exists()


def test_extension_no_soportada_no_sube(archivo_extension_no_soportada, almacenamiento, cliente):
    with pytest.raises(ErrorDeIngesta):
        ingerir_y_subir(archivo_extension_no_soportada, almacenamiento)

    assert cliente.llamadas_put == []


def test_pdf_escaneado_sin_texto_no_sube(pdf_escaneado_sin_texto, almacenamiento, cliente, tmp_path):
    documento, resultado = ingerir_y_subir(pdf_escaneado_sin_texto, almacenamiento)

    assert documento.esta_vacio
    assert resultado is None
    assert cliente.llamadas_put == []
    assert not (tmp_path / "local").exists()
