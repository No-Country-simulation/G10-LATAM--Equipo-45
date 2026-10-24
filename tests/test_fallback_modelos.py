"""
Cadena de modelos de respaldo de Gemini (GEMINI_MODEL + GEMINI_MODEL_FALLBACKS).

Todo con fakes, sin red: cada "modelo" es un guion de respuestas/excepciones, la espera entre modelos
(`dormir`) se registra en una lista en vez de dormir, y los topes de tiempo se bajan con monkeypatch.
"""

import logging
import threading

import pytest
from fastapi.testclient import TestClient
from google.api_core import exceptions as gexc
from pydantic import ValidationError

from app.api.dependencias import obtener_servicio
from app.api.main import app
from app.api.servicio import ServicioDeAdaptacion
from app.config import Settings, settings
from app.llm import gemini_client
from app.llm.fidelidad import VerificadorDeFidelidad
from app.llm.gemini_client import ClienteGemini, ErrorDeLLM
from app.llm.orquestador import Orquestador
from app.oci.almacenamiento import Almacenamiento
from app.rag.embeddings import GeneradorDeEmbeddings
from tests.test_api import FLASHCARDS_JSON, FakeModeloDeEmbeddings, _post_texto, oci_falso, store  # noqa: F401

CADENA = ("principal", "respaldo-1", "respaldo-2")


class ModeloGuionado:
    """Cada llamada consume un paso del guion: una excepción se lanza, un str se devuelve."""

    def __init__(self, *guion):
        self.guion = list(guion)
        self.llamadas = 0

    def invocar(self, prompt_sistema, prompt_usuario):
        self.llamadas += 1
        paso = self.guion.pop(0) if len(self.guion) > 1 else self.guion[0]
        if isinstance(paso, BaseException):
            raise paso
        return paso


class ModeloColgado:
    def __init__(self, evento):
        self.evento, self.llamadas = evento, 0

    def invocar(self, *a):
        self.llamadas += 1
        self.evento.wait()
        return "nunca"


@pytest.fixture
def colgado():
    evento = threading.Event()
    yield evento
    evento.set()


@pytest.fixture
def espera(monkeypatch):
    """Fija los parámetros de espera y devuelve la lista de esperas pedidas (nada duerme de verdad)."""
    monkeypatch.setattr(settings, "gemini_backoff_s", 2.0)
    monkeypatch.setattr(settings, "gemini_timeout_total_s", 30.0)
    return []


def _cliente(modelos: dict, espera: list, cadena=CADENA):
    """ClienteGemini sobre una cadena de fakes; `creados` registra qué modelos llegaron a construirse."""
    creados = []

    def fabrica(nombre):
        creados.append(nombre)
        return modelos[nombre]

    cliente = ClienteGemini(cadena=cadena, fabrica=fabrica, dormir=espera.append)
    cliente.creados = creados
    return cliente


def _http(cliente_llm, store, oci_falso, tmp_path):
    servicio = ServicioDeAdaptacion(
        orquestador=Orquestador(store, cliente_llm),
        verificador=VerificadorDeFidelidad(GeneradorDeEmbeddings(modelo=FakeModeloDeEmbeddings()), umbral=0.5),
        almacenamiento=Almacenamiento(cliente=oci_falso, carpeta_local=tmp_path, bucket="b", namespace="n"),
        vector_store=store,
        modelo="configurado-pero-no-usado",
    )
    app.dependency_overrides[obtener_servicio] = lambda: servicio
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _limpiar_overrides():
    yield
    app.dependency_overrides.clear()


