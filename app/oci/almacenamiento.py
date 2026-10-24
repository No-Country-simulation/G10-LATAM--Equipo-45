"""
NM-12 / NM-22 — Almacenamiento de documentos originales y JSON generados en OCI Object Storage,
con fallback a disco local (diseño técnico, caso de uso 4).

Por qué existe el fallback: el bucket puede no estar listo, o la red/credenciales de una persona
pueden fallar, y eso no debe bloquear al resto del equipo ni tumbar el request. Si OCI no está
configurado o falla por una causa ESPERADA (ver ERRORES_ESPERADOS_DE_OCI: errores del servicio,
de configuración, de red o de archivo), el archivo se guarda en `almacenamiento_local_path` con el MISMO
`objeto_id` que habría tenido en el bucket, y se devuelve `status_upload="pendiente_oci"`. Así el
día que el bucket funcione alcanza con recorrer la carpeta y subir cada archivo con su nombre.

Solo esa lista acotada activa el fallback. Cualquier otra excepción (TypeError, AttributeError,
etc.) es un bug de programación y sube sin envolver: si se tragara, un error de código se vería
como un inocente "pendiente_oci" y nadie lo notaría.

Deuda anotada (fuera de alcance de NM-12/NM-22): falta el script de reconciliación que suba a
OCI lo que quedó como `pendiente_oci`. Hasta entonces esos archivos solo viven en el disco local.

Uso típico:
    almacenamiento = Almacenamiento()
    resultado = almacenamiento.subir_documento("manual.pdf", datos)
"""

import json
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

import oci
import requests

from app.config import settings

logger = logging.getLogger(__name__)

PREFIJO_DOCUMENTOS = "documentos/"
PREFIJO_SALIDAS = "salidas/"
NOMBRE_POR_DEFECTO = "archivo"
LARGO_MAXIMO_NOMBRE = 100

StatusUpload = Literal["exito", "pendiente_oci", "error"]


class ErrorDeAlmacenamiento(Exception):
    """No se pudo guardar el archivo ni en OCI ni en el disco local (o no se encontró al descargar)."""


class _OciNoDisponible(Exception):
    """OCI no está configurado (variables vacías, falta ~/.oci/config o perfil inválido)."""


# Causas esperadas que activan el fallback local; cualquier otra excepción es un bug y debe subir.
# Se listan una por una (verificadas contra el SDK instalado) en vez de usar `Exception`:
#  - oci.exceptions.ServiceError: OCI respondió con error (401 credenciales, 403 permisos, 404 bucket).
#  - oci.exceptions.ConfigFileNotFound / ProfileNotFound / InvalidConfig / InvalidKeyFilePath /
#    InvalidPrivateKey: ~/.oci/config ausente, perfil inexistente, config inválida, .pem inválido.
#  - oci.exceptions.RequestException y ConnectTimeout: fallos de red que el SDK ya envolvió
#    (ambas heredan de OSError a través de requests; se listan igual para dejar la intención explícita).
#  - ConnectionError, TimeoutError y OSError (builtins): red caída, timeouts del socket y archivos
#    (ej. el .pem no se encuentra o no se puede leer). Incluye requests.exceptions.RequestException.
#  - _OciNoDisponible: nuestra señal de variables OCI_* vacías.
ERRORES_ESPERADOS_DE_OCI: tuple[type[BaseException], ...] = (
    oci.exceptions.ServiceError,
    oci.exceptions.ConfigFileNotFound,
    oci.exceptions.ProfileNotFound,
    oci.exceptions.InvalidConfig,
    oci.exceptions.InvalidKeyFilePath,
    oci.exceptions.InvalidPrivateKey,
    oci.exceptions.RequestException,
    oci.exceptions.ConnectTimeout,
    requests.exceptions.Timeout,
    ConnectionError,
    TimeoutError,
    OSError,
    _OciNoDisponible,
)


class ClienteDeObjetos(Protocol):
    """Lo mínimo que usamos de `oci.object_storage.ObjectStorageClient`; permite inyectar un fake."""

    def put_object(
        self, namespace_name: str, bucket_name: str, object_name: str, put_object_body: Any, **kwargs: Any
    ) -> Any: ...

    def get_object(self, namespace_name: str, bucket_name: str, object_name: str, **kwargs: Any) -> Any: ...


