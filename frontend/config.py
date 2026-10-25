"""
Configuración del frontend. Lee las mismas fuentes que el backend (variables de entorno y el .env de la raíz),
así un único .env sirve para los dos procesos. Streamlit no carga el .env por su cuenta.

MAX_UPLOAD_MB y EXTENSIONES_PERMITIDAS se llaman igual que en el backend a propósito: si se cambian en el
.env, la validación previa de la UI queda alineada con la del servidor.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parent.parent


class ConfigFrontend(BaseSettings):
    model_config = SettingsConfigDict(env_file=RAIZ / ".env", env_file_encoding="utf-8", extra="ignore")

    api_base_url: str = Field(default="http://127.0.0.1:8000", description="URL base de la API de NuevaMente")
    api_timeout_s: float = Field(
        default=150.0,
        gt=0,
        description="Plazo (s) de la solicitud a la API. Debe superar el peor caso del backend (~100 s)",
    )
    app_timezone: str = Field(
        default="America/Asuncion", description="Zona horaria IANA para mostrar la fecha de generación"
    )
    max_upload_mb: int = Field(default=10, gt=0)
    extensiones_permitidas: str = Field(default=".pdf,.md,.txt")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def extensiones_archivo(self) -> tuple[str, ...]:
        extensiones = (e.strip().lower() for e in self.extensiones_permitidas.split(","))
        return tuple(e if e.startswith(".") else f".{e}" for e in extensiones if e)


def cargar_config() -> ConfigFrontend:
    return ConfigFrontend()
