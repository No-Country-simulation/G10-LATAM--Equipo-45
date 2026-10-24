"""
Smoke test MANUAL contra la API real de Gemini. No es parte de pytest.

Verifica en orden, con la GOOGLE_API_KEY del .env:
  (a) embeddings: un embed_query de una frase corta (imprime la dimensión),
  (b) chat: una llamada simple con ClienteGemini,
  (c) orquestación: Orquestador.adaptar sobre un texto de ejemplo (VCN en OCI),
      una vez con Flashcards y otra con Guía práctica, sobre un Chroma en memoria.

Uso (desde cualquier carpeta):
    python scripts/smoke_gemini.py

Consume cuota de la API real (pocas llamadas). Sale con código 0 si todo
anduvo, 1 si algún paso falló y 2 si no hay API key.
"""

import json
import os
import sys
import uuid
from pathlib import Path

# Corre desde la raíz del repo: así `import app` funciona y pydantic-settings encuentra el .env.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

import chromadb  # noqa: E402
from chromadb.config import Settings as ChromaSettings  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm.gemini_client import ClienteGemini  # noqa: E402
from app.llm.orquestador import Orquestador  # noqa: E402
from app.llm.prompts import FormatoSalida, PerfilDestinatario  # noqa: E402
from app.rag.embeddings import GeneradorDeEmbeddings  # noqa: E402
from app.rag.vector_store import VectorStore  # noqa: E402

TEXTO_EJEMPLO = """\
Una Virtual Cloud Network (VCN) es una red privada y aislada dentro de Oracle Cloud Infrastructure donde corren tus recursos. Funciona como un datacenter virtual: vos definís el bloque CIDR, las subredes y las reglas de tráfico, y ningún recurso es accesible desde afuera salvo que lo habilites explícitamente.

Dentro de una VCN se crean subredes, que pueden ser públicas o privadas. Las subredes públicas permiten recursos con IP pública, como un balanceador de carga; las privadas se usan para bases de datos y servidores internos. Para que una subred pública llegue a internet hace falta un Internet Gateway y una regla en su tabla de ruteo.

La seguridad de una VCN se controla con Security Lists y Network Security Groups, que definen qué tráfico de entrada y salida se permite. Para que los recursos de una subred privada salgan a internet sin ser accesibles desde afuera se usa un NAT Gateway, y para hablar con servicios de Oracle sin salir a internet, un Service Gateway.
"""


def _paso(titulo: str) -> None:
    print(f"\n=== {titulo} ===")


def _fallo(causa: Exception) -> None:
    print(f"FALLÓ: {type(causa).__name__}: {causa}")


def paso_embeddings() -> None:
    _paso(f"(a) Embeddings ({settings.gemini_embedding_model})")
    vector = GeneradorDeEmbeddings().generar_embedding_query("¿Qué es una VCN en OCI?")
    print(f"OK — dimensión del vector: {len(vector)}")


def paso_chat() -> None:
    _paso(f"(b) Chat ({settings.gemini_model})")
    respuesta = ClienteGemini().generar(
        "Sos un asistente conciso.", "Respondé en una sola oración: ¿qué es una VCN en OCI?"
    )
    print(f"OK — respuesta: {respuesta.strip()}")


def paso_orquestacion() -> None:
    # Un Chroma en memoria nuevo por corrida: no deja nada en disco ni se mezcla con otros documentos.
    store = VectorStore(
        cliente=chromadb.EphemeralClient(ChromaSettings(anonymized_telemetry=False)),
        nombre_coleccion=f"smoke_{uuid.uuid4().hex}",
    )
    orquestador = Orquestador(store, ClienteGemini())

    for formato in (FormatoSalida.FLASHCARDS, FormatoSalida.GUIA_PRACTICA):
        _paso(f"(c) Orquestación — {formato.value}")
        resultado = orquestador.adaptar(
            nombre_archivo="vcn_oci.md",
            documento_titulo="Introducción a las VCN en OCI",
            documento_contenido=TEXTO_EJEMPLO,
            perfil=PerfilDestinatario.PRINCIPIANTE,
            formato=formato,
        )
        print(f"OK — {len(resultado.items)} ítems (perfil: {resultado.perfil.value})")
        print(json.dumps(resultado.items, ensure_ascii=False, indent=2))
        print(f"Fragmentos usados ({len(resultado.fragmentos_usados)}):")
        for f in resultado.fragmentos_usados:
            resumen = f.texto.replace("\n", " ")[:80]
            print(f"  - chunk {f.metadata.get('indice')} (score {f.score:.3f}): {resumen}...")


def main() -> int:
    if not settings.google_api_key:
        print(
            "No se encontró GOOGLE_API_KEY. Este smoke test llama a la API real de Gemini.\n"
            "Copiá .env.example a .env en la raíz del repo y completá GOOGLE_API_KEY, "
            "o exportala como variable de entorno."
        )
        return 2

    fallos = 0
    for paso in (paso_embeddings, paso_chat, paso_orquestacion):
        try:
            paso()
        except Exception as e:  # noqa: BLE001 — se informa la causa y se sigue con el próximo paso
            _fallo(e)
            if e.__cause__ is not None:
                print(f"  causa original: {type(e.__cause__).__name__}: {e.__cause__}")
            fallos += 1

    print(f"\nResultado: {'TODO OK' if not fallos else f'{fallos} paso(s) fallaron'}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
