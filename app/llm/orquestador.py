"""
NM-17 — Cadena de orquestación.

Flujo (según el doc de diseño):
    documento -> chunking -> embeddings e indexado -> recuperación de los
    fragmentos más relevantes -> prompt (perfil + formato + fragmentos)
    -> Gemini -> JSON parseado y validado.

Por qué recuperar fragmentos en vez de mandar el documento entero: el
prompt queda acotado aunque el documento sea un manual de 50+ páginas, y
el modelo trabaja sobre lo más relevante, lo que ayuda a que el contenido
generado quede anclado a la fuente.

Este módulo devuelve dataclasses internos. El schema Pydantic del endpoint
(NM-06) lo define otra persona y se mapea después desde acá.

TODO(NM-06): los campos `nicho_sector` y `nivel_detalle` del contrato del
endpoint todavía no se usan en la orquestación; incorporarlos a los prompts
cuando el schema NM-06 esté cerrado.
"""

import json
import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.ingesta.models import DocumentoIngerido, FormatoOrigen
from app.llm.gemini_client import ClienteGemini
from app.llm.prompts import (
    FormatoSalida,
    PerfilDestinatario,
    construir_prompt_sistema,
    construir_prompt_usuario,
)
from app.rag.chunking import dividir_en_chunks
from app.rag.vector_store import ResultadoBusqueda, VectorStore
from app.trazas import paso

logger = logging.getLogger(__name__)

# La query de recuperación es el título más esta frase genérica: el usuario no hace una pregunta
# concreta (pide "adaptar el documento"), así que se busca lo más representativo del tema.
FRASE_QUERY_GENERICA = "conceptos principales y puntos clave del documento"

# Campos obligatorios de cada ítem, según el formato de salida.
_CAMPOS_POR_FORMATO: dict[FormatoSalida, tuple[str, str]] = {
    FormatoSalida.FLASHCARDS: ("pregunta", "respuesta"),
    FormatoSalida.GUIA_PRACTICA: ("titulo", "detalle"),
}

# Claves envolventes que toleramos. La guía práctica se pide como {"pasos": [...]} (ver prompts.py),
# pero el modelo a veces devuelve la lista suelta o usa otra clave: se aceptan ambas formas.
_CLAVES_ENVOLVENTES = ("pasos", "flashcards", "items")

_RECORDATORIO_REINTENTO = (
    "\n\nTu respuesta anterior no fue JSON válido con la estructura pedida. "
    "Respondé ÚNICAMENTE con el JSON, sin texto ni bloques de código alrededor."
)

_REGEX_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class ErrorDeOrquestacion(Exception):
    """Error del flujo de orquestación: documento vacío o salida del LLM inválida tras reintentar."""


@dataclass
class ResultadoOrquestacion:
    """Resultado interno de adaptar un documento (NM-06 lo mapea al schema del endpoint)."""

    items: list[dict[str, str]]
    perfil: PerfilDestinatario
    formato: FormatoSalida
    fragmentos_usados: list[ResultadoBusqueda]
    modelo_usado: str | None = None  # modelo de Gemini que realmente respondió
    intentos_modelo: int = 0  # intentos de generación (modelos probados, sumando el reintento por JSON inválido)


def _extraer_json(texto: str) -> object:
    """Parsea la respuesta del modelo, tolerando bloques ```json ... ```."""
    candidato = texto.strip()
    fence = _REGEX_FENCE.search(candidato)
    if fence:
        candidato = fence.group(1)
    return json.loads(candidato)


def _validar_items(datos: object, formato: FormatoSalida) -> list[dict[str, str]]:
    """Verifica la forma del JSON según el formato; devuelve los ítems solo con los campos esperados."""
    if isinstance(datos, dict):
        for clave in _CLAVES_ENVOLVENTES:
            if isinstance(datos.get(clave), list):
                datos = datos[clave]
                break

    if not isinstance(datos, list) or not datos:
        raise ValueError("se esperaba una lista no vacía de ítems")

    campos = _CAMPOS_POR_FORMATO[formato]
    items: list[dict[str, str]] = []
    for i, item in enumerate(datos):
        if not isinstance(item, dict):
            raise ValueError(f"el ítem {i} no es un objeto")
        for campo in campos:
            valor = item.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                raise ValueError(f"el ítem {i} no tiene el campo '{campo}' como texto no vacío")
        items.append({campo: item[campo] for campo in campos})
    return items


