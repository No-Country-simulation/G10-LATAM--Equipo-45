"""
NM-06 — Esquemas Pydantic del API: entrada, salida de éxito y salida de error.

Los enums de perfil y formato NO se redefinen: se reexportan desde app/llm/prompts.py. Así hay una
única fuente de verdad y el contrato del endpoint no puede desincronizarse de los prompts (los
valores se envían tal cual, sin traducir: "Lider Tecnico / Arquitecto", "Guia Practica Paso a Paso").
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.config import settings
from app.llm.prompts import FormatoSalida, PerfilDestinatario

__all__ = [
    "PerfilDestinatario",
    "FormatoSalida",
    "SolicitudAdaptacion",
    "RespuestaAdaptacion",
    "ErrorRespuesta",
]

LARGO_MAXIMO_TITULO = 200
LARGO_MAXIMO_METADATO = 100  # nicho_sector y nivel_detalle


def _error_de_entrada(mensaje: str) -> PydanticCustomError:
    """
    Error de validación con mensaje ya redactado para el usuario.

    Se usa un tipo propio (en vez de ValueError) para que el manejador de errores pueda distinguir
    estos mensajes —escritos por nosotros, en español— de los de Pydantic o FastAPI, que vienen en inglés.
    """
    return PydanticCustomError("entrada_invalida", "{mensaje}", {"mensaje": mensaje})


# --------------------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------------------


class SolicitudAdaptacion(BaseModel):
    """
    Pedido de adaptación ya parseado del multipart/form-data.

    El archivo llega como `nombre_archivo` + `contenido_archivo` (bytes) y no como UploadFile: así el
    modelo es independiente de FastAPI y se puede validar y testear sin levantar el servidor.
    Regla central: exactamente uno entre archivo y `documento_contenido`.
    """

    perfil_destinatario: PerfilDestinatario
    formato_salida: FormatoSalida
    documento_titulo: str | None = Field(default=None, max_length=LARGO_MAXIMO_TITULO)
    documento_contenido: str | None = None
    nombre_archivo: str | None = None
    contenido_archivo: bytes | None = None
    # TODO(NM-06): nicho_sector y nivel_detalle se ACEPTAN y se devuelven en los metadatos, pero hoy
    # el orquestador NO los usa (los prompts no los incorporan). No cambian el contenido generado.
    nicho_sector: str | None = Field(default=None, max_length=LARGO_MAXIMO_METADATO)
    nivel_detalle: str | None = Field(default=None, max_length=LARGO_MAXIMO_METADATO)

    @field_validator("documento_titulo", "documento_contenido", "nicho_sector", "nivel_detalle", mode="before")
    @classmethod
    def _vacio_es_ausente(cls, valor):
        """Un campo de formulario en blanco llega como "": se trata como si no se hubiera enviado."""
        if isinstance(valor, str) and not valor.strip():
            return None
        return valor.strip() if isinstance(valor, str) else valor

    @field_validator("nombre_archivo")
    @classmethod
    def _extension_permitida(cls, nombre: str | None) -> str | None:
        if nombre is None:
            return None
        nombre = nombre.strip()
        extension = "." + nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
        permitidas = settings.extensiones_archivo
        if extension not in permitidas:
            raise _error_de_entrada(
                f"Formato de archivo no soportado ({extension or 'sin extensión'}). "
                f"Subí un archivo {', '.join(permitidas)}."
            )
        return nombre

    @field_validator("contenido_archivo")
    @classmethod
    def _archivo_no_vacio(cls, contenido: bytes | None) -> bytes | None:
        if contenido is not None and not contenido.strip():
            raise _error_de_entrada("El archivo está vacío.")
        return contenido

    @model_validator(mode="after")
    def _exactamente_uno(self) -> "SolicitudAdaptacion":
        hay_archivo = self.contenido_archivo is not None
        hay_texto = self.documento_contenido is not None
        if hay_archivo and hay_texto:
            raise _error_de_entrada("Enviá un archivo o un texto, no los dos a la vez.")
        if not hay_archivo and not hay_texto:
            raise _error_de_entrada("Falta el documento: subí un archivo o pegá el texto en 'documento_contenido'.")
        if hay_archivo and self.nombre_archivo is None:
            raise _error_de_entrada("El archivo no tiene nombre; no se puede saber su formato.")
        return self


# --------------------------------------------------------------------------------------
# Salida de éxito
# --------------------------------------------------------------------------------------


class Flashcard(BaseModel):
    pregunta: str
    respuesta: str


class PasoGuia(BaseModel):
    titulo: str
    detalle: str


class GuiaPractica(BaseModel):
    """Guía práctica: objeto con la clave `pasos`, como la pide el prompt (ver prompts.py)."""

    pasos: list[PasoGuia]


class Metadatos(BaseModel):
    documento_titulo: str
    perfil_destinatario: PerfilDestinatario
    formato_salida: FormatoSalida
    nombre_archivo: str | None = Field(description="Nombre del archivo subido; null si la entrada fue texto")
    fragmentos_usados: int
    nicho_sector: str | None = Field(default=None, description="Eco de la entrada; hoy no influye en el contenido")
    nivel_detalle: str | None = Field(default=None, description="Eco de la entrada; hoy no influye en el contenido")
    fecha_generacion: datetime = Field(description="UTC")
    modelo: str


class EvaluacionCalidad(BaseModel):
    anclaje_fuente_score: float | None = Field(
        description="Anclaje TEMÁTICO a la fuente (0-1), no veracidad; null si no se pudo verificar"
    )
    baja_confianza: bool
    umbral: float | None = None
    motivo: str | None = Field(default=None, description="Por qué no se pudo medir el anclaje, si aplica")
    # No implementada: se mantiene en el contrato para no romper al frontend cuando exista.
    claridad_pedagogica: None = None


class ResultadoAlmacenamiento(BaseModel):
    """
    Campos públicos de ResultadoSubida (app/oci/almacenamiento.py).

    `ruta_local` NO se expone: es una ruta del servidor y no debe salir por HTTP (solo va al log).
    """

    bucket: str
    objeto_id: str
    status_upload: Literal["exito", "pendiente_oci", "error"]


class AlmacenamientoOci(BaseModel):
    documento_original: ResultadoAlmacenamiento
    # null dentro del propio JSON subido (no puede contener su propio objeto_id); sí viaja en la respuesta.
    salida_json: ResultadoAlmacenamiento | None = None


class RespuestaAdaptacion(BaseModel):
    status: Literal["ok"] = "ok"
    metadatos: Metadatos
    # Flashcards: lista de {pregunta, respuesta}. Guía práctica: {"pasos": [...]}. Se distinguen por
    # forma (lista vs objeto), así que no hace falta un discriminador.
    contenido_adaptado: list[Flashcard] | GuiaPractica
    evaluacion_calidad: EvaluacionCalidad
    almacenamiento_oci: AlmacenamientoOci


# --------------------------------------------------------------------------------------
# Salida de error
# --------------------------------------------------------------------------------------


class DetalleError(BaseModel):
    campo: str
    problema: str


class ErrorRespuesta(BaseModel):
    status: Literal["error"] = "error"
    codigo: str
    mensaje: str
    detalles: list[DetalleError] | None = None
