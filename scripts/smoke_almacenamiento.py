"""
Smoke test MANUAL de la clase Almacenamiento (NM-12 / NM-22) contra OCI Object Storage real.
No es parte de pytest.

Verifica en orden, con las credenciales de ~/.oci/config y las variables OCI_* del .env:
  (a) configuración: variables del .env, existencia de ~/.oci/config y oci.config.validate_config,
  (b) subir_documento con un nombre con tildes: se espera status «exito»,
  (c) descargar(objeto_id) y comparación byte a byte,
  (d) subir_json con un dict con tildes: se espera status «exito»,
  (e) fallback forzado: otra instancia apuntando a un bucket inexistente y a una carpeta local
      temporal; se espera «pendiente_oci», archivo en esa carpeta y descargar() que lo recupera,
  (f) limpieza: borra de OCI los objetos de (b) y (d) con el cliente del SDK y la carpeta temporal.

Uso (desde cualquier carpeta):
    python scripts/smoke_almacenamiento.py

Sube dos objetos diminutos bajo documentos/ y salidas/ y los borra al final; si un paso falla la
limpieza se intenta igual. Las instancias de (b)-(d) también usan una carpeta temporal, para que un
fallback inesperado no ensucie data/almacenamiento_local.
Sale con código 0 si todo anduvo, 1 si algún paso falló y 2 si falta configuración.
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Corre desde la raíz del repo: así `import app` funciona y pydantic-settings encuentra el .env.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

import oci  # noqa: E402

from app.config import settings  # noqa: E402
from app.oci.almacenamiento import Almacenamiento  # noqa: E402


def _p(texto: str = "") -> None:
    # flush=True: si la salida se redirige o se pagina, el avance se ve en vivo y no al final.
    print(texto, flush=True)


def _paso(titulo: str) -> None:
    _p(f"\n=== {titulo} ===")


def _describir(error: Exception) -> str:
    if isinstance(error, oci.exceptions.ServiceError):
        return f"el servicio respondió {error.status} ({error.code}): {error.message}"
    return f"{type(error).__name__}: {error}"


def _fallo(error: Exception) -> None:
    _p(f"FALLÓ — {_describir(error)}")


def paso_configuracion() -> oci.object_storage.ObjectStorageClient | None:
    """Devuelve el cliente real listo, o None si falta configuración (sale con código 2)."""
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
    temporal = Path(tempfile.mkdtemp(prefix="smoke_almacenamiento_"))
    fallos = 0
    objetos_subidos: list[str] = []  # los de (b) y (d) que realmente quedaron en el bucket

    try:
        almacenamiento = Almacenamiento(cliente=cliente, carpeta_local=temporal / "principal")
        datos = f"smoke de Almacenamiento — {marca} — tildes y ñ: áéíóú ñ\n".encode("utf-8")
        objeto_documento = ""

        _paso("(b) subir_documento con nombre con tildes")
        try:
            resultado = almacenamiento.subir_documento("guía de prueba.txt", datos, "text/plain; charset=utf-8")
            _p(f"objeto_id: {resultado.objeto_id}")
            if resultado.status_upload != "exito":
                raise ValueError(
                    f"status_upload = {resultado.status_upload!r} (se esperaba 'exito'); "
                    f"ruta_local = {resultado.ruta_local}. Mirá el warning de arriba para ver la causa."
                )
            objeto_documento = resultado.objeto_id
            objetos_subidos.append(resultado.objeto_id)
            _p(f"OK — status «exito» en el bucket {resultado.bucket}, {len(datos)} bytes")
        except Exception as e:  # noqa: BLE001 — se informa la causa y se sigue con el próximo paso
            _fallo(e)
            fallos += 1

        _paso("(c) descargar y comparación")
        if not objeto_documento:
            _p("OMITIDO — la subida falló, no hay nada que descargar")
        else:
            try:
                descargado = almacenamiento.descargar(objeto_documento)
                if descargado != datos:
                    raise ValueError(f"el contenido difiere (subido {len(datos)} bytes, bajado {len(descargado)})")
                _p("OK — los bytes descargados son idénticos a los subidos")
            except Exception as e:  # noqa: BLE001
                _fallo(e)
                fallos += 1

        _paso("(d) subir_json con tildes")
        try:
            resultado = almacenamiento.subir_json(
                "resultado de prueba", {"título": "Introducción a VCN", "marca": marca, "ñandú": True}
            )
            _p(f"objeto_id: {resultado.objeto_id}")
            if resultado.status_upload != "exito":
                raise ValueError(f"status_upload = {resultado.status_upload!r} (se esperaba 'exito')")
            objetos_subidos.append(resultado.objeto_id)
            _p("OK — status «exito»")
        except Exception as e:  # noqa: BLE001
            _fallo(e)
            fallos += 1

        _paso("(e) fallback forzado (bucket inexistente + carpeta local temporal)")
        try:
            carpeta_fallback = temporal / "fallback"
            bucket_falso = f"nuevamente-inexistente-{marca.lower()}"
            forzado = Almacenamiento(
                cliente=cliente, carpeta_local=carpeta_fallback, bucket=bucket_falso, namespace=ns
            )
            datos_fallback = f"documento pendiente — {marca}\n".encode("utf-8")
            resultado = forzado.subir_documento("pendiente.txt", datos_fallback)
            _p(f"objeto_id: {resultado.objeto_id}")
            if resultado.status_upload != "pendiente_oci":
                # Si por algún motivo subió de verdad, queda en el bucket falso (no debería existir): se avisa.
                raise ValueError(f"status_upload = {resultado.status_upload!r} (se esperaba 'pendiente_oci')")
            _p("OK — status «pendiente_oci»")

            ruta = Path(resultado.ruta_local) if resultado.ruta_local else None
            if ruta is None or not ruta.is_file() or carpeta_fallback.resolve() not in ruta.parents:
                raise ValueError(f"el archivo no está en la carpeta local temporal (ruta_local = {resultado.ruta_local})")
            _p(f"OK — el archivo existe en la carpeta local: {ruta}")

            if forzado.descargar(resultado.objeto_id) != datos_fallback:
                raise ValueError("descargar() no devolvió los bytes guardados en la carpeta local")
            _p("OK — descargar() recuperó los bytes desde la copia local")
        except Exception as e:  # noqa: BLE001
            _fallo(e)
            fallos += 1
    finally:
        # La limpieza se intenta siempre, aunque algún paso intermedio haya fallado.
        _paso("(f) Limpieza")
        for objeto in objetos_subidos:
            try:
                cliente.delete_object(ns, bucket, objeto)
                _p(f"OK — borrado {objeto}")
            except Exception as e:  # noqa: BLE001
                _fallo(e)
                fallos += 1
                _p(f"  ojo: puede haber quedado {objeto} en el bucket; borralo a mano desde la consola.")
        if not objetos_subidos:
            _p("OK — no había objetos para borrar del bucket")
        try:
            shutil.rmtree(temporal)
            _p(f"OK — carpeta temporal borrada: {temporal}")
        except OSError as e:
            _fallo(e)
            fallos += 1

    _p(f"\nResultado: {'TODO OK' if not fallos else f'{fallos} paso(s) fallaron'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
