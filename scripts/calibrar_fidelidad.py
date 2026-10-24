"""
Calibración MANUAL del umbral de fidelidad (NM-20). No es parte de pytest.

Corre el VerificadorDeFidelidad con embeddings REALES de Gemini sobre un set
golden chico y fijo, escrito a mano acá abajo, y muestra si los casos FIELES
(paráfrasis correctas de la fuente) se separan de los INFIELES:
  (a) datos inventados pero sobre el mismo tema,
  (b) contenido de otro tema.
La fuente es el TEXTO_EJEMPLO de scripts/smoke_gemini.py.

NO llama a Gemini de generación (la cuota gratuita es de 20 llamadas por día):
solo embeddings. Los fragmentos se embeben una sola vez gracias a un caché
local, así la corrida completa hace unas pocas llamadas batch.

Uso (desde cualquier carpeta):
    python scripts/calibrar_fidelidad.py

Sale con código 0 si la calibración corrió (separe o no los grupos: que NO se
separen es un resultado válido y se informa), 1 si falló una llamada a la API
y 2 si no hay API key.
"""

import os
import sys
from pathlib import Path

# Corre desde la raíz del repo: así `import app` funciona y pydantic-settings encuentra el .env.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))
os.chdir(RAIZ)

from app.config import settings  # noqa: E402
from app.ingesta.models import DocumentoIngerido, FormatoOrigen  # noqa: E402
from app.llm.fidelidad import ResultadoFidelidad, VerificadorDeFidelidad  # noqa: E402
from app.llm.prompts import FormatoSalida  # noqa: E402
from app.rag.chunking import dividir_en_chunks  # noqa: E402
from app.rag.embeddings import GeneradorDeEmbeddings  # noqa: E402
from app.rag.models import Chunk  # noqa: E402
from app.rag.vector_store import ResultadoBusqueda  # noqa: E402
from smoke_gemini import TEXTO_EJEMPLO  # noqa: E402

FLASH = FormatoSalida.FLASHCARDS
GUIA = FormatoSalida.GUIA_PRACTICA

FIEL = "fiel"
INFIEL_TEMA = "infiel (inventado, mismo tema)"
INFIEL_OTRO = "infiel (otro tema)"

