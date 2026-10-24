"""
Trazas por paso y topes de tiempo.

`paso` registra inicio, fin y duración de cada etapa del pipeline, y si falla, el tipo de la excepción.
Nunca se registra el mensaje de la excepción ni datos del documento: pueden traer contenido, rutas o claves.

`ejecutar_con_limite` corta la ESPERA de una llamada bloqueante que no respeta sus propios timeouts.
Python no puede matar un hilo: si la llamada se cuelga, el hilo (daemon) sigue vivo hasta que el SDK
termine, pero quien llamó recibe `TiempoAgotado` y puede responder.
"""

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

T = TypeVar("T")


class TiempoAgotado(TimeoutError):
    """Una llamada externa superó su tope de tiempo."""


@contextmanager
def paso(logger: logging.Logger, nombre: str) -> Iterator[None]:
    logger.info("paso=%s inicio", nombre)
    inicio = time.perf_counter()
    try:
        yield
    except BaseException as e:
        logger.error("paso=%s FALLÓ duracion=%.2fs error=%s", nombre, time.perf_counter() - inicio, type(e).__name__)
        raise
    logger.info("paso=%s ok duracion=%.2fs", nombre, time.perf_counter() - inicio)


def ejecutar_con_limite(funcion: Callable[[], T], segundos: float, descripcion: str) -> T:
    """Ejecuta `funcion()` en un hilo daemon y espera como máximo `segundos`; si no termina, `TiempoAgotado`."""
    resultado: list[T] = []
    error: list[BaseException] = []

    def _correr() -> None:
        try:
            resultado.append(funcion())
        except BaseException as e:  # noqa: BLE001 — se re-lanza en el hilo que espera
            error.append(e)

    hilo = threading.Thread(target=_correr, name=f"limite-{descripcion}", daemon=True)
    hilo.start()
    hilo.join(segundos)
    if hilo.is_alive():
        raise TiempoAgotado(f"{descripcion} superó el tope de {segundos:g}s")
    if error:
        raise error[0]
    return resultado[0]
