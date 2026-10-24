# Test plan general — NuevaMente (NM-07)

Responsable: Jessica Escobar (QA Engineer). Última actualización: entrega de Semana 1/2.

Convención de estado:
- **Verificado**: hay un test automatizado que lo prueba, y el test pasa (`pytest`).
- **Previsto**: el caso está definido acá y planeado, pero todavía no tiene test
  automatizado (normalmente porque depende de un módulo que aún no está cerrado).

No marcamos nada como "listo" sin un test que lo respalde — ver el análisis de
`decisiones_proyecto.md` del Equipo 38 que motivó esta distinción.

## 1. Ingesta de documentos (NM-03, NM-04)

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| PDF válido, texto extraíble en todas las páginas | Automatizado | Verificado | `tests/test_ingesta.py::TestCargarPdf::test_pdf_valido_extrae_texto_de_todas_las_paginas` |
| PDF corrupto (bytes inválidos) | Automatizado | Verificado | `test_pdf_corrupto_lanza_error_de_ingesta` |
| PDF técnicamente válido pero sin páginas | Automatizado | Verificado | `test_pdf_sin_paginas_lanza_error_de_ingesta` |
| PDF escaneado sin capa de texto (sin OCR) | Automatizado | Verificado | `test_pdf_escaneado_sin_texto_no_rompe_pero_queda_marcado` |
| Markdown válido, se preservan encabezados | Automatizado | Verificado | `TestCargarTexto::test_markdown_valido_preserva_encabezados` |
| Texto plano válido | Automatizado | Verificado | `test_texto_plano_valido` |
| Archivo vacío (0 bytes) | Automatizado | Verificado | `test_archivo_vacio_devuelve_documento_vacio_sin_error` |
| Extensión no soportada (ej. .docx) | Automatizado | Verificado | `test_extension_no_soportada_lanza_error_de_ingesta` |
| Archivo inexistente | Automatizado | Verificado | `test_archivo_inexistente_lanza_error_de_ingesta` (ambos loaders) |
| PDF y Markdown exponen la misma interfaz de salida | Automatizado | Verificado | `test_pdf_y_markdown_devuelven_la_misma_interfaz` |
| Texto con tildes y ñ se lee sin alterar | Automatizado | Verificado | `test_texto_con_tildes_y_enie_se_lee_sin_alterar` |
| Archivo UTF-8 con BOM no deja `\ufeff` en el texto | Automatizado | Verificado | `test_bom_utf8_se_descarta` |
| Markdown con solo encabezados no se considera vacío | Automatizado | Verificado | `test_markdown_con_solo_encabezados_no_se_considera_vacio` |
| Tilde descompuesta (NFD) en `.txt` se normaliza a NFC (1 solo carácter) | Automatizado | Verificado | `tests/test_ingesta.py::TestNormalizacionNFC::test_texto_con_tilde_descompuesta_se_normaliza_a_un_solo_caracter` |
| Tilde descompuesta (NFD) en PDF se normaliza a NFC (1 solo carácter) | Automatizado | Verificado | `tests/test_ingesta.py::TestNormalizacionNFC::test_pdf_con_tilde_descompuesta_se_normaliza_a_un_solo_caracter` (PdfReader simulado) |
| PDF > 50 páginas (performance de extracción) | Manual | Previsto | Probar con un manual real de OCI antes de la demo |