@dataclass
class ResultadoSubida:
    """Mismos campos que `almacenamiento_oci` del contrato de salida, más la ruta local si hubo fallback."""

    bucket: str
    objeto_id: str
    status_upload: StatusUpload
    ruta_local: str | None = None


def _crear_cliente_oci() -> ClienteDeObjetos:
    """
    Crea el cliente real de OCI, en el primer uso (lazy: importar el módulo no exige credenciales).

    Igual que scripts/smoke_oci.py: la región del .env manda sobre la del perfil, pero solo en
    memoria; no se toca el ~/.oci/config.
    """
    if not settings.oci_region:
        raise _OciNoDisponible("OCI_REGION está vacía")

    ruta = Path(oci.config.DEFAULT_LOCATION).expanduser()
    if not ruta.is_file():
        raise _OciNoDisponible(f"no existe {ruta}")

    # Los errores del SDK (perfil inexistente, config o clave inválidas) se dejan subir: están en
    # ERRORES_ESPERADOS_DE_OCI y los atrapa quien llama.
    config = oci.config.from_file(file_location=str(ruta), profile_name=settings.oci_config_profile)
    config["region"] = settings.oci_region
    oci.config.validate_config(config)

    # Timeouts explícitos (conexión, lectura): el SDK no aplica reintentos por defecto, así que una
    # llamada colgada vence a los `oci_connect_timeout_s + oci_read_timeout_s` como mucho. El error que
    # sale (requests Timeout / oci ConnectTimeout) está en ERRORES_ESPERADOS_DE_OCI y activa el fallback local.
    return oci.object_storage.ObjectStorageClient(
        config, timeout=(settings.oci_connect_timeout_s, settings.oci_read_timeout_s)
    )


def sanitizar_nombre(nombre: str) -> str:
    """
    Deja solo un nombre de archivo seguro: sin directorios, sin "..", sin caracteres raros.

    Importa en dos lugares: el nombre llega del usuario y termina como clave en OCI y como ruta en
    disco, donde un "../../etc/x" escribiría fuera de la carpeta prevista (path traversal).
    """
    # Se queda con lo que está después de la última barra, sea "/" o "\" (rutas absolutas o de Windows).
    base = re.split(r"[/\\]", nombre)[-1]
    # NFKD + descartar marcas combinantes: "guía" -> "guia", para claves ASCII predecibles.
    base = unicodedata.normalize("NFKD", base)
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    # Sin puntos al principio (archivos ocultos) y sin ".." en ningún lado.
    base = re.sub(r"\.{2,}", ".", base).lstrip(".")
    base = re.sub(r"_+\.", ".", base)  # "v2_.pdf" -> "v2.pdf"
    base = base.strip("_")[:LARGO_MAXIMO_NOMBRE]
    return base or NOMBRE_POR_DEFECTO


def _validar_objeto_id(objeto_id: str) -> None:
    """Rechaza ids absolutos o con ".." antes de usarlos como ruta en disco."""
    partes = PurePosixPath(objeto_id).parts
    if not objeto_id or objeto_id.startswith(("/", "\\")) or ".." in partes or "\\" in objeto_id:
        raise ErrorDeAlmacenamiento(f"objeto_id inválido: {objeto_id!r}")


def _describir_causa(error: Exception) -> str:
    """Resumen de la causa para el log. Solo tipo/status/código: nunca config ni credenciales."""
    status = getattr(error, "status", None)
    if status is not None:
        return f"{type(error).__name__} {status} ({getattr(error, 'code', '?')})"
    return f"{type(error).__name__}: {error}"


