"""
NM-10 — Generación de embeddings vectoriales.

Envuelve el modelo de embeddings de Gemini (langchain-google-genai) detrás
de una interfaz simple, para que el resto del pipeline no dependa
directamente de LangChain y para poder testear (NM-14) sin necesitar una
GOOGLE_API_KEY real.

Uso típico:
    generador = GeneradorDeEmbeddings()
    vectores = generador.generar_embeddings(chunks)
"""

import logging
from typing import Protocol

from app.config import settings
from app.rag.models import Chunk
from app.trazas import TiempoAgotado, ejecutar_con_limite

logger = logging.getLogger(__name__)


class ErrorDeEmbeddings(Exception):
    """Error al generar embeddings: API key faltante, rate limit, respuesta inválida, etc."""


class ModeloDeEmbeddings(Protocol):
    """Interfaz mínima que debe cumplir cualquier backend de embeddings."""

    def embed_documents(self, textos: list[str]) -> list[list[float]]: ...
    def embed_query(self, texto: str) -> list[float]: ...


def _crear_modelo_gemini() -> ModeloDeEmbeddings:
    """Crea el cliente real de Gemini. Falla rápido y con mensaje claro si falta la API key."""
    if not settings.google_api_key:
        raise ErrorDeEmbeddings(
            "GOOGLE_API_KEY no está configurada. Completá el archivo .env "
            "(ver .env.example) antes de generar embeddings."
        )

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model=settings.gemini_embedding_model,
        google_api_key=settings.google_api_key,
    )


class GeneradorDeEmbeddings:
    """
    Genera embeddings para chunks de texto.

    Acepta un `modelo` inyectado (útil para tests con un mock que no llama
    a la API real). Si no se pasa nada, crea el cliente de Gemini en el
    primer uso real (lazy), para que importar este módulo no requiera tener
    la API key configurada.
    """

    def __init__(self, modelo: ModeloDeEmbeddings | None = None):
        self._modelo = modelo

    @property
    def modelo(self) -> ModeloDeEmbeddings:
        if self._modelo is None:
            self._modelo = _crear_modelo_gemini()
        return self._modelo

    def generar_embeddings(self, chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]:
        """
        Genera un embedding por cada chunk.

        Returns:
            Lista de tuplas (chunk, vector), en el mismo orden que la
            entrada. Lista vacía si `chunks` está vacío (no llama a la API).

        Raises:
            ErrorDeEmbeddings: si la API falla o devuelve una cantidad de
                vectores distinta a la cantidad de chunks pedidos.
        """
        if not chunks:
            return []

        textos = [chunk.texto for chunk in chunks]

        modelo = self.modelo
        try:
            vectores = ejecutar_con_limite(
                lambda: modelo.embed_documents(textos), settings.embeddings_timeout_s, "embeddings"
            )
        except ErrorDeEmbeddings:
            raise
        except TiempoAgotado as e:
            raise ErrorDeEmbeddings(f"Los embeddings no respondieron a tiempo: {e}") from e
        except Exception as e:  # noqa: BLE001 — cualquier falla del proveedor se normaliza acá
            raise ErrorDeEmbeddings(f"Fallo al generar embeddings: {e}") from e

        if len(vectores) != len(chunks):
            raise ErrorDeEmbeddings(
                f"El modelo devolvió {len(vectores)} vectores para {len(chunks)} chunks"
            )

        return list(zip(chunks, vectores))

    def generar_embedding_query(self, texto: str) -> list[float]:
        """Genera el embedding de una consulta (para búsqueda semántica, NM-11)."""
        if not texto or not texto.strip():
            raise ErrorDeEmbeddings("No se puede generar un embedding de una query vacía")

        modelo = self.modelo
        try:
            return ejecutar_con_limite(
                lambda: modelo.embed_query(texto), settings.embeddings_timeout_s, "embedding de query"
            )
        except ErrorDeEmbeddings:
            raise
        except TiempoAgotado as e:
            raise ErrorDeEmbeddings(f"El embedding de la query no respondió a tiempo: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise ErrorDeEmbeddings(f"Fallo al generar embedding de query: {e}") from e
