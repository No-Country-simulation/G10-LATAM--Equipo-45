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
| Llamada real a Gemini con el modelo `gemini-3.5-flash` y, si hace falta, sus respaldos | Manual | Previsto | Requiere `GOOGLE_API_KEY`; probar antes de la demo |

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

### Verificación de fidelidad (NM-20)

Similitud de embeddings entre el contenido generado y los fragmentos recuperados, sin segundo LLM.
Si el anclaje es bajo se marca `baja_confianza` pero no se bloquea. Todavía no está conectado al
orquestador ni al endpoint. Los tests usan un fake de embeddings por palabras clave (sin red).

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| Coseno: iguales = 1, ortogonales = 0, opuestos = -1, independiente de la magnitud | Automatizado | Verificado | `tests/test_fidelidad.py::TestSimilitudCoseno` |
| Coseno con vector nulo da 0 (sin dividir por cero); dimensiones distintas lanzan `ValueError` | Automatizado | Verificado | `test_vector_nulo_da_cero_sin_dividir_por_cero`, `test_dimensiones_distintas_lanza_value_error` |
| Extracción de unidades: flashcards (solo respuesta) y guía (título + detalle); ítems vacíos se saltean | Automatizado | Verificado | `tests/test_fidelidad.py::TestExtraerUnidades` |
| Unidades parecidas a la fuente dan score alto; unidades distintas dan score bajo | Automatizado | Verificado | `TestScore::test_unidades_parecidas_a_la_fuente_dan_score_alto`, `test_unidades_distintas_a_la_fuente_dan_score_bajo` |
| Score = promedio de las similitudes máximas, acotado a [0, 1]; detalle con índice del fragmento | Automatizado | Verificado | `test_el_score_es_el_promedio_de_las_similitudes_maximas`, `test_el_score_se_acota_a_cero_si_la_similitud_es_negativa`, `test_detalle_indica_unidad_similitud_maxima_e_indice_del_fragmento` |
| Umbral: score igual al umbral no es baja confianza, por debajo sí; default desde `settings.umbral_anclaje` (rango 0-1) | Automatizado | Verificado | `TestUmbral` |
| Sin unidades o sin fragmentos: `baja_confianza=True` con motivo, sin llamar a embeddings | Automatizado | Verificado | `TestCasosBorde::test_sin_unidades_es_baja_confianza_sin_llamar_a_embeddings`, `test_sin_fragmentos_es_baja_confianza_sin_llamar_a_embeddings` |
| Vectores de dimensiones inconsistentes: `baja_confianza=True` con motivo, sin lanzar | Automatizado | Verificado | `test_dimensiones_inconsistentes_dan_baja_confianza_con_motivo` |
| `ErrorDeEmbeddings` sube tal cual (lo decide el backend) | Automatizado | Verificado | `test_error_de_embeddings_sube_tal_cual` |
| Una sola llamada batch para las unidades y otra para los fragmentos | Automatizado | Verificado | `TestBatch::test_una_sola_llamada_por_conjunto` |
| Calibración del umbral con embeddings reales sobre un set golden (6 fieles, 6 infieles; fuente de 2 fragmentos) | Manual | Verificado — `python scripts/calibrar_fidelidad.py` (solo embeddings, requiere `GOOGLE_API_KEY`). Fieles 0.805-0.900; inventados del mismo tema 0.777-0.856; otro tema 0.611-0.661. Umbral `0.72` = punto medio entre 0.661 y 0.777 |
| Límite conocido: el score NO separa fieles de datos inventados sobre el mismo tema (rangos solapados) | Manual | Verificado — el score mide anclaje temático, no veracidad; solo detecta contenido fuera de tema. No hay mitigación automática; requiere revisión humana o un juez distinto |
| Re-calibración del umbral con un documento real y muchos fragmentos | Manual | Previsto | NM-30: correr con un documento real de OCI; el set actual (12 casos, 2 fragmentos) es chico |
| Integración del verificador en `Orquestador.adaptar` / endpoint | Automatizado | Previsto | Se conecta junto con el endpoint (NM-23) |