## 2. Pipeline RAG (NM-09, NM-10, NM-11)

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| Texto vacío no genera chunks | Automatizado | Verificado | `tests/test_chunking.py::test_texto_vacio_devuelve_lista_vacia` |
| Texto corto entra en un solo chunk | Automatizado | Verificado | `test_texto_mas_corto_que_el_chunk_devuelve_un_solo_chunk` |
| Texto largo se divide; cada chunk mide a lo sumo `tamano_chunk + overlap` | Automatizado | Verificado | `test_texto_largo_se_divide_en_varios_chunks`, `test_overlap_nunca_agrega_mas_de_overlap_caracteres` |
| El overlap empieza en límite de palabra y se une con un espacio | Automatizado | Verificado | `test_overlap_empieza_en_limite_de_palabra_y_con_separador` |
| Índices de chunk secuenciales e IDs únicos | Automatizado | Verificado | `test_indices_son_secuenciales_desde_cero`, `test_chunk_ids_son_unicos_y_deterministicos` |
| El corte por `". "` no pierde el punto al final del chunk | Automatizado | Verificado | `tests/test_chunking.py::TestPuntoEnCortesPorOracion::test_corte_por_punto_no_pierde_el_punto` |
| Un documento con solo `#` no genera chunks | Automatizado | Verificado | `tests/test_chunking.py::TestChunksSinContenido::test_documento_con_solo_numeral_no_genera_chunks` |
| Chunks sin alfanuméricos se descartan y los índices siguen secuenciales | Automatizado | Verificado | `tests/test_chunking.py::TestChunksSinContenido::test_chunk_sin_alfanumericos_se_descarta_y_los_indices_siguen_secuenciales` |
| Overlap/tamaño inválidos lanzan error | Automatizado | Verificado | `test_overlap_mayor_o_igual_a_tamano_chunk_lanza_error`, `test_tamano_chunk_cero_o_negativo_lanza_error` |
| Lista de chunks vacía no llama a la API de embeddings | Automatizado | Verificado | `tests/test_embeddings.py::test_lista_vacia_no_llama_al_modelo` |
| Un embedding por chunk, mismo orden que la entrada | Automatizado | Verificado | `test_genera_un_vector_por_chunk_en_el_mismo_orden` |
| Falla de la API de embeddings se maneja sin romper el proceso | Automatizado | Verificado | `test_falla_del_modelo_se_normaliza_a_error_de_embeddings` |
| Falta de `GOOGLE_API_KEY` da un error claro | Automatizado | Verificado | `test_sin_api_key_y_sin_modelo_inyectado_falla_con_mensaje_claro` |
| Búsqueda semántica devuelve resultados ordenados por similitud (embedder falso) | Automatizado | Verificado | `tests/test_vector_store.py::TestAgregarYBuscar::test_indexa_y_encuentra_el_chunk_mas_similar_primero`, `test_scores_estan_ordenados_de_mayor_a_menor` |
| Score = similitud coseno, independiente de la magnitud del vector | Automatizado | Verificado | `test_score_es_similitud_coseno_y_no_depende_de_la_magnitud` |
| `top_k` mayor que lo indexado, o limitado por `top_k` | Automatizado | Verificado | `test_top_k_mayor_que_lo_indexado_devuelve_todo_sin_error`, `test_top_k_limita_la_cantidad_de_resultados` |
| Lista de chunks vacía no llama al generador | Automatizado | Verificado | `test_agregar_lista_vacia_devuelve_cero_sin_llamar_al_generador` |
| `top_k` <= 0 lanza error | Automatizado | Verificado | `TestColeccionVaciaYParametrosInvalidos::test_top_k_cero_o_negativo_lanza_error` |
| Reindexar el mismo documento no duplica (upsert) y actualiza el contenido | Automatizado | Verificado | `test_reindexar_el_mismo_documento_no_duplica`, `test_reindexar_con_el_mismo_id_actualiza_el_contenido`, `test_documentos_distintos_con_mismo_indice_no_se_pisan` |
| Calidad de la búsqueda con embeddings reales de Gemini y documentos reales | Manual | Previsto | Requiere `GOOGLE_API_KEY` y datos reales indexados — probar en Semana 3 junto al endpoint completo (NM-23) |
| Colección vacía en vector store no rompe la búsqueda | Automatizado | Verificado | `test_coleccion_vacia_devuelve_lista_vacia_sin_llamar_al_generador` (usa `chromadb.EphemeralClient`, sin disco) |

### Configuración

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| `vector_store_backend` distinto de `chroma` (ej. `faiss`) lanza error de validación | Automatizado | Verificado | `tests/test_config.py::test_vector_store_backend_distinto_de_chroma_lanza_error_de_validacion` |
| `vector_store_backend` por defecto es `chroma` | Automatizado | Verificado | `tests/test_config.py::test_vector_store_backend_por_defecto_es_chroma` |

