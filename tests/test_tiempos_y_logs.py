"""
Diagnóstico de cuelgues — tests de límites de tiempo, logging y trazas por paso.

Todo con fakes: los "colgados" son modelos que esperan un Event (se liberan al terminar el test) y los
topes se bajan a décimas de segundo con monkeypatch, así que la suite sigue siendo instantánea.
"""

import logging
import sys
import threading

import pytest
import requests

import oci
from app import logging_config
from app.config import settings
from app.llm.gemini_client import ClienteGemini, ErrorDeLLM, _ModeloLangChain
from app.oci.almacenamiento import Almacenamiento, ErrorDeAlmacenamiento, _crear_cliente_oci
from app.rag.chunking import dividir_en_chunks
from app.rag.embeddings import ErrorDeEmbeddings, GeneradorDeEmbeddings
from app.ingesta.models import DocumentoIngerido, FormatoOrigen
from app.trazas import TiempoAgotado, ejecutar_con_limite, paso
from tests.test_api import (  # noqa: F401 — fixtures y ayudantes reutilizados
    FLASHCARDS_JSON,
    FakeModeloDeChat,
    FakeModeloDeEmbeddings,
    _post_archivo,
    _post_texto,
    construir,
    oci_falso,
    store,
)

TOPE = 0.2


@pytest.fixture
def colgado():
    """Evento que mantiene 'colgadas' las llamadas fake hasta el final del test."""
    evento = threading.Event()
    yield evento
    evento.set()


class ModeloDeChatColgado:
    def __init__(self, evento):
        self.evento = evento

    def invocar(self, prompt_sistema, prompt_usuario):
        self.evento.wait()
        return "nunca"


class ModeloDeEmbeddingsColgado:
    def __init__(self, evento):
        self.evento = evento

    def embed_documents(self, textos):
        self.evento.wait()
        return []

    def embed_query(self, texto):
        self.evento.wait()
        return []


class TestEjecutarConLimite:
    def test_devuelve_el_resultado(self):
        assert ejecutar_con_limite(lambda: 42, 1, "x") == 42

    def test_relanza_la_excepcion_original(self):
        def falla():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            ejecutar_con_limite(falla, 1, "x")

    def test_si_se_cuelga_lanza_tiempo_agotado(self, colgado):
        with pytest.raises(TiempoAgotado, match="tope"):
            ejecutar_con_limite(colgado.wait, TOPE, "llamada")

    def test_el_hilo_colgado_es_daemon(self, colgado):
        # Un hilo no daemon impediría que el proceso termine.
        with pytest.raises(TiempoAgotado):
            ejecutar_con_limite(colgado.wait, TOPE, "llamada-daemon")
        hilos = [h for h in threading.enumerate() if h.name == "limite-llamada-daemon"]
        assert hilos and all(h.daemon for h in hilos)


class TestTimeoutDeGemini:
    def test_se_traduce_a_error_de_llm(self, colgado, monkeypatch):
        monkeypatch.setattr(settings, "gemini_timeout_total_s", TOPE)
        cliente = ClienteGemini(modelo=ModeloDeChatColgado(colgado))

        with pytest.raises(ErrorDeLLM, match="no respondió a tiempo"):
            cliente.generar("s", "u")

    def test_el_modelo_langchain_pasa_plazo_y_desactiva_el_reintento_del_cliente(self):
        class Chat:
            def invoke(self, mensajes, **kwargs):
                self.kwargs = kwargs
                return type("R", (), {"content": "ok"})()

        chat = Chat()

        assert _ModeloLangChain(chat, timeout=12.5).invocar("s", "u") == "ok"
        assert chat.kwargs == {"timeout": 12.5, "retry": None}

    def test_sin_plazo_no_se_pasan_opciones(self):
        class Chat:
            def invoke(self, mensajes, **kwargs):
                self.kwargs = kwargs
                return type("R", (), {"content": "ok"})()

        chat = Chat()
        _ModeloLangChain(chat).invocar("s", "u")

        assert chat.kwargs == {}

    def test_la_api_responde_503_y_no_se_cuelga(self, construir, colgado, monkeypatch):
        monkeypatch.setattr(settings, "gemini_timeout_total_s", TOPE)
        cliente = construir()
        cliente_llm = cliente.app.dependency_overrides  # el servicio ya está armado con un chat fake
        servicio = next(iter(cliente_llm.values()))()
        servicio._orquestador._cliente = ClienteGemini(modelo=ModeloDeChatColgado(colgado))

        respuesta = _post_texto(cliente)

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "servicio_no_disponible"

    def test_un_429_falla_rapido_con_503(self, construir):
        cliente = construir(excepcion=RuntimeError("429 ResourceExhausted: cuota"))

        respuesta = _post_texto(cliente)

        assert respuesta.status_code == 503
        assert "429" not in respuesta.text


