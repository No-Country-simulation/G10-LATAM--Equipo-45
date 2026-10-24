"""
NM-16 — Integración con la API de Gemini (modelo de chat).

Envuelve ChatGoogleGenerativeAI (langchain-google-genai) detrás de una
interfaz mínima, con el mismo patrón que embeddings.py: el resto del
pipeline no depende de LangChain, y los tests (NM-14) corren con un modelo
falso, sin red y sin GOOGLE_API_KEY.

Uso típico:
    cliente = ClienteGemini()
    texto = cliente.generar(prompt_sistema, prompt_usuario)
"""

import logging
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)

# Temperatura baja: la salida tiene que ser JSON estable y anclado al documento fuente,
# no creativo. Con valores altos sube la chance de JSON roto o de datos inventados.
TEMPERATURA = 0.2


class ErrorDeLLM(Exception):
    """Error al llamar al LLM: API key faltante, rate limit, red, respuesta vacía, etc."""


class ModeloDeChat(Protocol):
    """Interfaz mínima que debe cumplir cualquier backend de chat."""

    def invocar(self, prompt_sistema: str, prompt_usuario: str) -> str: ...


class _ModeloLangChain:
    """
    Adapta ChatGoogleGenerativeAI a `ModeloDeChat`.

    LangChain trabaja con listas de mensajes y devuelve un objeto con `.content`; acá se
    traduce a "dos strings entran, un string sale" para no filtrar esos tipos al resto del código.
    """

    def __init__(self, chat):
        self._chat = chat

    def invocar(self, prompt_sistema: str, prompt_usuario: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        respuesta = self._chat.invoke(
            [SystemMessage(content=prompt_sistema), HumanMessage(content=prompt_usuario)]
        )
        contenido = respuesta.content
        if isinstance(contenido, str):
            return contenido
        # Algunos modelos devuelven una lista de partes (str o {"type": "text", "text": ...}).
        return "".join(
            parte if isinstance(parte, str) else parte.get("text", "") for parte in contenido
        )


def _crear_modelo_gemini() -> ModeloDeChat:
    """Crea el cliente real de Gemini. Falla rápido y con mensaje claro si falta la API key."""
    if not settings.google_api_key:
        raise ErrorDeLLM(
            "GOOGLE_API_KEY no está configurada. Completá el archivo .env "
            "(ver .env.example) antes de llamar a Gemini."
        )

    from langchain_google_genai import ChatGoogleGenerativeAI

    return _ModeloLangChain(
        ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.google_api_key,
            temperature=TEMPERATURA,
        )
    )


class ClienteGemini:
    """
    Cliente de chat de Gemini.

    Acepta un `modelo` inyectado (útil para tests con un fake que no llama a la
    API real). Si no se pasa nada, crea el cliente real en el primer uso (lazy),
    para que importar este módulo no requiera tener la API key configurada.
    """

    def __init__(self, modelo: ModeloDeChat | None = None):
        self._modelo = modelo

    @property
    def modelo(self) -> ModeloDeChat:
        if self._modelo is None:
            self._modelo = _crear_modelo_gemini()
        return self._modelo

    def generar(self, prompt_sistema: str, prompt_usuario: str) -> str:
        """
        Envía los prompts al modelo y devuelve el texto de la respuesta.

        Raises:
            ErrorDeLLM: si falta la API key, si el proveedor falla (rate limit,
                red, etc.) o si la respuesta viene vacía o solo con espacios.
        """
        try:
            texto = self.modelo.invocar(prompt_sistema, prompt_usuario)
        except ErrorDeLLM:
            raise
        except Exception as e:  # noqa: BLE001 — cualquier falla del proveedor se normaliza acá
            raise ErrorDeLLM(f"Fallo al llamar a Gemini: {e}") from e

        if not isinstance(texto, str) or not texto.strip():
            raise ErrorDeLLM("Gemini devolvió una respuesta vacía")

        return texto
