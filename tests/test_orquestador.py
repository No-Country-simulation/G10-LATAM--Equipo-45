"""
NM-14 — Tests unitarios del orquestador (NM-17).

Todo con fakes: embeddings por palabras clave (sin API), un VectorStore sobre
chromadb.EphemeralClient (sin disco) y un modelo de chat que devuelve
respuestas guionadas (sin red ni GOOGLE_API_KEY).
"""

import json
import uuid

import chromadb
import pytest

from app.llm.gemini_client import ClienteGemini, ErrorDeLLM
from app.llm.orquestador import ErrorDeOrquestacion, Orquestador
from app.llm.prompts import FormatoSalida, PerfilDestinatario
from app.rag.embeddings import GeneradorDeEmbeddings
from app.rag.vector_store import VectorStore

PALABRAS_CLAVE = ["redes", "almacenamiento", "seguridad"]

FLASHCARDS_JSON = json.dumps([{"pregunta": "¿Qué es una VCN?", "respuesta": "Una red privada virtual."}])
GUIA_JSON = json.dumps([{"titulo": "Crear la VCN", "detalle": "Ir a Networking y crear la VCN."}])


class FakeModeloDeEmbeddings:
    """Embeddings por conteo de palabras clave: determinístico y sin API."""

    @staticmethod
    def _vector(texto: str) -> list[float]:
        # El 0.01 evita vectores nulos, que no tienen similitud coseno definida.
        return [float(texto.lower().count(p)) + 0.01 for p in PALABRAS_CLAVE]

    def embed_documents(self, textos):
        return [self._vector(t) for t in textos]

    def embed_query(self, texto):
        return self._vector(texto)


class FakeModeloDeChat:
    """Devuelve las respuestas guionadas en orden y registra los prompts recibidos."""

    def __init__(self, respuestas: list[str], excepcion: Exception | None = None):
        self.respuestas = list(respuestas)
        self.excepcion = excepcion
        self.llamadas: list[tuple[str, str]] = []

    def invocar(self, prompt_sistema: str, prompt_usuario: str) -> str:
        self.llamadas.append((prompt_sistema, prompt_usuario))
        if self.excepcion:
            raise self.excepcion
        return self.respuestas.pop(0)


@pytest.fixture(autouse=True)
def chunks_chicos(monkeypatch):
    """Un chunk por párrafo y sin overlap, para controlar qué fragmentos existen."""
    monkeypatch.setattr("app.rag.chunking.settings.chunk_size", 40)
    monkeypatch.setattr("app.rag.chunking.settings.chunk_overlap", 0)


@pytest.fixture
def store():
    return VectorStore(
        generador_embeddings=GeneradorDeEmbeddings(modelo=FakeModeloDeEmbeddings()),
        cliente=chromadb.EphemeralClient(),
        nombre_coleccion=f"test_{uuid.uuid4().hex}",
    )


def _orquestador(store, respuestas=None, excepcion=None):
    modelo = FakeModeloDeChat(respuestas or [FLASHCARDS_JSON], excepcion=excepcion)
    return Orquestador(store, ClienteGemini(modelo=modelo)), modelo


def _adaptar(orq, formato=FormatoSalida.FLASHCARDS, contenido=None, nombre="doc.md", top_k=None):
    contenido = contenido if contenido is not None else (
        "Las redes conectan recursos.\n\nEl almacenamiento guarda datos.\n\nLa seguridad protege todo."
    )
    return orq.adaptar(
        nombre_archivo=nombre,
        documento_titulo="Guia de seguridad",
        documento_contenido=contenido,
        perfil=PerfilDestinatario.PRINCIPIANTE,
        formato=formato,
        top_k=top_k,
    )


class TestCasoFeliz:
    def test_flashcards(self, store):
        orq, _ = _orquestador(store, [FLASHCARDS_JSON])

        resultado = _adaptar(orq, FormatoSalida.FLASHCARDS)

        assert resultado.items == [{"pregunta": "¿Qué es una VCN?", "respuesta": "Una red privada virtual."}]
        assert resultado.perfil == PerfilDestinatario.PRINCIPIANTE
        assert resultado.formato == FormatoSalida.FLASHCARDS
        assert len(resultado.fragmentos_usados) == 3

    def test_guia_practica(self, store):
        orq, _ = _orquestador(store, [GUIA_JSON])

        resultado = _adaptar(orq, FormatoSalida.GUIA_PRACTICA)

        assert resultado.items == [{"titulo": "Crear la VCN", "detalle": "Ir a Networking y crear la VCN."}]
        assert resultado.formato == FormatoSalida.GUIA_PRACTICA

    def test_guia_practica_tolera_el_envoltorio_pasos(self, store):
        orq, _ = _orquestador(store, [json.dumps({"pasos": json.loads(GUIA_JSON)})])

        resultado = _adaptar(orq, FormatoSalida.GUIA_PRACTICA)

        assert resultado.items[0]["titulo"] == "Crear la VCN"


