"""
Diagnóstico MANUAL de las dependencias reales, una por una y con cronómetro. No es parte de pytest.

Sirve para saber QUÉ paso se cuelga cuando POST /api/v1/adaptar no responde. Necesita el .env completo
y ~/.oci/config. Ejecuta, en este orden:
    (a) inicializar el vector store de Chroma (en una carpeta temporal: no toca data/vector_store)
    (b) generar el embedding de un texto corto
    (c) subir y descargar un archivo pequeño a OCI (directo al SDK, SIN fallback local: el fallback
        taparía justo la falla que se busca) y borrarlo
    (d) UNA llamada a Gemini con un prompt trivial (consume una unidad de la cuota diaria; ojo: si
        la API responde error, la librería reintenta una vez por su cuenta)
Cada paso tiene su propio límite de tiempo (segundos, argumentos opcionales): el script nunca se cuelga.
Un paso colgado deja su hilo daemon vivo hasta que termine el proceso; por eso se sale con os._exit.

Uso:
    python scripts/diagnostico_pasos.py [limite_chroma] [limite_embedding] [limite_oci] [limite_gemini]
    (por defecto 30 30 40 y GEMINI_TIMEOUT_TOTAL_S)

Códigos de salida: 0 todo OK, 1 algún paso FALLÓ, 2 algún paso excedió su límite (TIMEOUT).
"""

import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config import settings  # noqa: E402
from app.logging_config import configurar_logging  # noqa: E402
from app.trazas import TiempoAgotado, ejecutar_con_limite  # noqa: E402

OK, FALLO, TIMEOUT = "OK", "FALLÓ", "TIMEOUT"


def paso_chroma() -> str:
    from app.rag.vector_store import VectorStore

    with tempfile.TemporaryDirectory(prefix="diagnostico_chroma_") as carpeta:
        VectorStore(path=carpeta, nombre_coleccion="diagnostico")
    return "colección creada en carpeta temporal"


def paso_embedding() -> str:
    from app.rag.embeddings import GeneradorDeEmbeddings

    vector = GeneradorDeEmbeddings().modelo.embed_query("hola mundo")
    return f"vector de {len(vector)} dimensiones"


def paso_oci() -> str:
    from app.oci.almacenamiento import Almacenamiento

    if not settings.oci_bucket_name or not settings.oci_namespace:
        raise RuntimeError("OCI_BUCKET_NAME u OCI_NAMESPACE están vacías")
    cliente = Almacenamiento()._obtener_cliente()
    nombre = f"diagnostico/{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-prueba.txt"
    contenido = b"diagnostico de NuevaMente"
    cliente.put_object(settings.oci_namespace, settings.oci_bucket_name, nombre, contenido)
    descargado = cliente.get_object(settings.oci_namespace, settings.oci_bucket_name, nombre).data.content
    if descargado != contenido:
        raise RuntimeError("el contenido descargado no coincide con el subido")
    try:
        cliente.delete_object(settings.oci_namespace, settings.oci_bucket_name, nombre)
        borrado = "borrado"
    except Exception as e:  # noqa: BLE001 — limpiar es opcional
        borrado = f"NO se pudo borrar ({type(e).__name__})"
    return f"subida y descarga correctas, objeto {borrado}"


def paso_gemini() -> str:
    from app.llm.gemini_client import ClienteGemini

    texto = ClienteGemini().modelo.invocar("Respondé solo con la palabra OK.", "Decí OK.")
    return f"respuesta de {len(texto)} caracteres"


def correr(nombre: str, funcion, limite: float) -> tuple[str, str, float]:
    print(f"\n[{nombre}] límite {limite:g}s ...", flush=True)
    inicio = time.perf_counter()
    try:
        detalle = ejecutar_con_limite(funcion, limite, nombre)
        estado = OK
    except TiempoAgotado:
        estado, detalle = TIMEOUT, f"sin respuesta tras {limite:g}s"
    except Exception as e:  # noqa: BLE001 — se informa y se sigue con el próximo paso
        estado, detalle = FALLO, f"{type(e).__name__}: {str(e)[:200]}"
    duracion = time.perf_counter() - inicio
    print(f"[{nombre}] {estado} en {duracion:.2f}s — {detalle}", flush=True)
    return estado, detalle, duracion


def main() -> int:
    configurar_logging()
    args = [float(a) for a in sys.argv[1:5]]
    limites = args + [30.0, 30.0, 40.0, settings.gemini_timeout_total_s][len(args):]
    pasos = [
        ("a) vector store (Chroma)", paso_chroma, limites[0]),
        ("b) embedding de un texto corto", paso_embedding, limites[1]),
        ("c) OCI: subir y descargar", paso_oci, limites[2]),
        ("d) Gemini: UNA llamada", paso_gemini, limites[3]),
    ]
    resultados = [(nombre, *correr(nombre, funcion, limite)) for nombre, funcion, limite in pasos]

    print("\n=== Resumen ===")
    for nombre, estado, _, duracion in resultados:
        print(f"{estado:8} {duracion:7.2f}s  {nombre}")

    colgados = [n for n, estado, *_ in resultados if estado == TIMEOUT]
    fallidos = [n for n, estado, *_ in resultados if estado == FALLO]
    if colgados:
        print(f"\nSospechoso: {colgados[0]} (excedió su límite; es el que cuelga las solicitudes).")
        return 2
    if fallidos:
        print(f"\nSospechoso: {fallidos[0]} (falló; revisá el detalle de arriba).")
        return 1
    print("\nNingún paso falló ni se colgó por separado. Si la API se cuelga igual, mirá los logs paso=... del servidor.")
    return 0


if __name__ == "__main__":
    codigo = main()
    sys.stdout.flush()
    os._exit(codigo)
