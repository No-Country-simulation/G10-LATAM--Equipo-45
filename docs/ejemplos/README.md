# Ejemplos de ejecución

Respuestas reales de `POST /api/v1/adaptar`, descargadas desde la interfaz Streamlit el 25/10/2026 con Gemini real y OCI Object Storage. Los JSON están sin modificar. Sirven de evidencia del requisito "mínimo 3 ejemplos de ejecución" del hackathon (punto 7 de la [sección 11 del README](../../README.md#11-cumplimiento-de-requisitos)).

## Tres escenarios sobre el mismo documento

Los tres usan el mismo documento de entrada: el texto de ejemplo "Redes virtuales en Oracle Cloud Infrastructure (OCI)", definido en [frontend/ejemplos.py](../../frontend/ejemplos.py) y pegado como texto (sin archivo). Solo cambian el perfil y el formato.

| Archivo | Perfil | Formato | Modelo | Puntaje (`anclaje_fuente_score`) | `baja_confianza` | Fragmentos usados | Contenido | OCI |
|---|---|---|---|---|---|---|---|---|
| [ej1_principiante_flashcards.json](ej1_principiante_flashcards.json) | Principiante | Flashcards | gemini-3.5-flash | 0.8506 | false | 3 | 8 tarjetas | exito (documento y salida) |
| [ej2_lider_guia.json](ej2_lider_guia.json) | Lider Tecnico / Arquitecto | Guia Practica Paso a Paso | gemini-3.5-flash | 0.8712 | false | 3 | 5 pasos | exito (documento y salida) |
| [ej3_lider_flashcards.json](ej3_lider_flashcards.json) | Lider Tecnico / Arquitecto | Flashcards | gemini-3.5-flash-lite | 0.8568 | false | 3 | 7 tarjetas | exito (documento y salida) |

El umbral de `baja_confianza` fue 0.72 en las tres.

## Ingestión de un PDF real

| Archivo | Archivo de origen | Perfil | Formato | Modelo | Puntaje | `baja_confianza` | Fragmentos usados | Contenido | OCI |
|---|---|---|---|---|---|---|---|---|---|
| [ej4_pdf_rag_lider_flashcards.json](ej4_pdf_rag_lider_flashcards.json) | `01_que_es_rag.pdf` (título "RAG") | Lider Tecnico / Arquitecto | Flashcards | gemini-3.5-flash | 0.8437 | false | 5 | 7 tarjetas | exito (documento y salida) |

Es un caso aparte: otro documento, subido como PDF. Muestra la ingestión de un archivo real, no la comparación entre perfiles.

## Cómo leerlos

Todos tienen `status`, `metadatos`, `contenido_adaptado`, `evaluacion_calidad` y `almacenamiento_oci`.

- **Flashcards:** `contenido_adaptado` es una lista de objetos con `pregunta` y `respuesta`.
- **Guía práctica:** `contenido_adaptado` es un objeto con la lista `pasos`; cada paso tiene `titulo` y `detalle`.
- `evaluacion_calidad` trae el puntaje, el umbral y `baja_confianza`. `almacenamiento_oci` indica el bucket, el `objeto_id` y el estado de la subida del documento original y de la salida.

## Notas

- Son salidas reales de una corrida, no se editaron.
- El puntaje mide anclaje temático respecto de la fuente, no veracidad. Ver [docs/fidelidad.md](../fidelidad.md).
- El modelo puede variar entre corridas: ej3 se generó con `gemini-3.5-flash-lite` y el resto con `gemini-3.5-flash`. Ver [docs/fallback.md](../fallback.md).
- Son corridas independientes de las P1 a P4 de la tabla de la sección 6 del README; los puntajes no coinciden porque cada ejecución genera contenido distinto.
