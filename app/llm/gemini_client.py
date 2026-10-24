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
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from google.api_core import exceptions as gexc

from app.config import settings
from app.trazas import TiempoAgotado, ejecutar_con_limite

logger = logging.getLogger(__name__)

# Temperatura baja: la salida tiene que ser JSON estable y anclado al documento fuente,
# no creativo. Con valores altos sube la chance de JSON roto o de datos inventados.
TEMPERATURA = 0.2


# Margen del tope de reloj de cada intento sobre el plazo de la solicitud (`gemini_timeout_s`): deja que el
# deadline del cliente venza primero y devuelva su propio error; el tope de reloj solo corta lo que no respeta plazos.
GRACIA_S = 5.0

# Errores que justifican probar OTRO modelo (el problema es del modelo o de su disponibilidad):
# 503 alta demanda, 504/deadline, 429 cuota, 404 modelo no disponible, y nuestro tope por llamada.
_PASAN_AL_SIGUIENTE: tuple[type[BaseException], ...] = (
    gexc.ServiceUnavailable,
    gexc.GatewayTimeout,  # DeadlineExceeded hereda de esta
    gexc.TooManyRequests,  # ResourceExhausted hereda de esta
    gexc.NotFound,
    TiempoAgotado,
)
# Errores de credenciales o de pedido: otro modelo fallaría igual.
_NUNCA_PASAN: tuple[type[BaseException], ...] = (gexc.InvalidArgument, gexc.PermissionDenied, gexc.Unauthenticated)


def _causas(error: BaseException):
    """El error y sus causas encadenadas (LangChain a veces envuelve el error de Google)."""
    visto = 0
    while error is not None and visto < 5:
        yield error
        error = error.__cause__ or error.__context__
        visto += 1


def _motivo_de_cambio(error: BaseException) -> str | None:
    """Tipo del error si corresponde pasar al siguiente modelo; None si debe propagarse."""
    causas = list(_causas(error))
    if any(isinstance(c, _NUNCA_PASAN) for c in causas):
        return None
    for c in causas:
        if isinstance(c, _PASAN_AL_SIGUIENTE):
            return type(c).__name__
    return None


