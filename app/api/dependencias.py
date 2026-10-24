"""
NM-18 — Construcción de las dependencias reales del API.

Todo es diferido (lazy) y cacheado: importar `app.api.main` no abre el vector store, no crea clientes
de Gemini ni de OCI, así que la app arranca (y los tests corren) sin claves ni red. El primer pedido
real arma el grafo de objetos una sola vez. Los tests lo reemplazan con
`app.dependency_overrides[obtener_servicio] = lambda: servicio_falso`.
"""

import logging
import threading

from app.api.servicio import ServicioDeAdaptacion
from app.llm.fidelidad import VerificadorDeFidelidad
from app.llm.gemini_client import ClienteGemini
from app.llm.orquestador import Orquestador
from app.oci.almacenamiento import Almacenamiento
from app.rag.vector_store import VectorStore
from app.trazas import paso

logger = logging.getLogger(__name__)

_servicio: ServicioDeAdaptacion | None = None
_candado = threading.Lock()


def obtener_servicio() -> ServicioDeAdaptacion:
    """
    Devuelve el servicio compartido por todas las solicitudes.

    El candado evita que dos solicitudes simultáneas en el primer arranque (los endpoints sync corren
    en un pool de hilos) construyan dos veces el vector store.
    """
    global _servicio
    if _servicio is None:
        with _candado:
            if _servicio is None:
                with paso(logger, "inicializar_dependencias"):
                    vector_store = VectorStore()
                    _servicio = ServicioDeAdaptacion(
                        orquestador=Orquestador(vector_store, ClienteGemini()),
                        verificador=VerificadorDeFidelidad(),
                        almacenamiento=Almacenamiento(),
                        vector_store=vector_store,
                    )
    return _servicio