class Almacenamiento:
    """
    Sube documentos y JSON a OCI, con fallback a disco local.

    Acepta un `cliente` inyectado (un fake en tests) y una `carpeta_local`. Si no se pasa cliente,
    el real se crea en el primer uso. `reloj` también es inyectable para tener nombres de objeto
    determinísticos en tests.
    """

    def __init__(
        self,
        cliente: ClienteDeObjetos | None = None,
        carpeta_local: str | Path | None = None,
        bucket: str | None = None,
        namespace: str | None = None,
        reloj: Callable[[], datetime] | None = None,
    ):
        self._cliente = cliente
        self._carpeta_local = Path(carpeta_local if carpeta_local is not None else settings.almacenamiento_local_path)
        self._bucket = settings.oci_bucket_name if bucket is None else bucket
        self._namespace = settings.oci_namespace if namespace is None else namespace
        self._reloj = reloj or (lambda: datetime.now(timezone.utc))

    # --- API pública ---

    def subir_documento(
        self, nombre_archivo: str, datos: bytes, content_type: str | None = None
    ) -> ResultadoSubida:
        """Sube el documento original a `documentos/<timestamp UTC>-<nombre sanitizado>` (NM-12)."""
        return self._subir(PREFIJO_DOCUMENTOS, nombre_archivo, datos, content_type)

    def subir_json(self, nombre_objeto: str, contenido: dict | str) -> ResultadoSubida:
        """Sube el JSON generado a `salidas/<timestamp UTC>-<nombre sanitizado>` (NM-22)."""
        if isinstance(contenido, dict):
            texto = json.dumps(contenido, ensure_ascii=False, indent=2)
        else:
            texto = contenido
        nombre = sanitizar_nombre(nombre_objeto)
        if not nombre.lower().endswith(".json"):
            nombre += ".json"
        return self._subir(PREFIJO_SALIDAS, nombre, texto.encode("utf-8"), "application/json; charset=utf-8")

    def descargar(self, objeto_id: str) -> bytes:
        """
        Devuelve el contenido del objeto. Intenta OCI y, si no se puede, la copia local: un archivo
        con `pendiente_oci` solo existe en disco.

        Raises:
            ErrorDeAlmacenamiento: si el id es inválido o el objeto no está ni en OCI ni en disco.
        """
        _validar_objeto_id(objeto_id)
        causa: Exception | None = None
        try:
            respuesta = self._obtener_cliente().get_object(self._namespace, self._bucket, objeto_id)
            return respuesta.data.content
        except ERRORES_ESPERADOS_DE_OCI as e:
            causa = e
            logger.warning("No se pudo descargar %s de OCI (%s); se busca en disco local", objeto_id, _describir_causa(e))

        ruta = self._ruta_local(objeto_id)
        try:
            return ruta.read_bytes()
        except OSError as e:
            raise ErrorDeAlmacenamiento(
                f"No se encontró {objeto_id} en OCI ({_describir_causa(causa)}) ni en disco local"
            ) from e

    # --- Internos ---

    def _subir(self, prefijo: str, nombre: str, datos: bytes, content_type: str | None) -> ResultadoSubida:
        marca = self._reloj().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        objeto_id = f"{prefijo}{marca}-{sanitizar_nombre(nombre)}"

        try:
            if not self._bucket or not self._namespace:
                raise _OciNoDisponible("OCI_BUCKET_NAME u OCI_NAMESPACE están vacías")
            cliente = self._obtener_cliente()
            kwargs = {"content_type": content_type} if content_type else {}
            cliente.put_object(self._namespace, self._bucket, objeto_id, datos, **kwargs)
        except ERRORES_ESPERADOS_DE_OCI as e:
            logger.warning("Subida a OCI fallida para %s (%s); se guarda en disco local", objeto_id, _describir_causa(e))
            return self._guardar_local(objeto_id, datos, causa=e)

        return ResultadoSubida(bucket=self._bucket, objeto_id=objeto_id, status_upload="exito")

    def _obtener_cliente(self) -> ClienteDeObjetos:
        if self._cliente is None:
            self._cliente = _crear_cliente_oci()
        return self._cliente

    def _ruta_local(self, objeto_id: str) -> Path:
        """Ruta en disco del objeto, verificando que no se salga de la carpeta local (defensa en profundidad)."""
        raiz = self._carpeta_local.resolve()
        ruta = (raiz / objeto_id).resolve()
        if not ruta.is_relative_to(raiz):
            raise ErrorDeAlmacenamiento(f"objeto_id fuera de la carpeta local: {objeto_id!r}")
        return ruta

    def _guardar_local(self, objeto_id: str, datos: bytes, causa: Exception) -> ResultadoSubida:
        try:
            ruta = self._ruta_local(objeto_id)
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(datos)
        except OSError as e:
            raise ErrorDeAlmacenamiento(
                f"Falló OCI ({_describir_causa(causa)}) y también el guardado local de {objeto_id}: {e}"
            ) from e

        return ResultadoSubida(
            bucket=self._bucket, objeto_id=objeto_id, status_upload="pendiente_oci", ruta_local=str(ruta)
        )