### Prompts (NM-13)

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| Las 4 combinaciones perfil x formato incluyen rol, instrucción de formato, reglas y ejemplo | Automatizado | Verificado | `tests/test_prompts.py::TestConstruirPromptSistema::test_incluye_rol_formato_reglas_y_ejemplo` |
| Las secciones del prompt aparecen en el orden rol, formato, reglas, ejemplo | Automatizado | Verificado | `test_orden_rol_formato_reglas_ejemplo` |
| Las 4 combinaciones generan prompts distintos | Automatizado | Verificado | `test_las_cuatro_combinaciones_generan_prompts_distintos` |
| Los valores de los enums coinciden con el contrato del endpoint | Automatizado | Verificado | `test_valores_de_los_enums_coinciden_con_el_contrato_del_endpoint` |
| El prompt de usuario incluye título y contenido del documento | Automatizado | Verificado | `TestConstruirPromptUsuario::test_incluye_titulo_y_contenido_del_documento` |
| La guía práctica se pide como objeto `{"pasos": [...]}` (instrucción) | Automatizado | Verificado | `tests/test_prompts.py::TestFormaDeSalidaDeLaGuiaPractica::test_instruccion_pide_un_objeto_con_la_clave_pasos` |
| El ejemplo few-shot de la guía es un objeto con lista de pasos `titulo`/`detalle` | Automatizado | Verificado | `tests/test_prompts.py::TestFormaDeSalidaDeLaGuiaPractica::test_ejemplo_few_shot_es_un_objeto_con_lista_de_pasos` |
| Los ejemplos few-shot de ambos formatos pasan la validación del orquestador | Automatizado | Verificado | `tests/test_prompts.py::TestFormaDeSalidaDeLaGuiaPractica::test_el_ejemplo_few_shot_pasa_la_validacion_del_orquestador` |
| Smoke test contra Gemini real (embeddings `gemini-embedding-001`, chat y orquestación) | Manual | Previsto | `python scripts/smoke_gemini.py` — requiere `GOOGLE_API_KEY`; aún no corrido con clave real |
| Calidad de la salida del LLM con cada prompt | Manual | Previsto | Evaluar a mano con Gemini real antes de la demo |

### Cliente de Gemini (NM-16)

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| Éxito: devuelve el texto del modelo y le pasa ambos prompts | Automatizado | Verificado | `tests/test_gemini_client.py::TestGenerar::test_devuelve_el_texto_del_modelo_y_le_pasa_ambos_prompts` |
| Excepción del proveedor (rate limit, red) se normaliza a `ErrorDeLLM` | Automatizado | Verificado | `tests/test_gemini_client.py::TestGenerar::test_excepcion_del_proveedor_se_normaliza_a_error_de_llm` |
| Respuesta vacía o solo espacios lanza `ErrorDeLLM` | Automatizado | Verificado | `tests/test_gemini_client.py::TestGenerar::test_respuesta_vacia_o_solo_espacios_lanza_error_de_llm` |
| Falta de `GOOGLE_API_KEY` da un error claro | Automatizado | Verificado | `tests/test_gemini_client.py::TestGenerar::test_sin_api_key_y_sin_modelo_inyectado_falla_con_mensaje_claro` |
| Llamada real a Gemini con el modelo `gemini-3.8-flash` | Manual | Previsto | Requiere `GOOGLE_API_KEY`; probar antes de la demo |

