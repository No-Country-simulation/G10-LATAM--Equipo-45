"""
NM-09 — Segmentación de texto en chunks.

Recibe el texto de un DocumentoIngerido (NM-03/NM-04) y lo parte en
fragmentos (chunks) de tamaño acotado, con solapamiento entre fragmentos
consecutivos para no perder contexto en los bordes.

Estrategia: separador recursivo (párrafo > línea > espacio > caracter),
igual a la de LangChain's RecursiveCharacterTextSplitter, reimplementada
acá sin la dependencia para tener control total y que sea fácil de testear
(NM-14) sin necesitar la librería completa instalada.
"""

from app.config import settings
from app.ingesta.models import DocumentoIngerido
from app.rag.models import Chunk

# Orden de preferencia de separadores: primero intenta cortar por párrafo,
# si un fragmento sigue siendo muy grande, cae al siguiente separador.
SEPARADORES_POR_DEFECTO = ["\n\n", "\n", ". ", " ", ""]


def _dividir_recursivo(texto: str, tamano_max: int, separadores: list[str]) -> list[str]:
    """Divide `texto` recursivamente probando cada separador en orden."""
    if len(texto) <= tamano_max or not separadores:
        return [texto] if texto else []

    separador, *resto_separadores = separadores
    partes = texto.split(separador) if separador else list(texto)
    union = separador

    if separador == ". ":
        # El split se come el punto: se lo devolvemos a cada oración y las unimos solo con espacio.
        if partes and partes[-1] == "":
            partes.pop()
            partes = [p + "." for p in partes]
        else:
            partes = [p + "." for p in partes[:-1]] + partes[-1:]
        union = " "

    fragmentos: list[str] = []
    buffer = ""

    for parte in partes:
        candidato = (buffer + union + parte) if buffer else parte

        if len(candidato) <= tamano_max:
            buffer = candidato
        else:
            if buffer:
                fragmentos.append(buffer)
            if len(parte) > tamano_max:
                # La parte individual sigue siendo muy grande: recursar con el siguiente separador
                fragmentos.extend(_dividir_recursivo(parte, tamano_max, resto_separadores))
                buffer = ""
            else:
                buffer = parte

    if buffer:
        fragmentos.append(buffer)

    return fragmentos


def _cola_en_limite_de_palabra(texto: str, largo_max: int) -> str:
    """Devuelve hasta `largo_max` caracteres del final de `texto`, empezando en una palabra completa."""
    if largo_max <= 0:
        return ""
    if len(texto) <= largo_max:
        return texto.strip()

    inicio = len(texto) - largo_max
    cola = texto[inicio:]
    # Si el corte cae en medio de una palabra, se descarta el pedazo parcial hasta el primer espacio.
    if not texto[inicio - 1].isspace() and not cola[0].isspace():
        primer_espacio = next((i for i, c in enumerate(cola) if c.isspace()), None)
        if primer_espacio is None:
            return ""
        cola = cola[primer_espacio:]
    return cola.strip()


def _aplicar_overlap(fragmentos: list[str], overlap: int) -> list[str]:
    """Agrega al inicio de cada fragmento (salvo el primero) la cola del anterior."""
    if overlap <= 0 or len(fragmentos) <= 1:
        return fragmentos

    resultado = [fragmentos[0]]
    for anterior, actual in zip(fragmentos, fragmentos[1:]):
        # largo_max = overlap - 1 para que cola + separador (1 espacio) no pase de `overlap`.
        cola = _cola_en_limite_de_palabra(anterior, overlap - 1)
        resultado.append(f"{cola} {actual}" if cola and not actual.startswith(cola) else actual)

    return resultado


def dividir_en_chunks(
    documento: DocumentoIngerido,
    tamano_chunk: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """
    Divide el texto de un documento ingerido en una lista de Chunks.

    Args:
        documento: resultado de cargar_pdf() o cargar_texto()
        tamano_chunk: tamaño base de cada chunk, en caracteres
            (default: settings.chunk_size). Ojo: el overlap se antepone al
            fragmento, así que un chunk puede medir hasta
            tamano_chunk + overlap caracteres (el chunk final incluido).
        overlap: solapamiento entre chunks consecutivos, en caracteres
            (default: settings.chunk_overlap)

    Returns:
        Lista de Chunk, vacía si el documento no tiene texto. Se descartan
        los chunks sin ningún carácter alfanumérico (ej. un .md con solo "#").
    """
    tamano_chunk = tamano_chunk if tamano_chunk is not None else settings.chunk_size
    overlap = overlap if overlap is not None else settings.chunk_overlap

    if tamano_chunk <= 0:
        raise ValueError("tamano_chunk debe ser mayor a 0")
    if overlap < 0 or overlap >= tamano_chunk:
        raise ValueError("overlap debe ser >= 0 y menor que tamano_chunk")

    if documento.esta_vacio:
        return []

    fragmentos = _dividir_recursivo(documento.texto, tamano_chunk, SEPARADORES_POR_DEFECTO)
    fragmentos = _aplicar_overlap(fragmentos, overlap)

    # Se filtra antes de numerar para que los índices queden secuenciales.
    fragmentos = [f for f in fragmentos if any(c.isalnum() for c in f)]

    return [
        Chunk(
            texto=fragmento,
            indice=i,
            nombre_archivo=documento.nombre_archivo,
            metadata={"formato_origen": documento.formato_origen.value},
        )
        for i, fragmento in enumerate(fragmentos)
    ]
