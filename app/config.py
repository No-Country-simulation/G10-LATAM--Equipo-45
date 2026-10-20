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

    # --- Backend ---
    app_env: Literal["dev", "test", "prod"] = Field(default="dev")
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de Settings (singleton de facto)."""
    return Settings()


settings = get_settings()
