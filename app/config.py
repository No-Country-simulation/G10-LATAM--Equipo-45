"""
Configuración central del proyecto NuevaMente.

Usa pydantic-settings para leer variables de entorno desde un archivo .env.
Todos los módulos deben importar `settings` desde acá en lugar de leer
os.environ directamente, para tener un único punto de verdad.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM / Embeddings (Google Gemini) ---
    google_api_key: str = Field(default="", description="API key de Google Gemini")
    gemini_model: str = Field(default="gemini-3.8-flash", description="Modelo de chat usado para orquestación")
    gemini_embedding_model: str = Field(
        default="models/gemini-embedding-001", description="Modelo de embeddings de Gemini (estable; embedding-001 fue dado de baja)"
    )

    gemini_timeout_s: float = Field(
        default=45.0,
        gt=0,
        description=(
            "Plazo (segundos) de CADA solicitud a Gemini (deadline gRPC). La librería hace como mucho 2 intentos "
            "(no es configurable), así que el peor caso es ~2x este valor + la espera entre intentos"
        ),
    )
    gemini_timeout_total_s: float = Field(
        default=100.0,
        gt=0,
        description="Tope de reloj (segundos) de toda la generación, reintentos de la librería incluidos",
    )
    embeddings_timeout_s: float = Field(
        default=60.0, gt=0, description="Tope de reloj (segundos) de cada llamada de embeddings a Gemini"
    )

    # --- RAG / Chunking ---
    chunk_size: int = Field(default=800, description=(
            "Tamaño base de cada chunk, en caracteres. Ojo: el chunk final puede medir hasta "
            "chunk_size + chunk_overlap, porque el overlap se antepone al fragmento."
        ),
    )
    chunk_overlap: int = Field(default=120, description="Solapamiento entre chunks consecutivos, en caracteres")
    top_k_recuperacion: int = Field(
        default=8, description="Cantidad de fragmentos que se recuperan del documento para armar el prompt"
    )

    # --- Verificación de fidelidad (NM-20) ---
    umbral_anclaje: float = Field(
        default=0.72,
        ge=0.0,
        le=1.0,
        description=(
            "Score de anclaje (similitud coseno promedio contenido/fuente) por debajo del cual la "
            "respuesta se marca como baja confianza. Calibrado con scripts/calibrar_fidelidad.py "
            "sobre 12 casos fijos y una fuente de 2 fragmentos (punto medio entre 'otro tema' <= 0.661 "
            "e 'inventados del mismo tema' >= 0.777); conviene revisarlo con documentos reales. "
            "Detecta contenido fuera de tema, no datos inventados sobre el mismo tema."
        ),
    )

    # --- Vector store ---
    # FAISS está descartado hasta que NM-02 lo confirme: hoy solo se acepta "chroma".
    vector_store_backend: Literal["chroma"] = Field(
        default="chroma", description="Backend de vector store a usar (decisión NM-02)"
    )
    vector_store_path: str = Field(default="./data/vector_store", description="Carpeta de persistencia local")
    vector_store_collection: str = Field(default="nuevamente_docs")

    # --- OCI Object Storage ---
    oci_bucket_name: str = Field(default="", description="Nombre del bucket de OCI Object Storage")
    oci_namespace: str = Field(default="", description="Namespace de OCI")
    oci_region: str = Field(default="", description="Región de OCI, ej. sa-saopaulo-1")
    oci_config_profile: str = Field(default="DEFAULT", description="Perfil del ~/.oci/config a usar")
    oci_connect_timeout_s: float = Field(default=5.0, gt=0, description="Timeout de conexión (s) del cliente de OCI")
    oci_read_timeout_s: float = Field(default=30.0, gt=0, description="Timeout de lectura (s) del cliente de OCI")
    almacenamiento_local_path: str = Field(
        default="./data/almacenamiento_local",
        description="Carpeta de fallback donde se guardan los archivos si OCI no está disponible (status pendiente_oci)",
    )

    # --- API (NM-18 / NM-19) ---
    max_upload_mb: int = Field(
        default=10, gt=0, description="Tamaño máximo, en MB, del archivo subido o del texto pegado (si lo supera: 413)"
    )
    extensiones_permitidas: str = Field(
        default=".pdf,.md,.txt",
        description="Extensiones de archivo aceptadas por el endpoint, separadas por coma",
    )

    # --- Backend ---
    app_env: Literal["dev", "test", "prod"] = Field(default="dev")
    log_level: str = Field(default="INFO")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def extensiones_archivo(self) -> tuple[str, ...]:
        """`extensiones_permitidas` normalizada: minúsculas, con punto inicial y sin vacíos."""
        extensiones = (e.strip().lower() for e in self.extensiones_permitidas.split(","))
        return tuple(e if e.startswith(".") else f".{e}" for e in extensiones if e)


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings (singleton de facto)."""
    return Settings()


settings = get_settings()