@dataclass
class ResultadoGeneracion:
    """Texto generado, modelo que realmente respondió (None si el cliente es un fake sin nombre) e intentos."""

    texto: str
    modelo: str | None
    intentos: int


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

    def __init__(self, chat, timeout: float | None = None):
        self._chat = chat
        self._timeout = timeout

    def invocar(self, prompt_sistema: str, prompt_usuario: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        # Reintentos y plazos (verificado en langchain-google-genai 2.0.6):
        #  - El `timeout`/`max_retries` del constructor de ChatGoogleGenerativeAI se IGNORAN en el camino
        #    síncrono (solo los usa el LLM de texto). Por eso el plazo se pasa por llamada: los kwargs de
        #    `invoke` llegan hasta `client.generate_content`.
        #  - `retry=None` desactiva el reintento por defecto del cliente gRPC (ante 503, hasta 600 s).
        #  - Queda el reintento de la librería (tenacity: 2 intentos, espera 1-60 s, sobre cualquier
        #    GoogleAPIError, 429 incluido). No es configurable; `gemini_timeout_total_s` acota el conjunto.
        opciones = {"timeout": self._timeout, "retry": None} if self._timeout else {}
        respuesta = self._chat.invoke(
            [SystemMessage(content=prompt_sistema), HumanMessage(content=prompt_usuario)], **opciones
        )
        contenido = respuesta.content
        if isinstance(contenido, str):
            return contenido
        # Algunos modelos devuelven una lista de partes (str o {"type": "text", "text": ...}).
        return "".join(
            parte if isinstance(parte, str) else parte.get("text", "") for parte in contenido
        )


def _crear_modelo_gemini(nombre: str | None = None) -> ModeloDeChat:
    """Crea el cliente real de Gemini para un modelo. Falla rápido y claro si falta la API key."""
    if not settings.google_api_key:
        raise ErrorDeLLM(
            "GOOGLE_API_KEY no está configurada. Completá el archivo .env "
            "(ver .env.example) antes de llamar a Gemini."
        )

    from langchain_google_genai import ChatGoogleGenerativeAI

    return _ModeloLangChain(
        ChatGoogleGenerativeAI(
            model=nombre or settings.gemini_model,
            google_api_key=settings.google_api_key,
            temperature=TEMPERATURA,
        ),
        timeout=settings.gemini_timeout_s,
    )


class ClienteGemini:
    """
    Cliente de chat de Gemini con cadena de modelos de respaldo.

    La cadena es `[GEMINI_MODEL] + GEMINI_MODEL_FALLBACKS`. Cada modelo se prueba con los timeouts ya
    existentes; ante 503/504/429/404 o timeout propio se pasa al siguiente (con `gemini_backoff_s` de
    espera, salvo tras un 404). Credenciales inválidas, errores de pedido y bugs propios se propagan sin
    probar otro modelo. Todo el conjunto respeta `gemini_timeout_total_s`.

    Para tests: `modelo` inyecta un único fake (cadena de un elemento, sin nombre salvo `nombre_modelo`);
    `cadena` + `fabrica` (nombre -> fake) simulan varios modelos; `dormir` reemplaza time.sleep.
    Sin nada inyectado, los modelos reales se crean en el primer uso (lazy), así importar este módulo
    no requiere la API key.
    """

    def __init__(
        self,
        modelo: ModeloDeChat | None = None,
        nombre_modelo: str | None = None,
        cadena: tuple[str, ...] | list[str] | None = None,
        fabrica: Callable[[str], ModeloDeChat] | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._modelos: dict[str | None, ModeloDeChat] = {}
        if modelo is not None:
            self._cadena: tuple[str | None, ...] = (nombre_modelo,)
            self._modelos[nombre_modelo] = modelo
        else:
            self._cadena = tuple(cadena) if cadena else settings.gemini_cadena_modelos
        self._fabrica = fabrica or _crear_modelo_gemini
        self._dormir = dormir

    def _obtener(self, nombre: str | None) -> ModeloDeChat:
        if nombre not in self._modelos:
            self._modelos[nombre] = self._fabrica(nombre)
        return self._modelos[nombre]

    @property
    def modelo(self) -> ModeloDeChat:
        """Modelo principal (el primero de la cadena)."""
        return self._obtener(self._cadena[0])

    def generar(self, prompt_sistema: str, prompt_usuario: str) -> str:
        """Como `generar_con_detalle`, devolviendo solo el texto."""
        return self.generar_con_detalle(prompt_sistema, prompt_usuario).texto

    def generar_con_detalle(
        self, prompt_sistema: str, prompt_usuario: str, empezar_en: str | None = None
    ) -> ResultadoGeneracion:
        """
        Envía los prompts a la cadena de modelos y devuelve el texto, el modelo que respondió y los intentos.

        `empezar_en` salta los modelos anteriores de la cadena (el reintento por JSON inválido sigue con
        el modelo que ya respondió en vez de volver a probar uno que había fallado).

        Raises:
            ErrorDeLLM: falta la API key, error no recuperable con otro modelo (credenciales, pedido, bug),
                respuesta vacía, presupuesto `gemini_timeout_total_s` agotado, o todos los modelos
                fallaron (el mensaje lista cada modelo y el tipo de su error, sin claves).
        """
        cadena = self._cadena
        if empezar_en in cadena:
            cadena = cadena[cadena.index(empezar_en):]
        inicio = time.monotonic()
        presupuesto = settings.gemini_timeout_total_s
        fallos: list[tuple[str | None, str]] = []

        for i, nombre in enumerate(cadena):
            restante = presupuesto - (time.monotonic() - inicio)
            if restante <= 0:
                break
            modelo = self._obtener(nombre)  # ErrorDeLLM (sin API key) sube tal cual
            try:
                texto = ejecutar_con_limite(
                    lambda: modelo.invocar(prompt_sistema, prompt_usuario),
                    min(restante, settings.gemini_timeout_s + GRACIA_S),
                    f"Gemini {nombre or ''}".strip(),
                )
            except ErrorDeLLM:
                raise
            except Exception as e:  # noqa: BLE001 — se clasifica: cambiar de modelo o normalizar y propagar
                motivo = _motivo_de_cambio(e)
                if motivo is None:
                    raise ErrorDeLLM(f"Fallo al llamar a Gemini: {e}") from e
                fallos.append((nombre, motivo))
                siguiente = cadena[i + 1] if i + 1 < len(cadena) else None
                logger.warning(
                    "paso=generacion modelo=%s intento=%d fallo=%s pasando_a=%s",
                    nombre or "configurado", i + 1, motivo, siguiente or "ninguno",
                )
                if siguiente is not None and motivo != "NotFound" and settings.gemini_backoff_s > 0:
                    espera = settings.gemini_backoff_s
                    self._dormir(min(espera, max(0.0, presupuesto - (time.monotonic() - inicio))))
                continue

            if not isinstance(texto, str) or not texto.strip():
                raise ErrorDeLLM("Gemini devolvió una respuesta vacía")
            logger.info("paso=generacion modelo_usado=%s intentos=%d", nombre or "configurado", i + 1)
            return ResultadoGeneracion(texto=texto, modelo=nombre, intentos=i + 1)

        detalle = ", ".join(f"{n or 'configurado'} ({m})" for n, m in fallos) or "ninguno"
        if time.monotonic() - inicio >= presupuesto:
            raise ErrorDeLLM(
                f"Gemini no respondió a tiempo: se agotó el presupuesto de {presupuesto:g}s. Intentos: {detalle}"
            )
        raise ErrorDeLLM(f"Gemini no respondió con ninguno de los modelos. Intentos: {detalle}")
