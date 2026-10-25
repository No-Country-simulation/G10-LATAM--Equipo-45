# Evaluación de fidelidad

Implementada en `app/llm/fidelidad.py` (`VerificadorDeFidelidad`) y conectada al flujo en el paso `fidelidad` de `app/api/servicio.py`. Responde una pregunta acotada: **¿lo generado se parece a los fragmentos de la fuente que se recuperaron?**

No usa un segundo LLM como juez: usa embeddings, así que no consume cuota de generación, es determinístico y hace dos llamadas batch de embeddings por respuesta (una para las unidades generadas y otra para los fragmentos).

## Cómo se calcula

1. **Unidades.** Se extrae el texto que se compara de cada ítem generado:
   - Flashcards: solo la **respuesta** (la pregunta es una fórmula genérica que se parece a cualquier fragmento del tema y subiría el puntaje de una respuesta inventada).
   - Guía práctica: `"<título>. <detalle>"` de cada paso.
   - Los ítems con el campo vacío se saltean.
2. **Embeddings.** Se embeben las unidades y los fragmentos recuperados (los `TOP_K_RECUPERACION` = 8 del paso `busqueda`) con `gemini-embedding-001`, usando el mismo método para ambos lados.
3. **Máximo por unidad.** Para cada unidad se calcula la similitud coseno contra todos los fragmentos y se toma la **más alta**.
4. **Puntaje.** `anclaje_fuente_score` = **media** de esos máximos, acotada a [0, 1].
5. **Umbral.** `baja_confianza = puntaje < umbral`. El umbral es `UMBRAL_ANCLAJE`, **0.72** por defecto. Un puntaje igual al umbral no es baja confianza.

Un `baja_confianza: true` es una advertencia: **no bloquea** la respuesta. Qué hacer con ella lo decide quien consume la API; la UI la muestra como aviso.

## Casos en que no se puede medir

El verificador no lanza error; devuelve `baja_confianza: true` y un `motivo`:

- Sin unidades de contenido, o sin fragmentos contra los cuales comparar.
- Vectores de dimensiones inconsistentes.
- Si falla la API de embeddings (`ErrorDeEmbeddings`), el servicio degrada la evaluación: `anclaje_fuente_score: null`, `baja_confianza: true` y `motivo: "no se pudo verificar la fidelidad"`. La respuesta sigue siendo 200.

## Qué mide

**Anclaje temático**: si cada pieza generada se parece semánticamente a algún fragmento de la fuente. Detecta contenido que se va de tema o que no se parece a nada de lo recuperado.

## Qué NO mide

- **Veracidad.** Un dato inventado sobre el mismo tema puede seguir pareciéndose a la fuente y puntuar alto.
- **Contradicciones.** Dos frases con significado opuesto pero vocabulario casi idéntico quedan muy cerca en el espacio de embeddings.
- **Contexto agregado por el modelo.** Algo razonable pero ausente de la fuente puede puntuar bien.
- **Claridad pedagógica.** El campo `claridad_pedagogica` existe en la respuesta pero siempre es `null`.

## Evidencia de la calibración

`python scripts/calibrar_fidelidad.py` corre el verificador con embeddings reales sobre 12 casos fijos (6 fieles, 3 inventados sobre el mismo tema, 3 de otro tema) y una fuente de 2 fragmentos. Rangos registrados en `app/llm/fidelidad.py` y `app/config.py`:

| Grupo | Puntaje |
|---|---|
| Fieles | 0.805 – 0.900 |
| Inventados, mismo tema | 0.777 – 0.856 |
| Otro tema | 0.611 – 0.661 |

Los rangos de fieles e inventados del mismo tema **se solapan**: ningún umbral los separa. El 0.72 es un punto medio entre "otro tema" (≤ 0.661) e "inventados del mismo tema" (≥ 0.777): separa lo fuera de tema, no lo inventado. El set es chico; el plan de pruebas deja pendiente recalibrar con un documento real y muchos fragmentos.

## Ejemplo de limitación

Si la fuente dice que un paso es **ideal** (recomendable) y el modelo lo afirma como **obligatorio**, la frase generada usa casi el mismo vocabulario y habla del mismo tema, así que su similitud con el fragmento sigue siendo alta y el puntaje no baja. El cambio de matiz no se detecta. (Caso ilustrativo reportado por el equipo para explicar este límite; no forma parte de la suite de tests ni del set de calibración, cuyos casos "inventados" son los que figuran en `scripts/calibrar_fidelidad.py`.)

Por eso el puntaje es una señal para priorizar la revisión humana, no una garantía de que el contenido sea correcto.

## En la interfaz

La tarjeta de puntaje muestra el valor, la marca del umbral y la píldora "Confianza normal" / "Baja confianza". El desplegable "¿Por qué esta nota?" explica el cálculo. El slider de umbral (0.50 a 0.95) solo cambia cómo se lee el resultado en pantalla: no vuelve a generar, no llama a la API y no modifica la píldora ni el aviso, que reflejan lo que devolvió la API.
