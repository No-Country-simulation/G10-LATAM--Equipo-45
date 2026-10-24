"""
NM-13 — Diseño de prompts base (few-shot / role prompting) por perfil.

Define los prompts para las 2x2 combinaciones del MVP:
  Perfiles:  Principiante / Transición de carrera · Líder Técnico / Arquitecto
  Formatos:  Flashcards · Guía práctica paso a paso

Los valores de PerfilDestinatario y FormatoSalida son los mismos que el
contrato del endpoint POST /adaptar-contenido (ver README y NM-06, schema
Pydantic de Larissa/Jose) — si cambian acá, avisar para mantenerlos
sincronizados.
"""

from enum import Enum


class PerfilDestinatario(str, Enum):
    PRINCIPIANTE = "Principiante"
    LIDER_TECNICO = "Lider Tecnico / Arquitecto"


class FormatoSalida(str, Enum):
    FLASHCARDS = "Flashcards"
    GUIA_PRACTICA = "Guia Practica Paso a Paso"


# --- Prompt de sistema (role prompting) por perfil ---

_ROL_POR_PERFIL: dict[PerfilDestinatario, str] = {
    PerfilDestinatario.PRINCIPIANTE: (
        "Sos un instructor técnico paciente que explica conceptos a personas "
        "en transición de carrera hacia tecnología, sin asumir conocimiento "
        "previo del tema. Evitás jerga sin explicarla, usás analogías "
        "cotidianas, y priorizás que el lector entienda el 'por qué' antes "
        "del 'cómo'. Nunca asumís que el lector sabe qué es un concepto solo "
        "porque lo mencionás."
    ),
    PerfilDestinatario.LIDER_TECNICO: (
        "Sos un arquitecto de software senior escribiendo para otro líder "
        "técnico o arquitecto. Asumís conocimiento sólido de ingeniería de "
        "software y vas directo a las decisiones de diseño, trade-offs, "
        "riesgos y a cómo encaja el concepto en un sistema más grande. "
        "Evitás explicar fundamentos básicos salvo que sean específicos del "
        "tema — el lector ya sabe programar y operar sistemas en producción."
    ),
}


# --- Instrucciones de formato (estructura de salida esperada) ---

_INSTRUCCION_POR_FORMATO: dict[FormatoSalida, str] = {
    FormatoSalida.FLASHCARDS: (
        "Generá el contenido como una lista de flashcards en JSON, cada una "
        "con 'pregunta' y 'respuesta'. Cada flashcard debe cubrir un único "
        "concepto atómico extraído del documento fuente. La respuesta debe "
        "ser breve (2-4 oraciones) y autocontenida — alguien debería poder "
        "entenderla sin leer otras flashcards. Generá entre 5 y 12 "
        "flashcards según la densidad del contenido fuente."
    ),
    FormatoSalida.GUIA_PRACTICA: (
        "Generá el contenido como una guía práctica paso a paso en JSON: "
        "un objeto con una única clave 'pasos', cuyo valor es una lista "
        "ordenada de pasos, cada uno con 'titulo' y 'detalle'. "
        "Cada paso debe ser accionable (algo que el lector hace "
        "o verifica, no solo lee). Si el documento fuente describe un "
        "proceso, preservá el orden original salvo que haya una razón "
        "pedagógica explícita para cambiarlo."
    ),
}


# --- Ejemplo few-shot (uno por formato, genérico — no depende del perfil) ---

_EJEMPLO_FEW_SHOT: dict[FormatoSalida, str] = {
    FormatoSalida.FLASHCARDS: (
        '[{"pregunta": "¿Qué es una VCN en OCI?", '
        '"respuesta": "Una Virtual Cloud Network es una red privada y '
        'aislada dentro de Oracle Cloud donde corren tus recursos, similar '
        "a tener tu propio datacenter virtual con control total sobre "
        'direccionamiento IP, subredes y reglas de tráfico."}]'
    ),
    FormatoSalida.GUIA_PRACTICA: (
        '{"pasos": [{"titulo": "Crear la VCN", "detalle": "Desde la consola '
        'de OCI, ir a Networking > Virtual Cloud Networks y hacer clic en '
        'Create VCN. Definir un bloque CIDR que no colisione con tu red '
        'on-premise si vas a usar VPN o FastConnect."}]}'
    ),
}


def construir_prompt_sistema(perfil: PerfilDestinatario, formato: FormatoSalida) -> str:
    """
    Construye el prompt de sistema completo para una combinación perfil x formato.

    Combina: rol (quién es el modelo y para quién escribe) + instrucción de
    formato + un ejemplo few-shot de la estructura JSON esperada.
    """
    rol = _ROL_POR_PERFIL[perfil]
    instruccion_formato = _INSTRUCCION_POR_FORMATO[formato]
    ejemplo = _EJEMPLO_FEW_SHOT[formato]

    return (
        f"{rol}\n\n"
        f"{instruccion_formato}\n\n"
        "Reglas estrictas:\n"
        "- Todo el contenido debe estar anclado en el documento fuente "
        "provisto. No inventes datos, nombres, cifras ni pasos que no "
        "estén respaldados por el texto fuente.\n"
        "- Si el documento fuente no alcanza para cubrir algo relevante, "
        "omitilo en vez de inventarlo.\n"
        "- Respondé ÚNICAMENTE con JSON válido, sin texto adicional antes "
        "ni después.\n\n"
        f"Ejemplo de estructura esperada:\n{ejemplo}"
    )


def construir_prompt_usuario(documento_titulo: str, documento_contenido: str) -> str:
    """Construye el mensaje de usuario (el documento fuente a adaptar)."""
    return (
        f"Documento fuente: {documento_titulo}\n\n"
        f"---\n{documento_contenido}\n---\n\n"
        "Adaptá este contenido siguiendo las instrucciones del system prompt."
    )
