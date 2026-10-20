"""
NM-14 — Tests unitarios del cliente de Gemini (NM-16).

Usa un modelo de chat falso (FakeModeloDeChat) en vez de llamar a la API real,
para que los tests corran sin GOOGLE_API_KEY y sin costo/latencia de red.
"""

import pytest

from app.llm.gemini_client import ClienteGemini, ErrorDeLLM


class FakeModeloDeChat:
    """Modelo de chat determinístico para tests: no llama a ninguna API."""

    def __init__(self, respuesta: str = "respuesta", excepcion: Exception | None = None):
        self.respuesta = respuesta
        self.excepcion = excepcion
        self.llamadas: list[tuple[str, str]] = []

    def invocar(self, prompt_sistema: str, prompt_usuario: str) -> str:
        self.llamadas.append((prompt_sistema, prompt_usuario))
        if self.excepcion:
            raise self.excepcion
        return self.respuesta


class TestGenerar:
    def test_devuelve_el_texto_del_modelo_y_le_pasa_ambos_prompts(self):
        modelo = FakeModeloDeChat(respuesta='[{"pregunta": "a", "respuesta": "b"}]')
        cliente = ClienteGemini(modelo=modelo)

        texto = cliente.generar("sistema", "usuario")

        assert texto == '[{"pregunta": "a", "respuesta": "b"}]'
        assert modelo.llamadas == [("sistema", "usuario")]

    def test_excepcion_del_proveedor_se_normaliza_a_error_de_llm(self):
        modelo = FakeModeloDeChat(excepcion=RuntimeError("429 rate limit"))
        cliente = ClienteGemini(modelo=modelo)

        with pytest.raises(ErrorDeLLM, match="429 rate limit"):
            cliente.generar("sistema", "usuario")

    @pytest.mark.parametrize("respuesta", ["", "   \n\t "])
    def test_respuesta_vacia_o_solo_espacios_lanza_error_de_llm(self, respuesta):
        cliente = ClienteGemini(modelo=FakeModeloDeChat(respuesta=respuesta))

        with pytest.raises(ErrorDeLLM, match="vacía"):
            cliente.generar("sistema", "usuario")

    def test_sin_api_key_y_sin_modelo_inyectado_falla_con_mensaje_claro(self, monkeypatch):
        monkeypatch.setattr("app.llm.gemini_client.settings.google_api_key", "")
        cliente = ClienteGemini()  # sin modelo inyectado -> intenta crear el real

        with pytest.raises(ErrorDeLLM, match="GOOGLE_API_KEY"):
            cliente.generar("sistema", "usuario")