class Orquestador:
    """
    Coordina vector store y Gemini para adaptar un documento.

    Ambas dependencias son inyectables: los tests usan un VectorStore sobre
    chromadb.EphemeralClient con embeddings falsos y un ClienteGemini con un
    modelo falso, así corren sin red ni GOOGLE_API_KEY.
    """

    def __init__(self, vector_store: VectorStore, cliente: ClienteGemini):
        self._store = vector_store
        self._cliente = cliente

    def adaptar(
        self,
        nombre_archivo: str,
        documento_titulo: str,
        documento_contenido: str,
        perfil: PerfilDestinatario,
        formato: FormatoSalida,
        top_k: int | None = None,
    ) -> ResultadoOrquestacion:
        """
        Adapta un documento a un perfil y formato.

        Raises:
            ErrorDeOrquestacion: documento sin texto útil, o el LLM devolvió JSON
                inválido (o con forma incorrecta) también en el reintento.
            ErrorDeLLM: falla de Gemini (se propaga tal cual, sin reintento).
            ErrorDeEmbeddings / ErrorDeVectorStore: fallas de la capa RAG (se propagan).
        """
        if not documento_contenido or not documento_contenido.strip():
            raise ErrorDeOrquestacion("El documento no tiene texto para adaptar")

        top_k = top_k if top_k is not None else settings.top_k_recuperacion

        # El contenido llega ya como texto (no sabemos si venía de PDF o Markdown): se trata como plano.
        documento = DocumentoIngerido(
            texto=documento_contenido.strip(),
            nombre_archivo=nombre_archivo,
            formato_origen=FormatoOrigen.TEXTO_PLANO,
        )
        chunks = dividir_en_chunks(documento)
        if not chunks:
            raise ErrorDeOrquestacion("El documento no tiene texto útil para adaptar")

        # Se borra la versión previa del documento: si el nuevo tiene menos chunks, los viejos
        # sobrantes se mezclarían en la recuperación filtrada por nombre_archivo.
        with paso(logger, "indexacion"):
            self._store.eliminar_documento(nombre_archivo)
            self._store.agregar_chunks(chunks)
        logger.info("indexacion: %d chunks", len(chunks))

        with paso(logger, "busqueda"):
            fragmentos = self._store.buscar(
                f"{documento_titulo}. {FRASE_QUERY_GENERICA}", top_k=top_k, nombre_archivo=nombre_archivo
            )
        # La búsqueda ordena por relevancia; para la prompt se reordena por posición original,
        # así una guía paso a paso conserva la secuencia del documento.
        fragmentos.sort(key=lambda f: f.metadata.get("indice", float("inf")))

        prompt_sistema = construir_prompt_sistema(perfil, formato)
        prompt_usuario = construir_prompt_usuario(
            documento_titulo, "\n\n".join(f.texto for f in fragmentos)
        )

        with paso(logger, "generacion"):
            items, modelo_usado, intentos = self._generar_items(prompt_sistema, prompt_usuario, formato)
        return ResultadoOrquestacion(
            items=items, perfil=perfil, formato=formato, fragmentos_usados=fragmentos,
            modelo_usado=modelo_usado, intentos_modelo=intentos,
        )

    def _generar_items(
        self, prompt_sistema: str, prompt_usuario: str, formato: FormatoSalida
    ) -> tuple[list[dict[str, str]], str | None, int]:
        """
        Llama a Gemini y valida el JSON; ante salida inválida reintenta UNA vez, con el modelo que respondió.

        Devuelve (ítems, modelo que respondió, intentos de modelo acumulados).
        """
        ultimo_error: Exception | None = None
        modelo: str | None = None
        intentos = 0
        for intento in range(2):
            prompt = prompt_usuario if intento == 0 else prompt_usuario + _RECORDATORIO_REINTENTO
            # ErrorDeLLM se propaga. El JSON inválido no cambia de modelo: el reintento sigue con el mismo.
            generado = self._cliente.generar_con_detalle(prompt_sistema, prompt, empezar_en=modelo)
            modelo = generado.modelo
            intentos += generado.intentos
            try:
                return _validar_items(_extraer_json(generado.texto), formato), modelo, intentos
            except (ValueError, TypeError) as e:  # JSONDecodeError es subclase de ValueError
                ultimo_error = e
                logger.warning("Salida inválida de Gemini (intento %d/2): %s", intento + 1, e)

        raise ErrorDeOrquestacion(
            f"Gemini no devolvió un JSON válido tras reintentar: {ultimo_error}"
        ) from ultimo_error
