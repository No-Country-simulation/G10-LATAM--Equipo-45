"""
Configuración de logging de la aplicación.

Uvicorn solo configura sus propios loggers: sin esto, los `logger.info` de "app" no se ven. Se instala un
handler a stdout en el logger "app" (y en la librería de Gemini, cuyos reintentos se loguean como WARNING).
Es idempotente: llamarlo dos veces (ej. con --reload) no duplica líneas.
"""

import logging
import sys

from app.config import settings

FORMATO = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MARCA = "_nuevamente_handler"
_LOGGERS_DE_LIBRERIAS = ("langchain_google_genai",)


def configurar_logging(nivel: str | None = None) -> None:
    valor = getattr(logging, (nivel or settings.log_level).strip().upper(), None)
    nivel_num = valor if isinstance(valor, int) else logging.INFO

    handler = None
    app_logger = logging.getLogger("app")
    for h in app_logger.handlers:
        if getattr(h, _MARCA, False):
            handler = h
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(FORMATO))
        setattr(handler, _MARCA, True)
        app_logger.addHandler(handler)
    app_logger.setLevel(nivel_num)

    for nombre in _LOGGERS_DE_LIBRERIAS:
        lib = logging.getLogger(nombre)
        if handler not in lib.handlers:
            lib.addHandler(handler)
        lib.setLevel(max(nivel_num, logging.WARNING))
