"""
NM-11 — Vector store + búsqueda semántica.

Abstracción sobre ChromaDB (backend por defecto hasta que NM-02 confirme
la decisión final de stack — Larissa). Si el equipo decide pasar a FAISS,
solo este archivo debería cambiar: el resto del pipeline usa la interfaz
`VectorStore.agregar_chunks` / `VectorStore.buscar`.

ChromaDB se eligió sobre FAISS para el MVP porque persiste a disco con
cero configuración adicional (FAISS requeriría serializar el índice a
mano) y permite guardar metadata junto a cada vector, que vamos a
necesitar para mostrar de qué documento/chunk salió cada resultado.
"""

import logging

import chromadb

from app.rag.embeddings import GeneradorDeEmbeddings
from app.rag.models import Chunk
from app.config import settings

logger = logging.getLogger(__name__)


class ErrorDeVectorStore(Exception):
    """Error al escribir o consultar el vector store."""


class ResultadoBusqueda:
    """Un resultado de búsqueda semántica: el chunk recuperado y su score de similitud."""

    def __init__(self, texto: str, nombre_archivo: str, metadata: dict, score: float):
        self.texto = texto
        self.nombre_archivo = nombre_archivo
        self.metadata = metadata
        self.score = score

    def __repr__(self) -> str:  # pragma: no cover
        return f"ResultadoBusqueda(archivo={self.nombre_archivo!r}, score={self.score:.3f})"


class VectorStore:
    """
    Wrapper sobre una colección de ChromaDB.

    Uso:
        store = VectorStore()
        store.agregar_chunks(chunks)                 # genera embeddings e indexa
        resultados = store.buscar("¿qué es una VCN?", top_k=5)
    """

    def __init__(
        self,
        generador_embeddings: GeneradorDeEmbeddings | None = None,
        path: str | None = None,
        nombre_coleccion: str | None = None,
        cliente: "chromadb.ClientAPI | None" = None,
    ):
        self._generador = generador_embeddings or GeneradorDeEmbeddings()
        path = path or settings.vector_store_path
        nombre_coleccion = nombre_coleccion or settings.vector_store_collection

        self._cliente = cliente or chromadb.PersistentClient(path=path)
        # Métrica coseno: sin esto Chroma usa L2 al cuadrado, cuya distancia puede
        # ser > 1 y haría que `score = 1 - distancia` diera valores negativos.
        # Ojo: solo aplica al CREAR la colección; una ya existente conserva su métrica.
        self._coleccion = self._cliente.get_or_create_collection(
            name=nombre_coleccion, metadata={"hnsw:space": "cosine"}
        )

    def agregar_chunks(self, chunks: list[Chunk]) -> int:
        """
        Genera embeddings para los chunks dados y los agrega a la colección.

        Returns:
            Cantidad de chunks agregados (0 si la lista de entrada está vacía).
        """
        if not chunks:
            return 0

        pares = self._generador.generar_embeddings(chunks)

        try:
            self._coleccion.upsert(
                ids=[chunk.id for chunk, _ in pares],
                embeddings=[vector for _, vector in pares],
                documents=[chunk.texto for chunk, _ in pares],
                metadatas=[
                    {"nombre_archivo": chunk.nombre_archivo, **chunk.metadata}
                    for chunk, _ in pares
                ],
            )
        except Exception as e:  # noqa: BLE001
            raise ErrorDeVectorStore(f"Fallo al indexar chunks en Chroma: {e}") from e

        return len(pares)

    def buscar(self, query: str, top_k: int = 5) -> list[ResultadoBusqueda]:
        """
        Busca los `top_k` chunks más semánticamente similares a `query`.

        Returns:
            Lista de ResultadoBusqueda ordenada de mayor a menor similitud.
            Lista vacía si la colección está vacía.
        """
        if top_k <= 0:
            raise ValueError("top_k debe ser mayor a 0")

        if self._coleccion.count() == 0:
            return []

        embedding_query = self._generador.generar_embedding_query(query)

        try:
            resultado = self._coleccion.query(
                query_embeddings=[embedding_query],
                n_results=min(top_k, self._coleccion.count()),
            )
        except Exception as e:  # noqa: BLE001
            raise ErrorDeVectorStore(f"Fallo al consultar Chroma: {e}") from e

        documentos = resultado["documents"][0]
        metadatas = resultado["metadatas"][0]
        distancias = resultado["distances"][0]

        return [
            ResultadoBusqueda(
                texto=doc,
                nombre_archivo=meta.get("nombre_archivo", "desconocido"),
                metadata=meta,
                # Chroma devuelve distancia (menor = más similar); lo invertimos
                # a un score de similitud (mayor = mejor) para que sea intuitivo.
                score=1.0 - distancia,
            )
            for doc, meta, distancia in zip(documentos, metadatas, distancias)
        ]

    def cantidad_indexada(self) -> int:
        return self._coleccion.count()
