"""Tests de configuración (app/config.py)."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_vector_store_backend_distinto_de_chroma_lanza_error_de_validacion():
    with pytest.raises(ValidationError):
        Settings(vector_store_backend="faiss")


def test_vector_store_backend_por_defecto_es_chroma():
    assert Settings().vector_store_backend == "chroma"
