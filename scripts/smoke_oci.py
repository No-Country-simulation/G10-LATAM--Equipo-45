"""
Smoke test MANUAL contra OCI Object Storage real. No es parte de pytest.

Verifica en orden, con las credenciales de ~/.oci/config y las variables OCI_* del .env:
  (a) configuración: variables del .env, existencia de ~/.oci/config y oci.config.validate_config,
  (b) subida de un objeto de texto chico (smoke/<timestamp>.txt),
  (c) descarga del objeto y comparación del contenido,
  (d) listado de los objetos con prefijo smoke/,
  (e) borrado del objeto de prueba.

Uso (desde cualquier carpeta):
    python scripts/smoke_oci.py

Escribe y borra un único objeto diminuto, así que cabe de sobra en la capa Always Free.
Si falla un paso intermedio igual se intenta el borrado, para no dejar basura en el bucket.
Sale con código 0 si todo anduvo, 1 si algún paso falló y 2 si falta configuración.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Corre desde la raíz del repo: así `import app` funciona y pydantic-settings encuentra el .env.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

import oci  # noqa: E402

from app.config import settings  # noqa: E402

PREFIJO = "smoke/"


def _p(texto: str = "") -> None:
    # flush=True: si la salida se redirige o se pagina, el avance se ve en vivo y no al final.
    print(texto, flush=True)


def _paso(titulo: str) -> None:
    _p(f"\n=== {titulo} ===")


# Un 401/403/404 de OCI es casi siempre un problema de configuración, no del código: se traduce
# a la causa probable para que no haya que descifrar el JSON del error.
DIAGNOSTICOS = {
    401: (
        "credenciales inválidas (401). Revisá que el fingerprint de ~/.oci/config coincida con el "
        "de la API key cargada en la consola, que key_file apunte al .pem correcto, y user/tenancy."
    ),
    403: (
        "sin permisos (403). Falta la política IAM sobre el bucket, o tu usuario no está en el "
        "grupo nuevamente-backend a la que apunta la política."
    ),
    404: (
        "no se encontró el recurso (404). El nombre del bucket (OCI_BUCKET_NAME) o el namespace "
        "(OCI_NAMESPACE) son incorrectos, o el bucket está en otra región (OCI_REGION)."
    ),
}


def _describir(error: Exception) -> str:
    if isinstance(error, oci.exceptions.ServiceError):
        base = DIAGNOSTICOS.get(error.status, f"el servicio respondió {error.status} ({error.code})")
        return f"{base}\n  mensaje de OCI: {error.message}"
    if isinstance(error, oci.exceptions.RequestException):
        return f"no se pudo conectar con OCI (¿sin red o timeout?): {error}"
    return f"{type(error).__name__}: {error}"


def _fallo(error: Exception) -> None:
    _p(f"FALLÓ — {_describir(error)}")


def paso_configuracion() -> oci.object_storage.ObjectStorageClient | None:
    """Devuelve el cliente listo, o None si falta configuración (sale con código 2)."""
    _paso("(a) Configuración")

    requeridas = {
        "OCI_BUCKET_NAME": settings.oci_bucket_name,
        "OCI_NAMESPACE": settings.oci_namespace,
        "OCI_REGION": settings.oci_region,
    }
    faltan = [nombre for nombre, valor in requeridas.items() if not valor]
    if faltan:
        _p(f"FALTA configuración — variables vacías en el .env: {', '.join(faltan)}")
        return None
    _p(f"OK — variables del .env (bucket: {settings.oci_bucket_name}, región: {settings.oci_region})")

    ruta = Path(oci.config.DEFAULT_LOCATION).expanduser()
    if not ruta.is_file():
        _p(f"FALTA configuración — no existe {ruta}. Ver README, sección «Configurar OCI Object Storage».")
        return None
    _p(f"OK — existe {ruta}")

    try:
        config = oci.config.from_file(file_location=str(ruta), profile_name=settings.oci_config_profile)
        # La región del .env manda sobre la del perfil: así el smoke prueba lo mismo que usará la app.
        config["region"] = settings.oci_region
        oci.config.validate_config(config)
    except (oci.exceptions.ProfileNotFound, oci.exceptions.InvalidConfig, oci.exceptions.InvalidKeyFilePath) as e:
        _p(f"FALTA configuración — perfil «{settings.oci_config_profile}» inválido: {e}")
        return None
    _p(f"OK — perfil «{settings.oci_config_profile}» validado con oci.config.validate_config")

    return oci.object_storage.ObjectStorageClient(config)


def main() -> int:
    cliente = paso_configuracion()
    if cliente is None:
        return 2

    ns, bucket = settings.oci_namespace, settings.oci_bucket_name
    marca = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    nombre = f"{PREFIJO}{marca}.txt"
    contenido = f"smoke test de NuevaMente — {marca} — tildes y ñ: áéíóú ñ\n".encode("utf-8")
    fallos = 0
    subido = False

    _paso(f"(b) Subida de {nombre}")
    try:
        cliente.put_object(ns, bucket, nombre, contenido, content_type="text/plain; charset=utf-8")
        subido = True
        _p(f"OK — {len(contenido)} bytes subidos")
    except Exception as e:  # noqa: BLE001 — se informa la causa y se sigue con el próximo paso
        _fallo(e)
        fallos += 1

    _paso("(c) Descarga y comparación")
    if not subido:
        _p("OMITIDO — la subida falló, no hay nada que descargar")
    else:
        try:
            descargado = cliente.get_object(ns, bucket, nombre).data.content
            if descargado != contenido:
                raise ValueError(f"el contenido difiere (subido {len(contenido)} bytes, bajado {len(descargado)})")
            _p("OK — el contenido descargado es idéntico al subido")
        except Exception as e:  # noqa: BLE001
            _fallo(e)
            fallos += 1

    _paso(f"(d) Listado con prefijo {PREFIJO}")
    try:
        objetos = [o.name for o in cliente.list_objects(ns, bucket, prefix=PREFIJO).data.objects]
        _p(f"OK — {len(objetos)} objeto(s): {', '.join(objetos) if objetos else '(ninguno)'}")
        if subido and nombre not in objetos:
            raise ValueError(f"{nombre} no aparece en el listado aunque se subió")
    except Exception as e:  # noqa: BLE001
        _fallo(e)
        fallos += 1

    # El borrado se intenta siempre que hubo un intento de subida, aunque un paso intermedio haya fallado.
    _paso("(e) Borrado del objeto de prueba")
    try:
        cliente.delete_object(ns, bucket, nombre)
        _p("OK — objeto borrado")
    except oci.exceptions.ServiceError as e:
        if not subido and e.status == 404:
            _p("OK — no había nada que borrar (la subida había fallado)")
        else:
            _fallo(e)
            fallos += 1
            _p(f"  ojo: puede haber quedado {nombre} en el bucket; borralo a mano desde la consola.")
    except Exception as e:  # noqa: BLE001
        _fallo(e)
        fallos += 1

    _p(f"\nResultado: {'TODO OK' if not fallos else f'{fallos} paso(s) fallaron'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
