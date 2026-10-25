"""
Validación del contenido de un documento ya ingerido, ANTES de subirlo a OCI y de llamar al LLM.

Un texto sin contenido útil (solo símbolos, o de unas pocas palabras) no puede dar una adaptación
confiable: el LLM responde basura o nada, y reintentar con el mismo documento no cambia el resultado.
Por eso se rechaza en la entrada, con un mensaje accionable.

Reglas, en este orden (el texto se normaliza antes: se colapsan los espacios en blanco):
    1. Proporción de letras sobre los caracteres no blancos por debajo de PROPORCION_MINIMA_LETRAS -> sin contenido útil.
    2. Menos de MIN_LETRAS letras (o de `min_chars_documento`, si es menor)                         -> sin contenido útil.
    3. Menos de `min_chars_documento` caracteres (MIN_CHARS_DOCUMENTO)                              -> demasiado corto.
La 2 va antes que la 3: "asdnasdndneedc ad@####" y "Hola, esto es una prueba" (menos de 50 letras) no son un
documento a adaptar, y "demasiado corto" queda para textos reales con 50 letras o más pero menos de MIN_CHARS.
"""

import re
from dataclasses import dataclass

# Letras / caracteres no blancos. El texto técnico con código, rutas y números ronda 0.6-0.8 (los materiales
# de prueba, 0.77-0.82); un texto de puros símbolos queda cerca de 0. 0.4 deja margen para tablas y listados.
PROPORCION_MINIMA_LETRAS = 0.4
# Letras mínimas (unas dos oraciones). Si MIN_CHARS_DOCUMENTO es menor, manda ese valor: bajarlo apaga esta regla.
MIN_LETRAS = 50

CODIGO_SIN_CONTENIDO = "documento_sin_contenido_util"
CODIGO_MUY_CORTO = "documento_muy_corto"
MENSAJE_SIN_CONTENIDO = (
    "El documento no contiene texto suficiente para adaptar. Subí un material con al menos algunos párrafos."
)
MENSAJE_MUY_CORTO = (
    "El documento es demasiado corto para adaptarlo (mínimo {minimo} caracteres). "
    "Subí un material con al menos algunos párrafos."
)

_ESPACIOS = re.compile(r"\s+")


@dataclass(frozen=True)
class ProblemaDeContenido:
    codigo: str
    mensaje: str


def normalizar(texto: str) -> str:
    return _ESPACIOS.sub(" ", texto).strip()


def evaluar_contenido(texto: str, min_chars: int) -> ProblemaDeContenido | None:
    """None si el texto es apto; si no, el problema (código + mensaje para el usuario). El vacío total no se juzga acá."""
    normal = normalizar(texto)
    if not normal:
        return None  # lo maneja el flujo existente de "documento sin texto" (ej. PDF escaneado)
    letras = sum(c.isalpha() for c in normal)
    no_blancos = len(normal) - normal.count(" ")
    sin_contenido = ProblemaDeContenido(CODIGO_SIN_CONTENIDO, MENSAJE_SIN_CONTENIDO)
    if letras / no_blancos < PROPORCION_MINIMA_LETRAS:
        return sin_contenido
    if letras < min(MIN_LETRAS, min_chars):
        return sin_contenido
    if len(normal) < min_chars:
        return ProblemaDeContenido(CODIGO_MUY_CORTO, MENSAJE_MUY_CORTO.format(minimo=min_chars))
    return None