# (nombre, grupo, formato, items). Fijo a propósito: cambiarlo invalida la comparación entre corridas.
CASOS: list[tuple[str, str, FormatoSalida, list[dict[str, str]]]] = [
    # --- FIELES: paráfrasis correctas de lo que dice la fuente ---
    ("fiel-1 flashcard: qué es una VCN", FIEL, FLASH, [{
        "pregunta": "¿Qué es una VCN?",
        "respuesta": "Es una red privada y aislada dentro de OCI donde ubicás tus recursos. Se parece a un "
                     "datacenter virtual en el que definís el rango de direcciones, las subredes y el tráfico permitido.",
    }]),
    ("fiel-2 flashcard: subred pública vs privada", FIEL, FLASH, [{
        "pregunta": "¿Qué diferencia hay entre una subred pública y una privada?",
        "respuesta": "Las públicas admiten recursos con IP pública, por ejemplo un balanceador de carga. "
                     "Las privadas se reservan para recursos internos como bases de datos y servidores.",
    }]),
    ("fiel-3 flashcard: NAT Gateway", FIEL, FLASH, [{
        "pregunta": "¿Para qué sirve un NAT Gateway?",
        "respuesta": "Permite que los recursos de una subred privada salgan a internet sin que nadie "
                     "desde afuera pueda acceder a ellos.",
    }]),
    ("fiel-4 guía: armar la red", FIEL, GUIA, [
        {"titulo": "Crear la VCN",
         "detalle": "Definí el bloque CIDR y creá la VCN: es la red privada y aislada donde van a vivir tus recursos."},
        {"titulo": "Crear las subredes",
         "detalle": "Dentro de la VCN creá una subred pública para lo que necesita IP pública, como un balanceador, "
                    "y una privada para bases de datos y servidores internos."},
    ]),
    ("fiel-5 guía: salida a internet", FIEL, GUIA, [
        {"titulo": "Agregar un Internet Gateway",
         "detalle": "Creá un Internet Gateway en la VCN para que la subred pública pueda llegar a internet."},
        {"titulo": "Configurar el ruteo",
         "detalle": "Agregá una regla en la tabla de ruteo de la subred pública que envíe el tráfico al Internet Gateway."},
    ]),
    ("fiel-6 guía: seguridad y subred privada", FIEL, GUIA, [
        {"titulo": "Controlar el tráfico",
         "detalle": "Usá Security Lists o Network Security Groups para definir qué tráfico de entrada y salida se permite."},
        {"titulo": "Conectar la subred privada",
         "detalle": "Usá un NAT Gateway para salir a internet sin ser accesible desde afuera y un Service Gateway "
                    "para llegar a servicios de Oracle sin pasar por internet."},
    ]),
    # --- INFIELES (a): datos inventados, mismo tema ---
    ("infiel-a7 flashcard: límite de subredes", INFIEL_TEMA, FLASH, [{
        "pregunta": "¿Cuántas subredes admite una VCN?",
        "respuesta": "Una VCN admite como máximo cuatro subredes y todas deben ser públicas. Las subredes "
                     "privadas se agregaron recién en la versión 2 de OCI y requieren una licencia adicional.",
    }]),
    ("infiel-a8 flashcard: cifrado cuántico", INFIEL_TEMA, FLASH, [{
        "pregunta": "¿Cómo se cifra el tráfico de la VCN?",
        "respuesta": "Toda la VCN usa por defecto cifrado cuántico de 512 bits administrado por el Quantum Gateway, "
                     "que reemplazó a las Security Lists en 2023.",
    }]),
    ("infiel-a9 guía: firewall y plan premium", INFIEL_TEMA, GUIA, [
        {"titulo": "Activar el Firewall Dinámico",
         "detalle": "Ejecutá el comando oci vcn enable-firewall-ai para habilitar la inspección de paquetes con "
                    "inteligencia artificial y esperá 48 horas a que aprenda el patrón de tráfico."},
        {"titulo": "Contratar el plan Premium de red",
         "detalle": "Pedile a Oracle el plan Premium de red, que garantiza un SLA del 100% y multiplica por diez "
                    "el ancho de banda de la VCN."},
    ]),
    # --- INFIELES (b): otro tema ---
    ("infiel-b10 flashcard: fotosíntesis", INFIEL_OTRO, FLASH, [{
        "pregunta": "¿Qué es la fotosíntesis?",
        "respuesta": "Es el proceso por el cual las plantas convierten luz solar, agua y dióxido de carbono en "
                     "glucosa y oxígeno. Ocurre principalmente en los cloroplastos de las hojas.",
    }]),
    ("infiel-b11 guía: pan casero", INFIEL_OTRO, GUIA, [
        {"titulo": "Preparar la masa",
         "detalle": "Mezclá 500 g de harina con agua tibia, sal y levadura, y amasá durante diez minutos."},
        {"titulo": "Hornear",
         "detalle": "Dejá levar la masa una hora y horneá a 220 grados durante veinte minutos hasta que dore."},
    ]),
    ("infiel-b12 flashcard: Mundial 1986", INFIEL_OTRO, FLASH, [{
        "pregunta": "¿Quién ganó el Mundial de 1986?",
        "respuesta": "Argentina ganó la Copa del Mundo de 1986 en México, venciendo 3-2 a Alemania Occidental "
                     "en la final con Diego Maradona como figura.",
    }]),
]


class _GeneradorConCache:
    """
    Envuelve un GeneradorDeEmbeddings y recuerda los vectores por texto.

    Los fragmentos de la fuente son los mismos en los 12 casos: sin caché se
    re-embeberían 12 veces. Solo existe en este script; el verificador de
    producción no lo necesita.
    """

    def __init__(self, generador: GeneradorDeEmbeddings):
        self._generador = generador
        self._cache: dict[str, list[float]] = {}
        self.llamadas_a_la_api = 0

    def generar_embeddings(self, chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]:
        faltantes = [c for c in chunks if c.texto not in self._cache]
        if faltantes:
            self.llamadas_a_la_api += 1
            for chunk, vector in self._generador.generar_embeddings(faltantes):
                self._cache[chunk.texto] = vector
        return [(c, self._cache[c.texto]) for c in chunks]


def _fragmentos_de_la_fuente() -> list[ResultadoBusqueda]:
    """Los fragmentos que vería el verificador en producción: el chunking real de la fuente."""
    documento = DocumentoIngerido(
        texto=TEXTO_EJEMPLO.strip(), nombre_archivo="vcn_oci.md", formato_origen=FormatoOrigen.TEXTO_PLANO
    )
    return [
        ResultadoBusqueda(texto=c.texto, nombre_archivo=c.nombre_archivo, metadata={"indice": c.indice}, score=1.0)
        for c in dividir_en_chunks(documento)
    ]