class TestCadena:
    def test_el_principal_responde_y_no_se_toca_ningun_respaldo(self, espera):
        modelos = {"principal": ModeloGuionado("ok"), "respaldo-1": ModeloGuionado("x"), "respaldo-2": ModeloGuionado("x")}
        cliente = _cliente(modelos, espera)

        resultado = cliente.generar_con_detalle("s", "u")

        assert (resultado.texto, resultado.modelo, resultado.intentos) == ("ok", "principal", 1)
        assert cliente.creados == ["principal"]  # los respaldos ni siquiera se construyen
        assert espera == []

    def test_503_pasa_al_segundo_con_backoff(self, espera):
        modelos = {
            "principal": ModeloGuionado(gexc.ServiceUnavailable("alta demanda")),
            "respaldo-1": ModeloGuionado("ok"),
        }
        resultado = _cliente(modelos, espera).generar_con_detalle("s", "u")

        assert (resultado.modelo, resultado.intentos) == ("respaldo-1", 2)
        assert espera == [2.0]

    def test_404_salta_de_inmediato_sin_backoff(self, espera):
        modelos = {
            "principal": ModeloGuionado(gexc.NotFound("no longer available to new users")),
            "respaldo-1": ModeloGuionado("ok"),
        }
        resultado = _cliente(modelos, espera).generar_con_detalle("s", "u")

        assert resultado.modelo == "respaldo-1"
        assert espera == []

    def test_429_luego_504_luego_ok(self, espera):
        modelos = {
            "principal": ModeloGuionado(gexc.ResourceExhausted("cuota")),
            "respaldo-1": ModeloGuionado(gexc.DeadlineExceeded("timeout")),
            "respaldo-2": ModeloGuionado("ok"),
        }
        resultado = _cliente(modelos, espera).generar_con_detalle("s", "u")

        assert (resultado.modelo, resultado.intentos) == ("respaldo-2", 3)
        assert espera == [2.0, 2.0]

    def test_todos_fallan_lista_cada_intento_sin_exponer_claves(self, espera):
        modelos = {
            "principal": ModeloGuionado(gexc.ServiceUnavailable("503 key=AIzaSECRETA")),
            "respaldo-1": ModeloGuionado(gexc.NotFound("404")),
            "respaldo-2": ModeloGuionado(gexc.ResourceExhausted("429")),
        }
        with pytest.raises(ErrorDeLLM) as e:
            _cliente(modelos, espera).generar_con_detalle("s", "u")

        mensaje = str(e.value)
        assert "principal (ServiceUnavailable)" in mensaje
        assert "respaldo-1 (NotFound)" in mensaje
        assert "respaldo-2 (ResourceExhausted)" in mensaje
        assert "AIzaSECRETA" not in mensaje
        assert espera == [2.0]  # tras el último modelo no se espera; tras el 404 tampoco

    def test_todos_fallan_en_la_api_es_el_503_de_siempre(self, store, oci_falso, tmp_path, espera):
        modelos = {n: ModeloGuionado(gexc.ServiceUnavailable("x")) for n in CADENA}
        http = _http(_cliente(modelos, espera), store, oci_falso, tmp_path)

        respuesta = _post_texto(http)

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "servicio_no_disponible"
        assert "ServiceUnavailable" not in respuesta.text and "principal" not in respuesta.text

    @pytest.mark.parametrize(
        "error",
        [gexc.InvalidArgument("clave inválida"), gexc.PermissionDenied("403"), gexc.Unauthenticated("401")],
    )
    def test_errores_de_credenciales_no_prueban_otros_modelos(self, espera, error):
        modelos = {"principal": ModeloGuionado(error), "respaldo-1": ModeloGuionado("ok")}
        cliente = _cliente(modelos, espera)

        with pytest.raises(ErrorDeLLM, match="Fallo al llamar a Gemini"):
            cliente.generar("s", "u")

        assert modelos["respaldo-1"].llamadas == 0 and espera == []

    def test_error_de_credenciales_envuelto_por_langchain_tampoco_cambia_de_modelo(self, espera):
        envuelto = RuntimeError("Invalid argument provided to Gemini")
        envuelto.__cause__ = gexc.InvalidArgument("API key not valid")
        modelos = {"principal": ModeloGuionado(envuelto), "respaldo-1": ModeloGuionado("ok")}

        with pytest.raises(ErrorDeLLM):
            _cliente(modelos, espera).generar("s", "u")

        assert modelos["respaldo-1"].llamadas == 0

    def test_un_bug_propio_se_propaga_sin_cambiar_de_modelo(self, espera):
        modelos = {"principal": ModeloGuionado(TypeError("bug")), "respaldo-1": ModeloGuionado("ok")}

        with pytest.raises(ErrorDeLLM, match="bug"):
            _cliente(modelos, espera).generar("s", "u")

        assert modelos["respaldo-1"].llamadas == 0

    def test_presupuesto_total_agotado_corta_y_usa_el_error_de_timeout_existente(self, espera, colgado, monkeypatch):
        monkeypatch.setattr(settings, "gemini_timeout_total_s", 0.2)
        modelos = {"principal": ModeloColgado(colgado), "respaldo-1": ModeloGuionado("ok")}

        with pytest.raises(ErrorDeLLM, match="no respondió a tiempo"):
            _cliente(modelos, espera).generar("s", "u")

        assert modelos["respaldo-1"].llamadas == 0  # el presupuesto se gastó: no se prueban más modelos

    def test_el_timeout_por_llamada_pasa_al_siguiente_modelo(self, espera, colgado, monkeypatch):
        monkeypatch.setattr(gemini_client, "GRACIA_S", 0.0)
        monkeypatch.setattr(settings, "gemini_timeout_s", 0.2)
        modelos = {"principal": ModeloColgado(colgado), "respaldo-1": ModeloGuionado("ok")}

        resultado = _cliente(modelos, espera).generar_con_detalle("s", "u")

        assert resultado.modelo == "respaldo-1"

    def test_respuesta_vacia_no_cambia_de_modelo(self, espera):
        modelos = {"principal": ModeloGuionado("  "), "respaldo-1": ModeloGuionado("ok")}

        with pytest.raises(ErrorDeLLM, match="vacía"):
            _cliente(modelos, espera).generar("s", "u")

    def test_el_backoff_no_supera_el_presupuesto_restante(self, espera, monkeypatch):
        monkeypatch.setattr(settings, "gemini_timeout_total_s", 1.0)
        monkeypatch.setattr(settings, "gemini_backoff_s", 50.0)
        modelos = {"principal": ModeloGuionado(gexc.ServiceUnavailable("x")), "respaldo-1": ModeloGuionado("ok")}

        _cliente(modelos, espera).generar("s", "u")

        assert espera and espera[0] <= 1.0

    def test_sin_respaldos_la_cadena_es_solo_el_principal(self, espera):
        modelos = {"principal": ModeloGuionado(gexc.ServiceUnavailable("x"))}

        with pytest.raises(ErrorDeLLM, match="principal \\(ServiceUnavailable\\)"):
            _cliente(modelos, espera, cadena=("principal",)).generar("s", "u")

        assert espera == []


