"""
NM-14 — Tests unitarios de embeddings (NM-10).

Usa un modelo falso (FakeModeloDeEmbeddings) en vez de llamar a la API real
de Gemini, para que los tests corran sin GOOGLE_API_KEY y sin costo/latencia
de red.
"""

import pytest

from app.ingesta.models import FormatoOrigen
from app.rag.embeddings import ErrorDeEmbeddings, GeneradorDeEmbeddings
from app.rag.models import Chunk

DIMENSION_FAKE = 8


class FakeModeloDeEmbeddings:
    """Modelo de embeddings determinístico para tests: no llama a ninguna API."""

    def __init__(self, fallar: bool = False, devolver_cantidad_incorrecta: bool = False):
        self.fallar = fallar
        self.devolver_cantidad_incorrecta = devolver_cantidad_incorrecta
        self.llamadas_embed_documents: list[list[str]] = []

    def embed_documents(self, textos: list[str]) -> list[list[float]]:
        if self.fallar:
            raise RuntimeError("fallo simulado de la API")

        self.llamadas_embed_documents.append(textos)
        vectores = [[float(len(t) % 10)] * DIMENSION_FAKE for t in textos]

        if self.devolver_cantidad_incorrecta:
            return vectores[:-1] if vectores else vectores

        return vectores

    def embed_query(self, texto: str) -> list[float]:
        if self.fallar:
            raise RuntimeError("fallo simulado de la API")
        return [float(len(texto) % 10)] * DIMENSION_FAKE


def _chunk(texto: str, indice: int = 0) -> Chunk:
    return Chunk(
        texto=texto,
        indice=indice,
        nombre_archivo="test.md",
        metadata={"formato_origen": FormatoOrigen.MARKDOWN.value},
    )


class TestGenerarEmbeddings:
    def test_lista_vacia_no_llama_al_modelo(self):
        modelo = FakeModeloDeEmbeddings()
        generador = GeneradorDeEmbeddings(modelo=modelo)

        resultado = generador.generar_embeddings([])

        assert resultado == []
        assert modelo.llamadas_embed_documents == []

    def test_genera_un_vector_por_chunk_en_el_mismo_orden(self):
        modelo = FakeModeloDeEmbeddings()
        generador = GeneradorDeEmbeddings(modelo=modelo)
        chunks = [_chunk("abc", 0), _chunk("abcdef", 1)]

        resultado = generador.generar_embeddings(chunks)

        assert len(resultado) == 2
        chunk0, vector0 = resultado[0]
        chunk1, vector1 = resultado[1]
        assert chunk0 is chunks[0]
        assert chunk1 is chunks[1]
        assert len(vector0) == DIMENSION_FAKE
        assert len(vector1) == DIMENSION_FAKE

    def test_falla_del_modelo_se_normaliza_a_error_de_embeddings(self):
        modelo = FakeModeloDeEmbeddings(fallar=True)
        generador = GeneradorDeEmbeddings(modelo=modelo)

        with pytest.raises(ErrorDeEmbeddings):
            generador.generar_embeddings([_chunk("abc")])

    def test_cantidad_de_vectores_distinta_a_chunks_lanza_error(self):
        modelo = FakeModeloDeEmbeddings(devolver_cantidad_incorrecta=True)
        generador = GeneradorDeEmbeddings(modelo=modelo)

        with pytest.raises(ErrorDeEmbeddings):
            generador.generar_embeddings([_chunk("abc"), _chunk("def", 1)])

    def test_generar_embedding_query(self):
        modelo = FakeModeloDeEmbeddings()
        generador = GeneradorDeEmbeddings(modelo=modelo)

        vector = generador.generar_embedding_query("que es una VCN")

        assert len(vector) == DIMENSION_FAKE

    def test_query_vacia_lanza_error_sin_llamar_al_modelo(self):
        modelo = FakeModeloDeEmbeddings()
        generador = GeneradorDeEmbeddings(modelo=modelo)

        with pytest.raises(ErrorDeEmbeddings):
            generador.generar_embedding_query("   ")

    def test_sin_api_key_y_sin_modelo_inyectado_falla_con_mensaje_claro(self, monkeypatch):
        monkeypatch.setattr("app.rag.embeddings.settings.google_api_key", "")
        generador = GeneradorDeEmbeddings()  # sin modelo inyectado -> intenta crear el real

        with pytest.raises(ErrorDeEmbeddings, match="GOOGLE_API_KEY"):
            generador.generar_embeddings([_chunk("abc")])