## 3. API (NM-06 esquemas, NM-18 endpoint, NM-19 errores)

Tests con `fastapi.testclient` y `app.dependency_overrides`: `ServicioDeAdaptacion` real con embeddings por
palabras clave, Chroma en memoria, chat guionado y cliente de OCI falso (sin red ni credenciales).

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| `GET /health` responde `ok` sin tocar servicios externos; 404 con el formato de error | Automatizado | Verificado | `tests/test_api.py::TestHealth` |
| Caso feliz con Flashcards por texto: forma exacta del JSON, metadatos y evaluación de calidad | Automatizado | Verificado | `TestCaminoFeliz::test_flashcards_por_texto_forma_exacta` |
| Caso feliz con Guía práctica por archivo (`{"pasos": [...]}`) y título por defecto | Automatizado | Verificado | `test_guia_practica_por_archivo_forma_exacta`, `test_titulo_por_defecto_en_texto_es_documento` |
| PDF válido | Automatizado | Verificado | `TestCaminoFeliz::test_pdf_valido` |
| Ninguna respuesta (éxito, éxito con fallback local ni error) contiene rutas del servidor ni `ruta_local` | Automatizado | Verificado | `TestSinRutasDelServidor` |
| Se sube el original y el JSON de salida; el JSON subido no contiene su propio `objeto_id` | Automatizado | Verificado | `TestCaminoFeliz::test_sube_el_original_y_el_json_de_salida` |
| OCI caído: `pendiente_oci` reflejado en la respuesta, sin fallar | Automatizado | Verificado | `TestAlmacenamientoYEstado::test_oci_caido_se_refleja_como_pendiente_oci_sin_fallar` |
| El documento se elimina del vector store al terminar (también si falla la generación) | Automatizado | Verificado | `test_el_documento_se_elimina_del_vector_store_al_terminar`, `test_el_documento_se_elimina_del_vector_store_aunque_falle_la_generacion` |
| Dos solicitudes con el mismo nombre usan claves distintas en el vector store | Automatizado | Verificado | `test_dos_solicitudes_con_el_mismo_nombre_usan_claves_distintas` |
| `ErrorDeEmbeddings` en la fidelidad: 200 degradado (`score` null, `baja_confianza`, motivo) | Automatizado | Verificado | `TestFidelidadDegradada` |
| Archivo y texto a la vez, o ninguno: 422 | Automatizado | Verificado | `TestValidacionDeEntrada::test_exactamente_uno_de_archivo_o_texto` |
| Texto en blanco; texto en blanco junto a un archivo | Automatizado | Verificado | `test_texto_en_blanco_cuenta_como_ausente`, `test_texto_en_blanco_junto_a_un_archivo_usa_el_archivo` |
| Perfil o formato fuera del enum / faltante: 422 con el campo indicado y sin eco del valor | Automatizado | Verificado | `test_valor_fuera_del_enum_indica_el_campo`, `test_campo_obligatorio_faltante` |
| Título demasiado largo | Automatizado | Verificado | `test_titulo_demasiado_largo` |
| Extensión no soportada; archivo vacío; no UTF-8 | Automatizado | Verificado | `test_extension_no_soportada`, `test_archivo_vacio`, `test_archivo_no_utf8` |
| PDF corrupto y PDF escaneado sin texto: 422 (el escaneado no sube nada a OCI) | Automatizado | Verificado | `test_pdf_corrupto`, `test_pdf_escaneado_sin_texto` |
| Archivo o texto por encima del límite: 413 | Automatizado | Verificado | `test_archivo_demasiado_grande_es_413`, `test_texto_demasiado_grande_es_413` |
| `ErrorDeLLM` → 503; salida inválida del modelo → 502; `ErrorDeEmbeddings` al indexar → 503 (sin filtrar detalles del proveedor) | Automatizado | Verificado | `TestErroresDelPipeline` |
| `ErrorDeAlmacenamiento` → 500 amable; excepción inesperada → 500 genérico sin stack ni detalles internos | Automatizado | Verificado | `test_error_de_almacenamiento_es_500_amable`, `test_excepcion_inesperada_es_500_generico_sin_detalles` |
| Los enums del schema son los de `prompts.py`; validación del modelo de entrada; forma del error | Automatizado | Verificado | `TestEsquemas` |
| Config del API: `max_upload_mb` y `extensiones_permitidas` | Automatizado | Verificado | `tests/test_config.py::test_limites_del_api_por_defecto`, `test_extensiones_permitidas_se_normalizan`, `test_max_upload_mb_debe_ser_positivo` |
| Tope de reloj (`ejecutar_con_limite`): devuelve, relanza la excepción, `TiempoAgotado` si se cuelga, hilo daemon | Automatizado | Verificado | `tests/test_tiempos_y_logs.py::TestEjecutarConLimite` |
| Gemini colgado → `ErrorDeLLM` (503 en la API); plazo y `retry=None` llegan a la llamada; un 429 falla rápido con 503 | Automatizado | Verificado | `test_tiempos_y_logs.py::TestTimeoutDeGemini` |
| Embeddings colgados → `ErrorDeEmbeddings` (documentos y query; 503 al indexar) | Automatizado | Verificado | `test_tiempos_y_logs.py::TestTimeoutDeEmbeddings` |
| Timeouts de OCI (read/connect) → fallback local; con disco roto, `ErrorDeAlmacenamiento`; el cliente real recibe `timeout=(conexión, lectura)` | Automatizado (fake) | Verificado | `test_tiempos_y_logs.py::TestTimeoutDeOci` |
| Logging: configurado al importar la app, a stdout, formato con hora/nivel/nombre, idempotente, nivel por `LOG_LEVEL` | Automatizado | Verificado | `test_tiempos_y_logs.py::TestLogging` |
| Trazas por paso con duración, orden del pipeline, tipo de excepción al fallar, sin contenido ni nombre del documento | Automatizado | Verificado | `test_tiempos_y_logs.py::TestTrazasPorPaso` |
| Diagnóstico de dependencias reales (Chroma, embedding, OCI, 1 llamada a Gemini) con OK/FALLÓ/TIMEOUT | Manual | Previsto | `python scripts/diagnostico_pasos.py` — requiere `.env` y `~/.oci/config`; gasta 1 unidad de cuota de Gemini |
| Cadena de modelos: el principal responde y no se construye ningún respaldo | Automatizado | Verificado | `tests/test_fallback_modelos.py::TestCadena::test_el_principal_responde_y_no_se_toca_ningun_respaldo` |
| 503 pasa al segundo modelo con backoff; `metadatos.modelo` es el que respondió | Automatizado | Verificado | `TestCadena::test_503_pasa_al_segundo_con_backoff`, `TestMetadatosYLogs::test_metadatos_modelo_es_el_que_respondio` |
| 404 salta de inmediato, sin backoff | Automatizado | Verificado | `TestCadena::test_404_salta_de_inmediato_sin_backoff` |
| 429 → 504 → OK en el tercero | Automatizado | Verificado | `TestCadena::test_429_luego_504_luego_ok` |
| Todos fallan: error con la lista de intentos (sin claves) y el mismo 503 de la API | Automatizado | Verificado | `TestCadena::test_todos_fallan_lista_cada_intento_sin_exponer_claves`, `test_todos_fallan_en_la_api_es_el_503_de_siempre` |
| Credenciales/pedido inválido (también envuelto por LangChain) y bugs propios no prueban otros modelos | Automatizado | Verificado | `TestCadena::test_errores_de_credenciales_no_prueban_otros_modelos`, `test_error_de_credenciales_envuelto_por_langchain_tampoco_cambia_de_modelo`, `test_un_bug_propio_se_propaga_sin_cambiar_de_modelo` |
| Presupuesto total agotado corta con el error de timeout existente; el timeout por llamada pasa al siguiente; el backoff no excede el presupuesto | Automatizado | Verificado | `TestCadena::test_presupuesto_total_agotado_corta_y_usa_el_error_de_timeout_existente`, `test_el_timeout_por_llamada_pasa_al_siguiente_modelo`, `test_el_backoff_no_supera_el_presupuesto_restante` |
| JSON inválido usa el reintento existente con el mismo modelo (y 502 si falla dos veces); respuesta vacía no cambia de modelo | Automatizado | Verificado | `TestMetadatosYLogs::test_json_invalido_*`, `TestCadena::test_respuesta_vacia_no_cambia_de_modelo` |
| Logs `paso=generacion modelo=… intento=… fallo=… pasando_a=…`, `modelo_usado` e intentos en el log final | Automatizado | Verificado | `TestMetadatosYLogs::test_logs_de_cada_intento_y_modelo_usado`, `test_el_ultimo_modelo_que_falla_se_loguea_sin_siguiente` |
| Parseo de `GEMINI_MODEL_FALLBACKS` (espacios, duplicados, vacía, prefijo `models/`), defaults y `GEMINI_BACKOFF_S` | Automatizado | Verificado | `tests/test_fallback_modelos.py::TestConfig` |
| Fallback real contra Gemini (principal caído/404 y respaldo respondiendo) | Manual | Previsto | Requiere `GOOGLE_API_KEY`; gasta cuota |
| Smoke del endpoint con servidor, Gemini y OCI reales (1 solicitud) | Manual | Previsto | `python scripts/smoke_endpoint.py` — requiere servidor levantado y `GOOGLE_API_KEY`; gasta cuota de generación |
| Dos solicitudes concurrentes reales contra el servidor | Manual | Previsto | Verificar que no se pisan en el vector store con Chroma persistente |
| `nicho_sector` y `nivel_detalle` influyen en el contenido | — | Previsto | Hoy solo se devuelven en metadatos; requiere cambios en prompts/orquestador |

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