class TestMetadatosYLogs:
    def test_metadatos_modelo_es_el_que_respondio(self, store, oci_falso, tmp_path, espera):
        modelos = {
            "principal": ModeloGuionado(gexc.ServiceUnavailable("x")),
            "respaldo-1": ModeloGuionado(FLASHCARDS_JSON),
        }
        http = _http(_cliente(modelos, espera), store, oci_falso, tmp_path)

        respuesta = _post_texto(http)

        assert respuesta.status_code == 200
        assert respuesta.json()["metadatos"]["modelo"] == "respaldo-1"

    def test_json_invalido_usa_el_reintento_existente_y_no_cambia_de_modelo(self, store, oci_falso, tmp_path, espera):
        modelos = {"principal": ModeloGuionado("no es json", FLASHCARDS_JSON), "respaldo-1": ModeloGuionado("x")}
        cliente = _cliente(modelos, espera)
        http = _http(cliente, store, oci_falso, tmp_path)

        respuesta = _post_texto(http)

        assert respuesta.status_code == 200
        assert modelos["principal"].llamadas == 2 and modelos["respaldo-1"].llamadas == 0
        assert respuesta.json()["metadatos"]["modelo"] == "principal"
        assert espera == []

    def test_el_reintento_por_json_invalido_sigue_con_el_modelo_que_respondio(self, store, oci_falso, tmp_path, espera):
        modelos = {
            "principal": ModeloGuionado(gexc.ServiceUnavailable("x")),
            "respaldo-1": ModeloGuionado("no es json", FLASHCARDS_JSON),
        }
        http = _http(_cliente(modelos, espera), store, oci_falso, tmp_path)

        respuesta = _post_texto(http)

        assert respuesta.status_code == 200
        assert modelos["principal"].llamadas == 1  # no se vuelve a probar el que ya había fallado
        assert respuesta.json()["metadatos"]["modelo"] == "respaldo-1"

    def test_json_invalido_dos_veces_sigue_siendo_502(self, store, oci_falso, tmp_path, espera):
        modelos = {"principal": ModeloGuionado("no json"), "respaldo-1": ModeloGuionado("x")}
        http = _http(_cliente(modelos, espera), store, oci_falso, tmp_path)

        assert _post_texto(http).status_code == 502
        assert modelos["respaldo-1"].llamadas == 0

    def test_logs_de_cada_intento_y_modelo_usado(self, store, oci_falso, tmp_path, espera, caplog):
        caplog.set_level(logging.INFO, logger="app")
        modelos = {
            "principal": ModeloGuionado(gexc.ServiceUnavailable("x")),
            "respaldo-1": ModeloGuionado(gexc.NotFound("x")),
            "respaldo-2": ModeloGuionado(FLASHCARDS_JSON),
        }
        http = _http(_cliente(modelos, espera), store, oci_falso, tmp_path)

        assert _post_texto(http).status_code == 200

        mensajes = caplog.messages
        assert "paso=generacion modelo=principal intento=1 fallo=ServiceUnavailable pasando_a=respaldo-1" in mensajes
        assert "paso=generacion modelo=respaldo-1 intento=2 fallo=NotFound pasando_a=respaldo-2" in mensajes
        assert "paso=generacion modelo_usado=respaldo-2 intentos=3" in mensajes
        final = next(m for m in mensajes if m.startswith("Adaptación completada"))
        assert "modelo_usado=respaldo-2" in final and "intentos_modelo=3" in final

    def test_el_ultimo_modelo_que_falla_se_loguea_sin_siguiente(self, espera, caplog):
        caplog.set_level(logging.INFO, logger="app")
        modelos = {"principal": ModeloGuionado(gexc.ServiceUnavailable("x"))}

        with pytest.raises(ErrorDeLLM):
            _cliente(modelos, espera, cadena=("principal",)).generar("s", "u")

        assert "paso=generacion modelo=principal intento=1 fallo=ServiceUnavailable pasando_a=ninguno" in caplog.messages