class TestTimeoutDeEmbeddings:
    def test_documentos_se_traduce_a_error_de_embeddings(self, colgado, monkeypatch):
        monkeypatch.setattr(settings, "embeddings_timeout_s", TOPE)
        generador = GeneradorDeEmbeddings(modelo=ModeloDeEmbeddingsColgado(colgado))
        doc = DocumentoIngerido(texto="hola mundo", nombre_archivo="a.txt", formato_origen=FormatoOrigen.TEXTO_PLANO)

        with pytest.raises(ErrorDeEmbeddings, match="no respondieron a tiempo"):
            generador.generar_embeddings(dividir_en_chunks(doc))

    def test_query_se_traduce_a_error_de_embeddings(self, colgado, monkeypatch):
        monkeypatch.setattr(settings, "embeddings_timeout_s", TOPE)
        generador = GeneradorDeEmbeddings(modelo=ModeloDeEmbeddingsColgado(colgado))

        with pytest.raises(ErrorDeEmbeddings, match="no respondió a tiempo"):
            generador.generar_embedding_query("hola")

    def test_la_api_responde_503_si_la_indexacion_se_cuelga(self, construir, store, colgado, monkeypatch):
        monkeypatch.setattr(settings, "embeddings_timeout_s", TOPE)
        cliente = construir()
        store._generador = GeneradorDeEmbeddings(modelo=ModeloDeEmbeddingsColgado(colgado))

        assert _post_texto(cliente).status_code == 503


class TestTimeoutDeOci:
    def test_read_timeout_activa_el_fallback_local(self, tmp_path):
        class OciLento:
            def put_object(self, *a, **k):
                raise requests.exceptions.ReadTimeout("read timed out")

        almacenamiento = Almacenamiento(cliente=OciLento(), carpeta_local=tmp_path, bucket="b", namespace="n")

        resultado = almacenamiento.subir_documento("a.txt", b"datos")

        assert resultado.status_upload == "pendiente_oci"
        assert (tmp_path / resultado.objeto_id).read_bytes() == b"datos"

    def test_connect_timeout_del_sdk_activa_el_fallback_local(self, tmp_path):
        class OciLento:
            def put_object(self, *a, **k):
                raise oci.exceptions.ConnectTimeout("connect timed out")

        almacenamiento = Almacenamiento(cliente=OciLento(), carpeta_local=tmp_path, bucket="b", namespace="n")

        assert almacenamiento.subir_documento("a.txt", b"x").status_upload == "pendiente_oci"

    def test_timeout_y_disco_roto_es_error_de_almacenamiento(self, tmp_path):
        class OciLento:
            def put_object(self, *a, **k):
                raise requests.exceptions.ReadTimeout("read timed out")

        no_es_carpeta = tmp_path / "archivo"
        no_es_carpeta.write_text("x")
        almacenamiento = Almacenamiento(cliente=OciLento(), carpeta_local=no_es_carpeta, bucket="b", namespace="n")

        with pytest.raises(ErrorDeAlmacenamiento):
            almacenamiento.subir_documento("a.txt", b"x")

    def test_el_cliente_real_se_crea_con_timeouts_de_conexion_y_lectura(self, tmp_path, monkeypatch):
        config = tmp_path / "config"
        config.write_text("")
        capturado = {}
        monkeypatch.setattr(oci.config, "DEFAULT_LOCATION", str(config))
        monkeypatch.setattr(oci.config, "from_file", lambda **k: {})
        monkeypatch.setattr(oci.config, "validate_config", lambda c: None)
        monkeypatch.setattr(
            oci.object_storage, "ObjectStorageClient", lambda c, **kw: capturado.update(kw) or object()
        )
        monkeypatch.setattr(settings, "oci_region", "sa-saopaulo-1")
        monkeypatch.setattr(settings, "oci_connect_timeout_s", 3.0)
        monkeypatch.setattr(settings, "oci_read_timeout_s", 17.0)

        _crear_cliente_oci()

        assert capturado == {"timeout": (3.0, 17.0)}


@pytest.fixture
def logging_limpio():
    """Restaura handlers y niveles de 'app' y de la librería tras configurar logging en el test."""
    nombres = ["app", *logging_config._LOGGERS_DE_LIBRERIAS]
    antes = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).level) for n in nombres}
    yield
    for n, (handlers, nivel) in antes.items():
        logging.getLogger(n).handlers[:] = handlers
        logging.getLogger(n).setLevel(nivel)


def _handlers_propios():
    return [h for h in logging.getLogger("app").handlers if getattr(h, logging_config._MARCA, False)]