### Orquestador (NM-17)

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| Caso feliz con Flashcards | Automatizado | Verificado | `tests/test_orquestador.py::TestCasoFeliz::test_flashcards` |
| Caso feliz con Guía práctica (y tolerancia al envoltorio `pasos`) | Automatizado | Verificado | `tests/test_orquestador.py::TestCasoFeliz::test_guia_practica`, `test_guia_practica_tolera_el_envoltorio_pasos` |
| Documento vacío o sin texto útil lanza `ErrorDeOrquestacion` sin llamar a Gemini | Automatizado | Verificado | `tests/test_orquestador.py::TestDocumentoVacio::test_documento_sin_texto_util_lanza_error_sin_llamar_a_gemini` |
| JSON dentro de fences \`\`\`json | Automatizado | Verificado | `tests/test_orquestador.py::TestParseoDelJson::test_json_con_fences_markdown` |
| JSON inválido con reintento exitoso | Automatizado | Verificado | `test_json_invalido_con_reintento_exitoso` |
| JSON inválido dos veces: error tras un solo reintento | Automatizado | Verificado | `test_json_invalido_dos_veces_lanza_error_tras_un_solo_reintento` |
| Estructura con forma incorrecta | Automatizado | Verificado | `test_estructura_con_forma_incorrecta_lanza_error` |
| Los fragmentos pasan al prompt en el orden del documento | Automatizado | Verificado | `tests/test_orquestador.py::TestRecuperacionYPrompt::test_los_fragmentos_llegan_al_prompt_en_el_orden_del_documento` |
| `top_k` limita y conserva los más relevantes | Automatizado | Verificado | `test_top_k_limita_los_fragmentos_y_se_queda_con_los_mas_relevantes` |
| El prompt de sistema corresponde al perfil y formato | Automatizado | Verificado | `test_prompt_de_sistema_corresponde_al_perfil_y_formato` |
| El filtro por `nombre_archivo` evita mezclar documentos | Automatizado | Verificado | `test_el_filtro_por_nombre_archivo_evita_mezclar_documentos` |
| Reindexar una versión más corta no deja fragmentos viejos | Automatizado | Verificado | `test_reindexar_una_version_mas_corta_no_deja_fragmentos_viejos` |
| Falla de Gemini se propaga como `ErrorDeLLM`, sin reintento | Automatizado | Verificado | `tests/test_orquestador.py::TestFallasDeGemini::test_falla_de_gemini_se_propaga_como_error_de_llm_sin_reintentar` |
| Vector store: filtro por `nombre_archivo`, `top_k` acotado al filtro, índice en metadata | Automatizado | Verificado | `tests/test_vector_store.py::TestFiltroPorNombreArchivo::test_buscar_con_nombre_archivo_solo_devuelve_chunks_de_ese_documento`, `test_sin_filtro_busca_en_toda_la_coleccion`, `test_filtro_por_documento_inexistente_devuelve_lista_vacia_sin_llamar_al_generador`, `test_top_k_se_limita_a_lo_que_matchea_el_filtro`, `test_el_indice_del_chunk_viaja_en_la_metadata` |
| Vector store: `eliminar_documento` borra solo los chunks del documento | Automatizado | Verificado | `tests/test_vector_store.py::TestEliminarDocumento::test_eliminar_documento_borra_solo_sus_chunks` |
| Calidad del contenido generado de punta a punta con Gemini real | Manual | Previsto | Requiere `GOOGLE_API_KEY` y un documento real de OCI |

## 3. Esquema de entrada/salida (NM-06 — Pydantic, de Larissa/Jose)

**Depende de que NM-06 esté cerrado.** Casos previstos, a automatizar en cuanto el
schema exista:

| Caso | Tipo | Estado |
|---|---|---|
| Input válido con todos los campos requeridos | Automatizado | Previsto |
| `perfil_destinatario` fuera del enum permitido | Automatizado | Previsto |
| `formato_salida` fuera del enum permitido | Automatizado | Previsto |
| Campo requerido faltante (ej. `documento_contenido`) | Automatizado | Previsto |
| `documento_contenido` vacío o solo espacios | Automatizado | Previsto |

## 4. OCI Object Storage (NM-05, NM-12, NM-22)

**Depende de que el bucket (NM-05) esté creado.** Casos previstos:

| Caso | Tipo | Estado |
|---|---|---|
| Subida exitosa de un documento al bucket | Manual + automatizado (mock del SDK) | Previsto |
| Falla de conexión a OCI (timeout, sin red) | Automatizado (mock) | Previsto |
| Credenciales inválidas o config faltante | Automatizado (mock) | Previsto |
| Fallback: el pipeline sigue funcionando en local si OCI no está configurado | Manual | Previsto — recomendado para no bloquear el resto del equipo mientras se arma el bucket |

## 5. Manual vs. automatizado — criterio general

- **Automatizado**: cualquier caso que no dependa de un servicio externo real
  (red, credenciales) y que tenga una entrada/salida determinística. Vive en
  `tests/` y corre con `pytest`.
- **Manual**: casos que dependen de un servicio externo configurado (OCI real,
  Gemini real) o de evaluar calidad subjetiva (¿la guía generada es clara?).
  Se prueban a mano antes de cada demo y se documentan acá con capturas o notas
  cuando corresponda.

## Cómo correr los tests automatizados

```bash
pip install -r requirements.txt
pytest -v
```