def _config(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


class TestConfig:
    def test_valores_por_defecto(self):
        cfg = _config()

        assert cfg.gemini_model == "gemini-3.5-flash"
        assert cfg.gemini_backoff_s == 2
        assert cfg.gemini_cadena_modelos == ("gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite")

    def test_ignora_espacios_y_vacios(self):
        cfg = _config(gemini_model_fallbacks="  a ,, b  , ")

        assert cfg.gemini_cadena_modelos == ("gemini-3.5-flash", "a", "b")

    def test_ignora_duplicados_incluido_el_principal_y_conserva_el_orden(self):
        cfg = _config(gemini_model="x", gemini_model_fallbacks="y,x,z,y")

        assert cfg.gemini_cadena_modelos == ("x", "y", "z")

    def test_vacia_significa_sin_respaldos(self):
        assert _config(gemini_model_fallbacks="").gemini_cadena_modelos == ("gemini-3.5-flash",)
        assert _config(gemini_model_fallbacks=" , ").gemini_cadena_modelos == ("gemini-3.5-flash",)

    def test_quita_el_prefijo_models(self):
        cfg = _config(gemini_model="models/x", gemini_model_fallbacks="models/y, models/x")

        assert cfg.gemini_cadena_modelos == ("x", "y")

    def test_backoff_no_puede_ser_negativo(self):
        with pytest.raises(ValidationError):
            _config(gemini_backoff_s=-1)

    def test_el_cliente_toma_la_cadena_de_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "gemini_model", "uno")
        monkeypatch.setattr(settings, "gemini_model_fallbacks", "dos")

        assert ClienteGemini()._cadena == ("uno", "dos")
