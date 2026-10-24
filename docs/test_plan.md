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

Los casos automatizados usan un cliente falso del SDK (sin red ni credenciales); el bucket real
(NM-05) se valida aparte con el smoke test manual.

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| Subida exitosa de un documento: `status_upload="exito"`, `objeto_id` y bucket correctos | Automatizado (fake del SDK) | Verificado | `tests/test_almacenamiento.py::TestSubidaExitosa::test_sube_a_oci_con_status_exito_y_objeto_id_correcto` |
| Falla de conexión a OCI (timeout, sin red): fallback local, `pendiente_oci` | Automatizado (fake) | Verificado | `tests/test_almacenamiento.py::TestFallbackALocal::test_error_de_red_cae_a_local` |
| Credenciales inválidas o sin permisos (ServiceError 401, 403, 404): fallback local | Automatizado (fake) | Verificado | `tests/test_almacenamiento.py::TestFallbackALocal::test_service_error_cae_a_local` |
| Config faltante (variables vacías o sin `~/.oci/config`): fallback local | Automatizado | Verificado | `test_oci_sin_configurar_guarda_en_local_como_pendiente_oci`, `test_sin_cliente_inyectado_y_sin_config_de_oci_cae_a_local` |
| Falla OCI y falla el disco: `ErrorDeAlmacenamiento` | Automatizado | Verificado | `test_falla_oci_y_falla_el_disco_lanza_error_de_almacenamiento` |
| Nombres con `../` o ruta absoluta no escapan (OCI ni disco) | Automatizado | Verificado | `TestSanitizacionDeNombres::test_sanitizar_nombre`, `test_nombre_con_traversal_no_escapa_de_la_carpeta_local`, `test_nombre_con_ruta_absoluta_no_llega_a_la_clave_de_oci` |
| Subida del JSON generado (dict y str) a `salidas/` (NM-22) | Automatizado | Verificado | `TestSubirJson::test_dict_se_serializa_con_tildes_legibles_y_prefijo_salidas`, `test_str_se_sube_tal_cual`, `test_json_con_oci_caido_cae_a_local` |
| Descarga desde OCI, desde la copia local y rechazo de `objeto_id` malicioso | Automatizado | Verificado | `TestDescargar::test_descarga_desde_oci`, `test_descarga_la_copia_local_si_el_objeto_quedo_pendiente`, `test_objeto_inexistente_lanza_error_de_almacenamiento`, `test_objeto_id_malicioso_se_rechaza` |
| `ingerir_y_subir`: PDF válido sube el original | Automatizado | Verificado | `tests/test_subida.py::test_pdf_valido_se_ingiere_y_se_sube_el_original` |
| `ingerir_y_subir`: PDF corrupto o extensión no soportada no sube | Automatizado | Verificado | `tests/test_subida.py::test_pdf_corrupto_lanza_error_de_ingesta_y_no_sube`, `test_extension_no_soportada_no_sube` |
| `ingerir_y_subir`: PDF escaneado sin texto no sube | Automatizado | Verificado | `tests/test_subida.py::test_pdf_escaneado_sin_texto_no_sube` |
| Subida real de un documento al bucket desde el pipeline | Manual | Previsto | Probar con credenciales reales antes de la demo |
| Script de reconciliación (subir lo `pendiente_oci`) | — | Previsto | Deuda: no implementado todavía |
| Smoke test contra el bucket real (NM-05): validar config, subir, descargar y comparar, listar y borrar `smoke/<timestamp>.txt` | Manual | Verificado — `python scripts/smoke_oci.py`, corrido el 2026-10-20 contra el bucket `nuevamente-documentos`: TODO OK (subida, descarga, listado y borrado). Requiere bucket, política IAM y `~/.oci/config` |

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
