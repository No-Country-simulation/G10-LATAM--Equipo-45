"""
NM-14 — Tests unitarios del vector store (NM-11).

Usa un generador de embeddings falso (FakeGeneradorDeEmbeddings) y un cliente
de Chroma en memoria (chromadb.EphemeralClient), para que los tests no
toquen disco ni llamen a la API real de Gemini.
"""

import uuid

import chromadb
import pytest

from app.rag.models import Chunk
from app.rag.vector_store import VectorStore

# Vectores fijos por texto. Se usan magnitudes distintas a propósito (no normalizadas)
# para verificar que la similitud depende del ángulo y no de la longitud del vector.
VECTORES = {
    "redes": [3.0, 0.0],
    "almacenamiento": [0.0, 5.0],
    "mixto": [1.0, 1.0],
    "consulta redes": [1.0, 0.0],
}


class FakeGeneradorDeEmbeddings:
    """Generador determinístico para tests: no llama a ninguna API."""

    def __init__(self):
        self.llamadas_generar_embeddings = 0
        self.llamadas_query = 0

    def generar_embeddings(self, chunks):
        self.llamadas_generar_embeddings += 1
        return [(chunk, VECTORES[chunk.texto]) for chunk in chunks]

    def generar_embedding_query(self, texto):
        self.llamadas_query += 1
        return VECTORES[texto]


def _chunk(texto: str, indice: int = 0, nombre_archivo: str = "test.md") -> Chunk:
    return Chunk(texto=texto, indice=indice, nombre_archivo=nombre_archivo, metadata={"formato_origen": "markdown"})


@pytest.fixture
def generador():
    return FakeGeneradorDeEmbeddings()


@pytest.fixture
def store(generador):
    # EphemeralClient comparte estado dentro del proceso: cada test usa una colección con nombre único.
    return VectorStore(
        generador_embeddings=generador,
        cliente=chromadb.EphemeralClient(),
        nombre_coleccion=f"test_{uuid.uuid4().hex}",
    )


class TestAgregarYBuscar:
    def test_indexa_y_encuentra_el_chunk_mas_similar_primero(self, store):
        store.agregar_chunks([_chunk("almacenamiento", 0), _chunk("redes", 1), _chunk("mixto", 2)])

        resultados = store.buscar("consulta redes", top_k=3)

        assert [r.texto for r in resultados] == ["redes", "mixto", "almacenamiento"]
        assert resultados[0].nombre_archivo == "test.md"
        assert resultados[0].metadata["formato_origen"] == "markdown"

    def test_score_es_similitud_coseno_y_no_depende_de_la_magnitud(self, store):
        store.agregar_chunks([_chunk("redes", 0), _chunk("almacenamiento", 1)])

        resultados = store.buscar("consulta redes", top_k=2)

        # [3,0] y [1,0] apuntan en la misma dirección -> similitud 1.0; [0,5] es ortogonal -> 0.0
        assert resultados[0].score == pytest.approx(1.0, abs=1e-4)
        assert resultados[1].score == pytest.approx(0.0, abs=1e-4)

    def test_scores_estan_ordenados_de_mayor_a_menor(self, store):
        store.agregar_chunks([_chunk("almacenamiento", 0), _chunk("mixto", 1), _chunk("redes", 2)])

        scores = [r.score for r in store.buscar("consulta redes", top_k=3)]

        assert scores == sorted(scores, reverse=True)

    def test_top_k_mayor_que_lo_indexado_devuelve_todo_sin_error(self, store):
        store.agregar_chunks([_chunk("redes", 0), _chunk("mixto", 1)])

        assert len(store.buscar("consulta redes", top_k=10)) == 2

    def test_top_k_limita_la_cantidad_de_resultados(self, store):
        store.agregar_chunks([_chunk("redes", 0), _chunk("mixto", 1), _chunk("almacenamiento", 2)])

        assert len(store.buscar("consulta redes", top_k=1)) == 1

    def test_agregar_lista_vacia_devuelve_cero_sin_llamar_al_generador(self, store, generador):
        assert store.agregar_chunks([]) == 0
        assert generador.llamadas_generar_embeddings == 0
        assert store.cantidad_indexada() == 0


class TestColeccionVaciaYParametrosInvalidos:
    def test_coleccion_vacia_devuelve_lista_vacia_sin_llamar_al_generador(self, store, generador):
        assert store.buscar("consulta redes") == []
        assert generador.llamadas_query == 0

    @pytest.mark.parametrize("top_k", [0, -1])
    def test_top_k_cero_o_negativo_lanza_error(self, store, top_k):
        with pytest.raises(ValueError):
            store.buscar("consulta redes", top_k=top_k)


class TestReindexar:
    def test_reindexar_el_mismo_documento_no_duplica(self, store):
        chunks = [_chunk("redes", 0), _chunk("almacenamiento", 1)]

        store.agregar_chunks(chunks)
        store.agregar_chunks(chunks)

        assert store.cantidad_indexada() == 2
        assert len(store.buscar("consulta redes", top_k=10)) == 2

    def test_reindexar_con_el_mismo_id_actualiza_el_contenido(self, store):
        store.agregar_chunks([_chunk("redes", 0)])
        store.agregar_chunks([_chunk("almacenamiento", 0)])  # mismo id: test.md::chunk_0

        resultados = store.buscar("consulta redes", top_k=10)

        assert store.cantidad_indexada() == 1
        assert [r.texto for r in resultados] == ["almacenamiento"]

    def test_documentos_distintos_con_mismo_indice_no_se_pisan(self, store):
        store.agregar_chunks([_chunk("redes", 0, "a.md"), _chunk("almacenamiento", 0, "b.md")])

        assert store.cantidad_indexada() == 2
