"""
NM-20 — Tests unitarios de la verificación de fidelidad.

Embeddings falsos y determinísticos (conteo de palabras clave): sin red ni
GOOGLE_API_KEY. El fake registra cada llamada para poder afirmar que los
embeddings se piden en batch.
"""

import pytest

from app.config import Settings
from app.llm.fidelidad import (
    ResultadoFidelidad,
    VerificadorDeFidelidad,
    extraer_unidades,
    similitud_coseno,
)
from app.llm.prompts import FormatoSalida
from app.rag.embeddings import ErrorDeEmbeddings, GeneradorDeEmbeddings
from app.rag.vector_store import ResultadoBusqueda

PALABRAS_CLAVE = ["redes", "almacenamiento", "seguridad"]


class FakeModeloDeEmbeddings:
    """Embeddings por conteo de palabras clave: un texto sin ninguna da vector nulo."""

    def __init__(self, fallar: bool = False):
        self.fallar = fallar
        self.llamadas: list[list[str]] = []

    def embed_documents(self, textos):
        if self.fallar:
            raise RuntimeError("fallo simulado de la API")
        self.llamadas.append(list(textos))
        return [[float(t.lower().count(p)) for p in PALABRAS_CLAVE] for t in textos]

    def embed_query(self, texto):  # pragma: no cover — el verificador no debe usarlo
        raise AssertionError("el verificador no debe usar embed_query")


def _fragmento(texto: str, indice: int = 0) -> ResultadoBusqueda:
    return ResultadoBusqueda(texto=texto, nombre_archivo="doc.md", metadata={"indice": indice}, score=1.0)


def _verificador(modelo=None, umbral=0.5):
    modelo = modelo or FakeModeloDeEmbeddings()
    return VerificadorDeFidelidad(GeneradorDeEmbeddings(modelo=modelo), umbral=umbral), modelo


def _flashcard(respuesta: str, pregunta: str = "¿Qué es?") -> dict[str, str]:
    return {"pregunta": pregunta, "respuesta": respuesta}


FRAGMENTOS = [
    _fragmento("Las redes conectan recursos. redes", 0),
    _fragmento("El almacenamiento guarda datos. almacenamiento", 1),
    _fragmento("La seguridad protege todo. seguridad", 2),
]


