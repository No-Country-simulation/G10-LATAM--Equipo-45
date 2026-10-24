"""Interfaz común entre chunking (NM-09) y embeddings (NM-10)."""

from dataclasses import dataclass, field


@dataclass
class Chunk:
    """Un fragmento de texto listo para ser embebido e indexado."""

    texto: str
    indice: int  # posición del chunk dentro del documento (0-based)
    nombre_archivo: str
    metadata: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        """ID determinístico y estable, usado como clave en el vector store."""
        return f"{self.nombre_archivo}::chunk_{self.indice}"