## 5. Frontend Streamlit (NM-25, NM-26, NM-27)

Sin red ni Streamlit en ejecución: el cliente se prueba con `httpx.MockTransport` y la lógica de formato
son funciones puras. La UI solo tiene un humo con `streamlit.testing.v1.AppTest`.

| Caso | Tipo | Estado | Dónde |
|---|---|---|---|
| Mapeo etiquetas → valores del enum (`PerfilDestinatario`, `FormatoSalida` importados de `app.api.schemas`): si el backend cambia, falla | Automatizado | Verificado | `tests/test_frontend.py::TestMapeoConEnumsDelBackend` |
| Límite de tamaño y extensiones de la UI = los del backend por defecto | Automatizado | Verificado | `TestMapeoConEnumsDelBackend::test_la_validacion_usa_los_mismos_limites_que_el_backend_por_defecto` |
| Cliente: éxito, y envía los valores del enum y el título; archivo como multipart | Automatizado | Verificado | `TestClienteApi::test_exito_*`, `test_envia_archivo_como_multipart` |
| Cliente: 422 muestra mensaje y detalles del formato de error de la API; 413 como validación; 4xx sin ese formato no copia el cuerpo crudo | Automatizado | Verificado | `TestClienteApi::test_422_*`, `test_413_*`, `test_4xx_sin_formato_*` |
| Cliente: 502/503/504 → mensaje claro del modelo; 500 → mensaje de la API o genérico | Automatizado | Verificado | `TestClienteApi::test_errores_del_modelo_*`, `test_500_*` |
| Cliente: timeout y API caída (ConnectError) → `ErrorDeApi` sin texto técnico; 200 con cuerpo inválido controlado | Automatizado | Verificado | `TestClienteApi::test_timeout`, `test_api_caida`, `test_200_con_cuerpo_invalido_*` |
| Timeout por defecto del cliente (150 s) supera el peor caso del backend (`GEMINI_TIMEOUT_TOTAL_S`) | Automatizado | Verificado | `TestClienteApi::test_el_timeout_por_defecto_supera_el_peor_caso_del_backend` |
| Validación previa: texto vacío, archivo vacío, extensión inválida, tamaño (bytes UTF-8) | Automatizado | Verificado | `TestValidarEntrada` |
| Formateo: flashcards, guía, contenido malformado, score `null` → "No disponible", fecha UTC | Automatizado | Verificado | `TestFormateo` |
| El estado de OCI no expone bucket ni `objeto_id`; JSON con tildes; nombre de descarga seguro | Automatizado | Verificado | `TestFormateo::test_almacenamiento_*`, `test_json_formateado_*`, `test_nombre_de_descarga_es_seguro` |
| La app arranca (AppTest) con la API mockeada, sin llamarla al cargar | Automatizado | Verificado | `test_la_app_arranca_con_la_api_mockeada` |
| Helpers visuales: porcentaje de la barra (0, 0.72, 1, null, fuera de rango), píldora de confianza con texto, contador de caracteres, etiqueta del enum | Automatizado | Verificado | `TestHelpersVisuales` |
| Fecha en `America/Asuncion`, en UTC y con zona inválida (cae a UTC y lo dice en la etiqueta); zona por defecto de la config | Automatizado | Verificado | `TestHelpersVisuales::test_fecha_*`, `test_la_zona_por_defecto_de_la_config_es_asuncion` |
| Tarjeta de score: normal, baja confianza (aviso), score `null` sin barra ni romper; el contenido del modelo se escapa en el HTML; encabezado sin "Maqueta" | Automatizado | Verificado | `TestComponentes` |
| Humo AppTest: estado vacío, resultado de flashcards, guía con score `null` y baja confianza, tarjeta de error con Reintentar (los de resultado precargan el estado: AppTest 1.40 no soporta una segunda corrida con el `st.segmented_control` de la vista) | Automatizado | Verificado | `test_la_app_arranca_en_estado_vacio`, `test_la_app_muestra_*` |
| CSS del uploader en español con el límite real (`MAX_UPLOAD_MB`, extensiones), sanitizado; tarjetas con `box-sizing: border-box` | Automatizado | Verificado | `TestEstilos` |
| Sin desborde en las tarjetas y textos del uploader en español en el navegador (selectores ligados al DOM de Streamlit 1.40.2) | Manual | Previsto | Revisión visual |
| Perfil y formato elegidos en los selectbox llegan a la API con los valores exactos del enum (cliente mockeado) | Automatizado | Verificado | `test_elegir_perfil_y_formato_envia_los_valores_del_enum_a_la_api` |
| Encabezado con el título exacto "NuevaMente - Adaptación de contenido educativo" y su subtítulo; marca de umbral sobre la barra (posición con los mismos límites que el score), texto "Umbral mínimo", sin marca si el umbral es null | Automatizado | Verificado | `TestComponentes::test_el_encabezado_no_trae_la_pildora_maqueta`, `TestMarcaDeUmbral` |
| CSS: tarjeta de score y tarjetas internas sin desborde (`box-sizing`, `flex-wrap`, `overflow-wrap`), JSON con scroll horizontal, contador `InputInstructions` oculto, foco solo en el contenedor del input/textarea | Automatizado | Verificado | `TestEstilos` |
| Sin desborde de la tarjeta de score ni de textos largos; marca del umbral bien ubicada; sin doble borde ni contador superpuesto en el campo Título | Manual | Previsto | Revisión visual |
| Flujo completo en el navegador (cargar, generar, ver resultado, descargar JSON, reintentar tras un error, botón deshabilitado mientras genera) | Manual | Previsto | `uvicorn` + `streamlit run frontend/app.py` con Gemini real; gasta cuota |
| Subir archivo (PDF/MD/TXT) desde la UI | Manual | Previsto | `AppTest` de esta versión de Streamlit no soporta `file_uploader` |
| Estética contra el prototipo: colores, tipografías (Poppins / JetBrains Mono), selectores segmentados, barra de score, foco visible (outline magenta), apilado en pantallas angostas, CSS enganchado a `data-testid` de Streamlit 1.40.2 | Manual | Previsto | Revisión visual en el navegador; no se pudo verificar en esta entrega |

## 6. Manual vs. automatizado — criterio general

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