class TestLogging:
    def test_la_app_lo_configura_al_importarse(self):
        import app.api.main  # noqa: F401

        assert len(_handlers_propios()) == 1
        assert logging.getLogger("app").level != logging.NOTSET

    def test_handler_a_stdout_con_hora_nivel_y_nombre(self, logging_limpio):
        logging.getLogger("app").handlers[:] = []

        logging_config.configurar_logging("INFO")

        (handler,) = _handlers_propios()
        assert handler.stream is sys.stdout
        registro = logging.LogRecord("app.x", logging.INFO, __file__, 1, "mensaje", None, None)
        linea = handler.format(registro)
        assert "INFO" in linea and "app.x" in linea and "mensaje" in linea
        assert linea[:4].isdigit()  # empieza con la hora (año)

    def test_es_idempotente(self, logging_limpio):
        logging_config.configurar_logging("INFO")
        logging_config.configurar_logging("INFO")

        assert len(_handlers_propios()) == 1

    @pytest.mark.parametrize(
        "valor, esperado",
        [("DEBUG", logging.DEBUG), ("warning", logging.WARNING), ("ERROR", logging.ERROR), ("NOEXISTE", logging.INFO)],
    )
    def test_nivel_configurable(self, logging_limpio, valor, esperado):
        logging_config.configurar_logging(valor)

        assert logging.getLogger("app").level == esperado

    def test_el_nivel_por_defecto_sale_de_settings(self, logging_limpio, monkeypatch):
        monkeypatch.setattr(settings, "log_level", "ERROR")

        logging_config.configurar_logging()

        assert logging.getLogger("app").level == logging.ERROR

    def test_los_reintentos_de_la_libreria_de_gemini_son_visibles(self, logging_limpio):
        logging_config.configurar_logging("INFO")

        lib = logging.getLogger("langchain_google_genai")
        assert lib.level == logging.WARNING and _handlers_propios()[0] in lib.handlers


MARCADOR = "MARCADOR_CONFIDENCIAL_XYZ"
PASOS_ESPERADOS = [
    "guardar_entrada", "ingesta", "subida_original", "indexacion", "busqueda",
    "generacion", "limpieza", "fidelidad", "subida_json",  # la limpieza del vector store sigue a la orquestación
]


def _lineas_de_pasos(caplog):
    return [r.getMessage() for r in caplog.records if "paso=" in r.getMessage()]


class TestTrazasPorPaso:
    def test_registra_inicio_y_fin_con_duracion_de_cada_paso(self, construir, caplog):
        caplog.set_level(logging.INFO, logger="app")

        assert _post_texto(construir()).status_code == 200

        lineas = _lineas_de_pasos(caplog)
        for nombre in PASOS_ESPERADOS:
            assert f"paso={nombre} inicio" in lineas
            assert any(l.startswith(f"paso={nombre} ok duracion=") and l.endswith("s") for l in lineas), nombre
        # y en el orden del pipeline
        inicios = [l.split()[0].removeprefix("paso=") for l in lineas if l.endswith("inicio")]
        assert inicios == PASOS_ESPERADOS

    def test_un_paso_que_falla_registra_el_paso_y_solo_el_tipo_de_excepcion(self, construir, caplog):
        caplog.set_level(logging.INFO, logger="app")

        respuesta = _post_texto(construir(excepcion=RuntimeError(f"clave AIzaSECRETA {MARCADOR}")))

        assert respuesta.status_code == 503
        fallos = [l for l in _lineas_de_pasos(caplog) if "FALLÓ" in l]
        assert any(l.startswith("paso=generacion FALLÓ duracion=") and l.endswith("error=ErrorDeLLM") for l in fallos)
        assert not any("AIzaSECRETA" in l or MARCADOR in l for l in _lineas_de_pasos(caplog))

    def test_las_trazas_no_incluyen_contenido_ni_nombre_del_documento(self, construir, caplog):
        caplog.set_level(logging.INFO, logger="app")
        texto = f"Las redes conectan. {MARCADOR}. El almacenamiento guarda. La seguridad protege."

        respuesta = _post_archivo(construir(), "informe_confidencial.md", texto.encode())

        assert respuesta.status_code == 200
        assert MARCADOR not in caplog.text
        assert "informe_confidencial" not in caplog.text
        assert _lineas_de_pasos(caplog)  # sí hubo trazas

    def test_la_solicitud_se_registra_solo_con_metadatos(self, construir, caplog):
        caplog.set_level(logging.INFO, logger="app")

        _post_texto(construir(), texto=f"redes {MARCADOR}")

        assert any("Solicitud: perfil=Principiante formato=Flashcards origen=texto" in m for m in caplog.messages)

    def test_paso_propaga_la_excepcion_y_mide_la_duracion(self, caplog):
        logger = logging.getLogger("app.prueba")
        caplog.set_level(logging.INFO, logger="app")

        with pytest.raises(KeyError):
            with paso(logger, "demo"):
                raise KeyError("dato sensible")

        assert "paso=demo FALLÓ duracion=" in caplog.text and "error=KeyError" in caplog.text
        assert "dato sensible" not in caplog.text
