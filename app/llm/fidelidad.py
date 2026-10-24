"""
NM-20 — Verificación de fidelidad del contenido generado.

Pregunta que responde: ¿lo que generó el LLM está respaldado por los fragmentos
de la fuente? Se mide con similitud de embeddings entre cada "unidad" del
contenido generado (una respuesta, un paso) y los fragmentos recuperados,
SIN un segundo LLM como juez: no consume cuota de generación, es determinístico
y barato (dos llamadas batch de embeddings por respuesta).

Es una señal, no una garantía: la similitud semántica detecta contenido que se
va de tema o que no se parece a nada de la fuente, pero un dato inventado sobre
el mismo tema puede seguir pareciéndose a la fuente. Por eso, si el anclaje es
bajo la respuesta se marca como baja confianza pero NO se bloquea: decide el
backend/UI qué hacer con la marca. El umbral es provisorio hasta calibrarlo
con scripts/calibrar_fidelidad.py.

Este módulo todavía no está conectado al Orquestador ni al endpoint.
"""

import logging
import math
from dataclasses import dataclass, field

from app.config import settings
from app.llm.prompts import FormatoSalida
from app.rag.embeddings import ErrorDeEmbeddings, GeneradorDeEmbeddings
from app.rag.models import Chunk
from app.rag.vector_store import ResultadoBusqueda

logger = logging.getLogger(__name__)

# Nombre de archivo de los Chunk descartables con los que se reutiliza GeneradorDeEmbeddings.
_ORIGEN_TEMPORAL = "fidelidad"


@dataclass
class ResultadoFidelidad:
    """
    Resultado de verificar el anclaje del contenido generado a la fuente.

    `anclaje_fuente_score` mide ANCLAJE TEMÁTICO a los fragmentos recuperados, no
    veracidad: un dato inventado sobre el mismo tema puede puntuar alto. En la
    calibración (12 casos) los fieles dieron 0.805-0.900, los inventados del mismo
    tema 0.777-0.856 (se solapan) y los de otro tema 0.611-0.661.

    `detalle` tiene una tupla por unidad evaluada:
    (texto de la unidad, similitud máxima contra los fragmentos, posición en la
    lista `fragmentos` del fragmento más parecido; -1 si no hubo comparación).
    `motivo` queda vacío en el caso normal y explica por qué hubo baja confianza
    cuando no se pudo medir (sin unidades, sin fragmentos, vectores inválidos).
    """

    anclaje_fuente_score: float
    baja_confianza: bool
    umbral: float
    detalle: list[tuple[str, float, int]] = field(default_factory=list)
    motivo: str = ""


def similitud_coseno(a: list[float], b: list[float]) -> float:
    """
    Similitud coseno entre dos vectores, implementada a mano.

    Un vector nulo no tiene dirección, así que el coseno no está definido: se
    devuelve 0.0 (sin parecido) en vez de dividir por cero.

    Raises:
        ValueError: si los vectores tienen dimensiones distintas.
    """
    if len(a) != len(b):
        raise ValueError(f"Dimensiones distintas: {len(a)} vs {len(b)}")

    norma_a = math.sqrt(sum(x * x for x in a))
    norma_b = math.sqrt(sum(y * y for y in b))
    if norma_a == 0.0 or norma_b == 0.0:
        return 0.0

    return sum(x * y for x, y in zip(a, b)) / (norma_a * norma_b)


def extraer_unidades(items: list[dict[str, str]], formato: FormatoSalida) -> list[str]:
    """
    Convierte los ítems generados en los textos que se comparan con la fuente.

    - Flashcards: SOLO la respuesta. La pregunta es una fórmula genérica
      ("¿Qué es una VCN?") que se parece a cualquier fragmento del tema y
      subiría el score de una respuesta inventada; la afirmación factual vive
      en la respuesta, que además el prompt pide autocontenida.
    - Guía práctica: "titulo. detalle". El título solo es muy corto y el
      detalle a veces lo referencia ("ese bloque"), así que juntos conservan
      el sentido; el título es accionable y aporta vocabulario del tema.

    Los ítems con el campo vacío o ausente se saltean (el orquestador ya los
    valida, pero acá no debe romper ante una forma inesperada).
    """
    unidades: list[str] = []
    for item in items:
        if formato == FormatoSalida.FLASHCARDS:
            texto = str(item.get("respuesta", "")).strip()
        elif formato == FormatoSalida.GUIA_PRACTICA:
            titulo = str(item.get("titulo", "")).strip()
            detalle = str(item.get("detalle", "")).strip()
            texto = f"{titulo}. {detalle}" if titulo and detalle else titulo or detalle
        else:
            return []
        if texto:
            unidades.append(texto)
    return unidades