class TestDocumentoVacio:
    @pytest.mark.parametrize("contenido", ["", "   \n  ", "###"])
    def test_documento_sin_texto_util_lanza_error_sin_llamar_a_gemini(self, store, contenido):
        orq, modelo = _orquestador(store)

        with pytest.raises(ErrorDeOrquestacion):
            _adaptar(orq, contenido=contenido)

        assert modelo.llamadas == []


class TestParseoDelJson:
    def test_json_con_fences_markdown(self, store):
        orq, _ = _orquestador(store, [f"```json\n{FLASHCARDS_JSON}\n```"])

        assert _adaptar(orq).items[0]["pregunta"] == "¿Qué es una VCN?"

    def test_json_invalido_con_reintento_exitoso(self, store):
        orq, modelo = _orquestador(store, ["esto no es json", FLASHCARDS_JSON])

        resultado = _adaptar(orq)

        assert resultado.items[0]["pregunta"] == "¿Qué es una VCN?"
        assert len(modelo.llamadas) == 2
        assert "no fue JSON válido" in modelo.llamadas[1][1]

    def test_json_invalido_dos_veces_lanza_error_tras_un_solo_reintento(self, store):
        orq, modelo = _orquestador(store, ["no json", "tampoco json", FLASHCARDS_JSON])

        with pytest.raises(ErrorDeOrquestacion, match="tras reintentar"):
            _adaptar(orq)

        assert len(modelo.llamadas) == 2

    @pytest.mark.parametrize(
        "salida",
        [
            json.dumps({"clave": "no es una lista"}),
            json.dumps([]),
            json.dumps(["texto suelto"]),
            json.dumps([{"titulo": "a", "detalle": "b"}]),  # campos de guía en un pedido de flashcards
            json.dumps([{"pregunta": "a", "respuesta": ""}]),
        ],
    )
    def test_estructura_con_forma_incorrecta_lanza_error(self, store, salida):
        orq, _ = _orquestador(store, [salida, salida])

        with pytest.raises(ErrorDeOrquestacion):
            _adaptar(orq, FormatoSalida.FLASHCARDS)


class TestRecuperacionYPrompt:
    def test_los_fragmentos_llegan_al_prompt_en_el_orden_del_documento(self, store):
        orq, modelo = _orquestador(store)

        resultado = _adaptar(orq)

        # Por relevancia (el título habla de "seguridad") el último párrafo sería el primero;
        # en el prompt deben ir por posición original.
        prompt_usuario = modelo.llamadas[0][1]
        posiciones = [
            prompt_usuario.index(t)
            for t in ("Las redes conectan", "El almacenamiento guarda", "La seguridad protege")
        ]
        assert posiciones == sorted(posiciones)
        assert [f.metadata["indice"] for f in resultado.fragmentos_usados] == [0, 1, 2]

    def test_top_k_limita_los_fragmentos_y_se_queda_con_los_mas_relevantes(self, store):
        orq, _ = _orquestador(store)

        resultado = _adaptar(orq, top_k=1)

        assert [f.texto for f in resultado.fragmentos_usados] == ["La seguridad protege todo."]

    def test_prompt_de_sistema_corresponde_al_perfil_y_formato(self, store):
        orq, modelo = _orquestador(store, [GUIA_JSON])

        _adaptar(orq, FormatoSalida.GUIA_PRACTICA)

        assert "guía práctica paso a paso" in modelo.llamadas[0][0]

    def test_el_filtro_por_nombre_archivo_evita_mezclar_documentos(self, store):
        orq, modelo = _orquestador(store, [FLASHCARDS_JSON, FLASHCARDS_JSON])
        _adaptar(orq, contenido="Otro documento sobre seguridad ajena.", nombre="otro.md")

        resultado = _adaptar(orq, nombre="doc.md", top_k=10)

        assert {f.nombre_archivo for f in resultado.fragmentos_usados} == {"doc.md"}
        assert "ajena" not in modelo.llamadas[1][1]

    def test_reindexar_una_version_mas_corta_no_deja_fragmentos_viejos(self, store):
        orq, modelo = _orquestador(store, [FLASHCARDS_JSON, FLASHCARDS_JSON])
        _adaptar(orq, nombre="doc.md")

        resultado = _adaptar(orq, nombre="doc.md", contenido="Solo queda redes.")

        assert [f.texto for f in resultado.fragmentos_usados] == ["Solo queda redes."]


class TestFallasDeGemini:
    def test_falla_de_gemini_se_propaga_como_error_de_llm_sin_reintentar(self, store):
        orq, modelo = _orquestador(store, excepcion=RuntimeError("503"))

        with pytest.raises(ErrorDeLLM):
            _adaptar(orq)

        assert len(modelo.llamadas) == 1
