"""Tests de configuración (app/config.py)."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_vector_store_backend_distinto_de_chroma_lanza_error_de_validacion():
    with pytest.raises(ValidationError):
        Settings(vector_store_backend="faiss")


def test_vector_store_backend_por_defecto_es_chroma():
    assert Settings().vector_store_backend == "chroma"


def test_limites_del_api_por_defecto():
    s = Settings()
    assert s.max_upload_mb == 10
    assert s.max_upload_bytes == 10 * 1024 * 1024
    assert s.extensiones_archivo == (".pdf", ".md", ".txt")


def test_extensiones_permitidas_se_normalizan():
    assert Settings(extensiones_permitidas=" PDF, .Md ,").extensiones_archivo == (".pdf", ".md")


def test_max_upload_mb_debe_ser_positivo():
    with pytest.raises(ValidationError):
        Settings(max_upload_mb=0)