class TestSimilitudCoseno:
    def test_vectores_iguales_dan_uno(self):
        assert similitud_coseno([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_no_depende_de_la_magnitud(self):
        assert similitud_coseno([1.0, 2.0], [10.0, 20.0]) == pytest.approx(1.0)

    def test_vectores_ortogonales_dan_cero(self):
        assert similitud_coseno([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_vectores_opuestos_dan_menos_uno(self):
        assert similitud_coseno([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_vector_nulo_da_cero_sin_dividir_por_cero(self):
        assert similitud_coseno([0.0, 0.0], [1.0, 2.0]) == 0.0
        assert similitud_coseno([1.0, 2.0], [0.0, 0.0]) == 0.0
        assert similitud_coseno([0.0, 0.0], [0.0, 0.0]) == 0.0

    def test_dimensiones_distintas_lanza_value_error(self):
        with pytest.raises(ValueError):
            similitud_coseno([1.0, 2.0], [1.0, 2.0, 3.0])


class TestExtraerUnidades:
    def test_flashcards_usa_solo_la_respuesta(self):
        items = [
            {"pregunta": "¿Qué es una VCN?", "respuesta": "Una red privada."},
            {"pregunta": "¿Y una subred?", "respuesta": "Un segmento de la VCN."},
        ]

        unidades = extraer_unidades(items, FormatoSalida.FLASHCARDS)

        assert unidades == ["Una red privada.", "Un segmento de la VCN."]

    def test_guia_practica_une_titulo_y_detalle(self):
        items = [{"titulo": "Crear la VCN", "detalle": "Ir a Networking."}]

        unidades = extraer_unidades(items, FormatoSalida.GUIA_PRACTICA)

        assert unidades == ["Crear la VCN. Ir a Networking."]

    def test_items_con_campos_vacios_o_ausentes_se_saltean(self):
        items = [_flashcard("   "), {"pregunta": "sin respuesta"}, _flashcard("Válida.")]

        assert extraer_unidades(items, FormatoSalida.FLASHCARDS) == ["Válida."]

    def test_lista_vacia_no_da_unidades(self):
        assert extraer_unidades([], FormatoSalida.GUIA_PRACTICA) == []


class TestScore:
    def test_unidades_parecidas_a_la_fuente_dan_score_alto(self):
        verificador, _ = _verificador()
        items = [_flashcard("Las redes conectan."), _flashcard("La seguridad protege.")]

        resultado = verificador.verificar(items, FormatoSalida.FLASHCARDS, FRAGMENTOS)

        assert resultado.anclaje_fuente_score == pytest.approx(1.0)
        assert resultado.baja_confianza is False
        assert resultado.motivo == ""

    def test_unidades_distintas_a_la_fuente_dan_score_bajo(self):
        verificador, _ = _verificador()
        items = [_flashcard("Texto sobre cocina sin relación."), _flashcard("Fútbol y deportes.")]

        resultado = verificador.verificar(items, FormatoSalida.FLASHCARDS, FRAGMENTOS)

        assert resultado.anclaje_fuente_score == pytest.approx(0.0)
        assert resultado.baja_confianza is True

    def test_el_score_es_el_promedio_de_las_similitudes_maximas(self):
        verificador, _ = _verificador()
        # Una unidad idéntica a un fragmento (1.0) y una sin parecido (0.0): promedio 0.5.
        items = [_flashcard("redes"), _flashcard("cocina")]

        resultado = verificador.verificar(items, FormatoSalida.FLASHCARDS, FRAGMENTOS)

        assert resultado.anclaje_fuente_score == pytest.approx(0.5)

    def test_detalle_indica_unidad_similitud_maxima_e_indice_del_fragmento(self):
        verificador, _ = _verificador()
        items = [_flashcard("La seguridad protege."), _flashcard("Las redes conectan.")]

        resultado = verificador.verificar(items, FormatoSalida.FLASHCARDS, FRAGMENTOS)

        assert [(texto, indice) for texto, _, indice in resultado.detalle] == [
            ("La seguridad protege.", 2),
            ("Las redes conectan.", 0),
        ]
        assert all(sim == pytest.approx(1.0) for _, sim, _ in resultado.detalle)

    def test_funciona_con_guia_practica(self):
        verificador, _ = _verificador()
        items = [{"titulo": "Configurar la seguridad", "detalle": "Revisar la seguridad."}]

        resultado = verificador.verificar(items, FormatoSalida.GUIA_PRACTICA, FRAGMENTOS)

        assert resultado.detalle[0][2] == 2
        assert resultado.baja_confianza is False

    def test_el_score_se_acota_a_cero_si_la_similitud_es_negativa(self):
        class ModeloOpuesto:
            def embed_documents(self, textos):
                return [[-1.0, 0.0] if "unidad" in t else [1.0, 0.0] for t in textos]

            def embed_query(self, texto):  # pragma: no cover
                raise AssertionError

        verificador, _ = _verificador(ModeloOpuesto())

        resultado = verificador.verificar(
            [_flashcard("unidad")], FormatoSalida.FLASHCARDS, [_fragmento("fuente")]
        )

        assert resultado.detalle[0][1] == pytest.approx(-1.0)
        assert resultado.anclaje_fuente_score == 0.0


class TestUmbral:
    def test_score_igual_al_umbral_no_es_baja_confianza(self):
        verificador, _ = _verificador(umbral=0.5)
        items = [_flashcard("redes"), _flashcard("cocina")]  # score exacto 0.5

        resultado = verificador.verificar(items, FormatoSalida.FLASHCARDS, FRAGMENTOS)

        assert resultado.umbral == 0.5
        assert resultado.baja_confianza is False

    def test_score_por_debajo_del_umbral_es_baja_confianza(self):
        verificador, _ = _verificador(umbral=0.51)
        items = [_flashcard("redes"), _flashcard("cocina")]

        assert verificador.verificar(items, FormatoSalida.FLASHCARDS, FRAGMENTOS).baja_confianza is True

    def test_sin_umbral_explicito_usa_el_de_settings(self, monkeypatch):
        monkeypatch.setattr("app.llm.fidelidad.settings.umbral_anclaje", 0.42)

        verificador = VerificadorDeFidelidad(GeneradorDeEmbeddings(modelo=FakeModeloDeEmbeddings()))

        resultado = verificador.verificar([_flashcard("redes")], FormatoSalida.FLASHCARDS, FRAGMENTOS)
        assert resultado.umbral == 0.42

    def test_umbral_por_defecto_de_config_es_valido(self):
        assert 0.0 <= Settings().umbral_anclaje <= 1.0

    def test_umbral_de_config_fuera_de_rango_lanza_error(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(umbral_anclaje=1.5)


class TestCasosBorde:
    def test_sin_unidades_es_baja_confianza_sin_llamar_a_embeddings(self):
        verificador, modelo = _verificador()

        resultado = verificador.verificar([], FormatoSalida.FLASHCARDS, FRAGMENTOS)

        assert resultado.baja_confianza is True
        assert resultado.anclaje_fuente_score == 0.0
        assert resultado.detalle == []
        assert "unidades" in resultado.motivo
        assert modelo.llamadas == []

    def test_sin_fragmentos_es_baja_confianza_sin_llamar_a_embeddings(self):
        verificador, modelo = _verificador()

        resultado = verificador.verificar([_flashcard("redes")], FormatoSalida.FLASHCARDS, [])

        assert resultado.baja_confianza is True
        assert resultado.anclaje_fuente_score == 0.0
        assert resultado.detalle == [("redes", 0.0, -1)]
        assert "fragmentos" in resultado.motivo
        assert modelo.llamadas == []

    def test_error_de_embeddings_sube_tal_cual(self):
        verificador, _ = _verificador(FakeModeloDeEmbeddings(fallar=True))

        with pytest.raises(ErrorDeEmbeddings):
            verificador.verificar([_flashcard("redes")], FormatoSalida.FLASHCARDS, FRAGMENTOS)

    def test_dimensiones_inconsistentes_dan_baja_confianza_con_motivo(self):
        class ModeloInconsistente:
            def embed_documents(self, textos):
                return [[1.0, 0.0] if "unidad" in t else [1.0, 0.0, 0.0] for t in textos]

            def embed_query(self, texto):  # pragma: no cover
                raise AssertionError

        verificador, _ = _verificador(ModeloInconsistente())

        resultado = verificador.verificar(
            [_flashcard("unidad")], FormatoSalida.FLASHCARDS, [_fragmento("fuente")]
        )

        assert resultado.baja_confianza is True
        assert "inconsistentes" in resultado.motivo

    def test_vector_nulo_en_la_unidad_cuenta_como_sin_parecido(self):
        verificador, _ = _verificador()

        resultado = verificador.verificar([_flashcard("cocina")], FormatoSalida.FLASHCARDS, FRAGMENTOS)

        assert resultado.detalle[0][1] == 0.0
        assert isinstance(resultado, ResultadoFidelidad)


class TestBatch:
    def test_una_sola_llamada_por_conjunto(self):
        verificador, modelo = _verificador()
        items = [_flashcard("redes"), _flashcard("seguridad"), _flashcard("almacenamiento")]

        verificador.verificar(items, FormatoSalida.FLASHCARDS, FRAGMENTOS)

        # Exactamente dos llamadas: todas las unidades juntas y todos los fragmentos juntos.
        assert len(modelo.llamadas) == 2
        assert modelo.llamadas[0] == ["redes", "seguridad", "almacenamiento"]
        assert modelo.llamadas[1] == [f.texto for f in FRAGMENTOS]