def _estadisticas(nombre: str, scores: list[float]) -> None:
    print(f"  {nombre:<34} n={len(scores)}  mín={min(scores):.3f}  máx={max(scores):.3f}  "
          f"promedio={sum(scores) / len(scores):.3f}")


def main() -> int:
    if not settings.google_api_key:
        print(
            "No se encontró GOOGLE_API_KEY. Este script llama a la API real de embeddings de Gemini.\n"
            "Copiá .env.example a .env en la raíz del repo y completá GOOGLE_API_KEY, "
            "o exportala como variable de entorno."
        )
        return 2

    fragmentos = _fragmentos_de_la_fuente()
    generador = _GeneradorConCache(GeneradorDeEmbeddings())
    verificador = VerificadorDeFidelidad(generador, umbral=settings.umbral_anclaje)

    print(f"Modelo de embeddings: {settings.gemini_embedding_model}")
    print(f"Fragmentos de la fuente: {len(fragmentos)}   Umbral actual (provisorio): {settings.umbral_anclaje}\n")

    scores_por_grupo: dict[str, list[float]] = {FIEL: [], INFIEL_TEMA: [], INFIEL_OTRO: []}
    try:
        for nombre, grupo, formato, items in CASOS:
            resultado: ResultadoFidelidad = verificador.verificar(items, formato, fragmentos)
            scores_por_grupo[grupo].append(resultado.anclaje_fuente_score)
            marca = "BAJA CONFIANZA" if resultado.baja_confianza else "ok"
            print(f"[{grupo.split(' ')[0]:<6}] {nombre:<42} score={resultado.anclaje_fuente_score:.3f}  {marca}")
            if resultado.motivo:
                print(f"           motivo: {resultado.motivo}")
    except Exception as e:  # noqa: BLE001 — se informa la causa y se sale con código 1
        print(f"\nFALLÓ: {type(e).__name__}: {e}")
        if e.__cause__ is not None:
            print(f"  causa original: {type(e.__cause__).__name__}: {e.__cause__}")
        return 1

    fieles = scores_por_grupo[FIEL]
    infieles = scores_por_grupo[INFIEL_TEMA] + scores_por_grupo[INFIEL_OTRO]

    print("\n=== Resumen ===")
    _estadisticas("Fieles", fieles)
    _estadisticas("Infieles (todos)", infieles)
    _estadisticas("  a) inventados, mismo tema", scores_por_grupo[INFIEL_TEMA])
    _estadisticas("  b) otro tema", scores_por_grupo[INFIEL_OTRO])
    print(f"  Llamadas batch a la API de embeddings: {generador.llamadas_a_la_api} "
          f"(con caché de fragmentos; verificar() sin caché haría {2 * len(CASOS)})")

    min_fieles, max_infieles = min(fieles), max(infieles)
    print("\n=== ¿Se separan los grupos? ===")
    if min_fieles > max_infieles:
        sugerido = (min_fieles + max_infieles) / 2
        print(f"SÍ: el peor fiel ({min_fieles:.3f}) supera al mejor infiel ({max_infieles:.3f}); "
              f"margen = {min_fieles - max_infieles:.3f}.")
        print(f"Umbral sugerido (punto medio): {sugerido:.3f}   (actual: {settings.umbral_anclaje})")
        print("Con un set tan chico, tomalo como punto de partida y no como valor definitivo.")
    else:
        print(f"NO: se solapan. El peor fiel ({min_fieles:.3f}) NO supera al mejor infiel ({max_infieles:.3f}).")
        mal_fieles = [s for s in fieles if s <= max_infieles]
        mal_infieles = [s for s in infieles if s >= min_fieles]
        print(f"  Zona de solape: [{min_fieles:.3f}, {max_infieles:.3f}] — "
              f"{len(mal_fieles)} fiel(es) y {len(mal_infieles)} infiel(es) caen dentro.")
        grupos_en_solape = [
            g for g in (INFIEL_TEMA, INFIEL_OTRO) if any(s >= min_fieles for s in scores_por_grupo[g])
        ]
        print("Ningún umbral único separa bien estos casos. Infieles dentro del solape: "
              f"{', '.join(grupos_en_solape)}.")
        print("No se sugiere umbral. Opciones: tratar el score como informativo, o revisar qué unidades "
              "evaluar / cómo agregarlas antes de fijar un umbral.")

    print(f"\nPara comparar, con el umbral actual {settings.umbral_anclaje}: "
          f"{sum(s >= settings.umbral_anclaje for s in fieles)}/{len(fieles)} fieles pasan, "
          f"{sum(s < settings.umbral_anclaje for s in infieles)}/{len(infieles)} infieles se marcan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