def _a_chunks(textos: list[str]) -> list[Chunk]:
    """Envuelve textos sueltos en Chunk para reutilizar GeneradorDeEmbeddings tal cual."""
    return [Chunk(texto=t, indice=i, nombre_archivo=_ORIGEN_TEMPORAL) for i, t in enumerate(textos)]


class VerificadorDeFidelidad:
    """
    Mide qué tan anclado a la fuente está el contenido generado.

    ATENCIÓN: es anclaje TEMÁTICO, no verificación de veracidad. Detecta contenido
    fuera de tema (medido: 0.611-0.661) pero no datos inventados sobre el mismo
    tema (0.777-0.856, solapado con los fieles 0.805-0.900). El umbral por defecto
    (0.72) separa lo primero, no lo segundo.

    `generador_embeddings` es inyectable (los tests usan un modelo falso, sin red
    ni API key). Se usa `generar_embeddings` (embed_documents) para unidades y
    fragmentos por igual: ambos lados son "documentos", así la comparación es
    simétrica; `embed_query` está optimizado para búsquedas, no para esto.

    Los fragmentos se re-embeben en vez de reutilizar los vectores de Chroma:
    ResultadoBusqueda no los trae, y exponerlos obligaría a tocar VectorStore
    (include=embeddings) y el modelo de resultados para ahorrar una llamada batch
    por respuesta. No vale la pena acoplar las capas por eso; si el costo
    importara, el punto de extensión es agregar `vector` a ResultadoBusqueda.
    """

    def __init__(
        self,
        generador_embeddings: GeneradorDeEmbeddings | None = None,
        umbral: float | None = None,
    ):
        self._generador = generador_embeddings or GeneradorDeEmbeddings()
        self._umbral = umbral if umbral is not None else settings.umbral_anclaje

    def verificar(
        self,
        items: list[dict[str, str]],
        formato: FormatoSalida,
        fragmentos: list[ResultadoBusqueda],
    ) -> ResultadoFidelidad:
        """
        Calcula el score de anclaje: promedio, sobre las unidades, de su
        similitud máxima contra los fragmentos, acotado a [0, 1].

        No lanza ante casos que no se pueden medir (sin unidades, sin
        fragmentos, vectores inconsistentes): devuelve baja_confianza=True con
        el motivo, para no tumbar una respuesta ya generada.

        Raises:
            ErrorDeEmbeddings: si falla la API de embeddings. Sube tal cual: el
                backend decide si reintentar, degradar o responder sin verificar.
        """
        unidades = extraer_unidades(items, formato)

        if not unidades:
            return self._sin_medicion([], "No hay unidades de contenido para verificar")
        if not fragmentos:
            return self._sin_medicion(
                unidades, "No hay fragmentos de la fuente contra los cuales comparar"
            )

        # Una llamada batch por conjunto. ErrorDeEmbeddings se deja subir.
        vectores_unidades = [v for _, v in self._generador.generar_embeddings(_a_chunks(unidades))]
        vectores_fragmentos = [
            v for _, v in self._generador.generar_embeddings(_a_chunks([f.texto for f in fragmentos]))
        ]

        detalle: list[tuple[str, float, int]] = []
        try:
            for unidad, vector in zip(unidades, vectores_unidades):
                similitudes = [similitud_coseno(vector, vf) for vf in vectores_fragmentos]
                mejor = max(range(len(similitudes)), key=similitudes.__getitem__)
                detalle.append((unidad, similitudes[mejor], mejor))
        except ValueError as e:
            logger.warning("Vectores inconsistentes al verificar fidelidad: %s", e)
            return self._sin_medicion(unidades, f"Vectores de embeddings inconsistentes: {e}")

        promedio = sum(sim for _, sim, _ in detalle) / len(detalle)
        score = min(1.0, max(0.0, promedio))

        return ResultadoFidelidad(
            anclaje_fuente_score=score,
            baja_confianza=score < self._umbral,
            umbral=self._umbral,
            detalle=detalle,
        )

    def _sin_medicion(self, unidades: list[str], motivo: str) -> ResultadoFidelidad:
        """Resultado para cuando no se puede medir: sin evidencia de anclaje, baja confianza."""
        logger.warning("Fidelidad sin medir: %s", motivo)
        return ResultadoFidelidad(
            anclaje_fuente_score=0.0,
            baja_confianza=True,
            umbral=self._umbral,
            detalle=[(u, 0.0, -1) for u in unidades],
            motivo=motivo,
        )
