# G10-LATAM--Equipo-45
Sistema inteligente de adaptación y generación de contenido educativo con RAG y Gemini — Hackathon ONE G10-LATAM.
# NuevaMente

Sistema inteligente que ingiere documentación técnica (PDF, Markdown o texto) y la transforma automáticamente en contenido educativo personalizado, usando RAG (Retrieval-Augmented Generation) para anclar el contenido en las fuentes originales y evitar alucinaciones.

Construido para el Hackathon ONE G10-LATAM (Oracle Next Education & Alura).

## Qué resuelve

Adaptar documentación técnica densa a distintos públicos —desde alguien en transición de carrera hasta un líder técnico— es un proceso manual que consume semanas de trabajo de especialistas instruccionales. NuevaMente automatiza ese flujo: recibe un documento técnico, un perfil de destinatario y un formato pedagógico de salida, y devuelve contenido educativo estructurado y fiel a la fuente original.

## Arquitectura

```mermaid
flowchart LR
  A[Usuario] --> B[Frontend<br/>Streamlit o Gradio]
  B --> C[Backend/API<br/>FastAPI o Flask]
  C --> D[Ingesta de documentos<br/>PyPDF, Markdown, texto]
  D --> E[Pipeline RAG<br/>chunking, embeddings, vector store]
  C --> F[Orquestacion LLM<br/>LangChain + Gemini]
  E --> F
  F --> G[Verificacion de fidelidad]
  G --> C
  C --> H[OCI Object Storage<br/>Always Free]
```

## Stack

| Herramienta | Versión sugerida | Motivo |
|---|---|---|
| Python | 3.10 o superior (probado con 3.11) | El código usa sintaxis de tipos `X \| Y` (PEP 604), disponible desde 3.10 |
| FastAPI | 0.115.x | HTTP server, async-first, integra bien con Pydantic |
| Pydantic | 2.x | Validación tipada de entrada/salida del endpoint |
| LangChain | 0.3.x | Orquestación del pipeline RAG y de prompts |
| ChromaDB | última estable | Vector store para embeddings (FAISS descartado hasta que NM-02 lo confirme) |
| langchain-google-genai | última estable | LLM y embeddings de Google Gemini |
| Streamlit o Gradio | última estable | Interfaz interactiva de carga y visualización |
| oci (OCI SDK for Python) | última estable | Persistencia en OCI Object Storage, capa Always Free |
| PyPDF | última estable | Extracción de texto desde archivos PDF |

## Quickstart

```bash
# 1. Clonar y crear entorno
git clone https://github.com/<owner>/<repo>.git
cd <repo>
python3 -m venv .venv      # Python 3.10 o superior
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env — mínimo requerido: GOOGLE_API_KEY, OCI_* (config del bucket)

# 3. Verificar que todo funciona
pytest -v
```

> **Requisito:** Python 3.10 o superior. Hoy se pueden instalar las dependencias, correr `pytest` y levantar la API (ver sección **API**).

## Configurar OCI Object Storage

Cada integrante configura sus credenciales en su propia máquina. Nada de esto se sube al repo.

1. **Crear el bucket** (consola de OCI → Storage → Buckets): nombre `nuevamente-documentos`, tier Standard, acceso privado. Anotá el *namespace* que muestra la consola en el detalle del bucket.
2. **Permisos**: una política IAM que le dé al grupo `nuevamente-backend` acceso a los objetos del bucket, y tu usuario dentro de ese grupo.
3. **Generar la API key** (Perfil → tu usuario → API keys → Add API key → Generate API key pair). Descargá la clave privada (`.pem`), guardala en `~/.oci/` y restringí permisos: `chmod 600 ~/.oci/<tu_clave>.pem`. La consola te muestra un bloque de configuración: copialo.
4. **Crear `~/.oci/config`** pegando ese bloque y ajustando `key_file` a la ruta real del `.pem`:

   ```ini
   [DEFAULT]
   user=ocid1.user.oc1..<tu_ocid>
   fingerprint=<fingerprint_de_tu_api_key>
   tenancy=ocid1.tenancy.oc1..<tu_ocid>
   region=<tu_region>
   key_file=~/.oci/<tu_clave>.pem
   ```

5. **Completar las variables en el `.env`**: `OCI_BUCKET_NAME`, `OCI_NAMESPACE`, `OCI_REGION` y, si usás otro perfil que no sea `[DEFAULT]`, `OCI_CONFIG_PROFILE`.
6. **Verificar con el smoke test** (sube, descarga, lista y borra un objeto `smoke/<timestamp>.txt`):

   ```bash
   python scripts/smoke_oci.py
   ```

   Sale con código 0 si todo anduvo, 1 si falló algún paso (imprime la causa probable: 401 credenciales, 403 política IAM, 404 bucket o namespace) y 2 si falta configuración.

**Fallback a disco local.** Si OCI no está configurado (variables `OCI_*` vacías o sin `~/.oci/config`) o la subida falla (401/403/404, red, timeout), `Almacenamiento` guarda el archivo en `ALMACENAMIENTO_LOCAL_PATH` (por defecto `./data/almacenamiento_local`, ignorada por git) con el mismo `objeto_id` que habría tenido en el bucket, registra un warning con la causa y devuelve `status_upload: "pendiente_oci"`. El pipeline sigue funcionando sin bucket; si también falla el disco, se lanza `ErrorDeAlmacenamiento`. Todavía no existe el script que sube a OCI lo que quedó pendiente.

> **Seguridad:** `~/.oci/` y los archivos `.pem` viven fuera del repo y nunca se commitean (`.gitignore` ya ignora `.oci/` y `*.pem`). Nunca pegues el contenido de la clave privada en un chat, issue o commit.
>
> **macOS:** no abras el `.pem` con doble clic. Keychain Access lo interpreta como un certificado y lo agrega al llavero del sistema por error. Si necesitás ver su contenido, usá la terminal (`cat`) o un editor de texto.

## API

Backend FastAPI (NM-06, NM-18, NM-19). Los endpoints son funciones síncronas porque las librerías del pipeline (Chroma, SDK de OCI, Gemini) son bloqueantes.

```bash
uvicorn app.api.main:app --reload     # http://127.0.0.1:8000  (documentación interactiva en /docs)
```

Importar la app no requiere claves ni red: Gemini, Chroma y OCI se inicializan en la primera solicitud real. Con `OCI_*` sin configurar, los archivos se guardan en disco y la respuesta informa `pendiente_oci`.

### Endpoints

- `GET /health` → `{"status": "ok"}` (no toca servicios externos).
- `POST /api/v1/adaptar` (`multipart/form-data`):

| Campo | Obligatorio | Descripción |
|---|---|---|
| `archivo` | uno de los dos | `.pdf`, `.md` o `.txt` (límite `MAX_UPLOAD_MB`, 10 por defecto) |
| `documento_contenido` | uno de los dos | texto del documento; no combinar con `archivo` |
| `perfil_destinatario` | sí | `Principiante` o `Lider Tecnico / Arquitecto` |
| `formato_salida` | sí | `Flashcards` o `Guia Practica Paso a Paso` |
| `documento_titulo` | no | máx. 200 caracteres; por defecto el nombre del archivo o `documento` |
| `nicho_sector`, `nivel_detalle` | no | se aceptan y se devuelven en `metadatos`, pero **hoy no influyen en el contenido generado** |

```bash
# Con archivo
curl -X POST http://127.0.0.1:8000/api/v1/adaptar \
  -F "archivo=@manual.pdf" \
  -F "perfil_destinatario=Principiante" \
  -F "formato_salida=Flashcards"

# Con texto
curl -X POST http://127.0.0.1:8000/api/v1/adaptar \
  -F "documento_contenido=Una VCN es una red privada dentro de OCI..." \
  -F "documento_titulo=Introducción a las VCN" \
  -F "perfil_destinatario=Lider Tecnico / Arquitecto" \
  -F "formato_salida=Guia Practica Paso a Paso"
```

### Respuesta de éxito (200)

```json
{
  "status": "ok",
  "metadatos": {
    "documento_titulo": "Introducción a las VCN", "perfil_destinatario": "Principiante",
    "formato_salida": "Flashcards", "nombre_archivo": "manual.pdf", "fragmentos_usados": 3,
    "nicho_sector": null, "nivel_detalle": null,
    "fecha_generacion": "2026-10-24T15:30:00Z", "modelo": "gemini-3.8-flash"
  },
  "contenido_adaptado": [{"pregunta": "¿Qué es una VCN?", "respuesta": "..."}],
  "evaluacion_calidad": {
    "anclaje_fuente_score": 0.83, "baja_confianza": false, "umbral": 0.72,
    "motivo": null, "claridad_pedagogica": null
  },
  "almacenamiento_oci": {
    "documento_original": {"bucket": "nuevamente-documentos", "objeto_id": "documentos/...", "status_upload": "exito"},
    "salida_json": {"bucket": "nuevamente-documentos", "objeto_id": "salidas/...", "status_upload": "exito"}
  }
}
```

- Para `Guia Practica Paso a Paso`, `contenido_adaptado` es `{"pasos": [{"titulo": "...", "detalle": "..."}]}`.
- `anclaje_fuente_score` mide **anclaje temático** a los fragmentos recuperados, **no veracidad**: detecta contenido fuera de tema, pero un dato inventado sobre el mismo tema puede puntuar alto. Una `baja_confianza: true` es una advertencia, no bloquea la respuesta. Si no se pudo verificar, `anclaje_fuente_score` es `null` y `motivo` lo explica.
- `claridad_pedagogica` siempre es `null` (no está implementada).
- `status_upload` puede ser `exito`, `pendiente_oci` (guardado en disco, ver más arriba) o `error`; una caída de OCI no hace fallar la solicitud. La respuesta nunca incluye rutas del servidor (la ruta del fallback local solo se registra en el log).

### Respuesta de error

Todos los errores tienen la misma forma, con mensajes en español y sin detalles internos (esos van al log):

```json
{
  "status": "error",
  "codigo": "entrada_invalida",
  "mensaje": "Revisá los datos enviados: hay campos con problemas.",
  "detalles": [{"campo": "perfil_destinatario", "problema": "Valor no permitido. Valores válidos: ..."}]
}
```

| HTTP | `codigo` | Cuándo |
|---|---|---|
| 422 | `entrada_invalida`, `documento_ilegible`, `documento_sin_texto` | campo inválido o faltante, ni/ambos archivo y texto, extensión no soportada, archivo vacío, PDF corrupto o escaneado sin texto |
| 413 | `documento_demasiado_grande` | el archivo o el texto supera `MAX_UPLOAD_MB` |
| 502 | `respuesta_invalida_del_modelo` | Gemini no devolvió un JSON válido ni tras el reintento |
| 503 | `servicio_no_disponible` | falla de Gemini (generación o embeddings): cuota, red, clave |
| 500 | `error_interno` | fallo de almacenamiento o cualquier error inesperado |

Smoke test manual (una sola solicitud real, gasta cuota de Gemini): `python scripts/smoke_endpoint.py`.

## Próximamente (aún no implementado)

Estos comandos apuntan a archivos que todavía no existen en el repo (`frontend/app.py`, `scripts/ingest.py`):

```bash
streamlit run frontend/app.py     # interfaz Streamlit
python scripts/ingest.py          # CLI de ingesta de docs/
```

## Contrato del endpoint principal

El contrato vigente es el de la sección **API** (`POST /api/v1/adaptar`, definido en `app/api/schemas.py`). Los valores de `perfil_destinatario` y `formato_salida` están limitados a los definidos en `app/llm/prompts.py`, no aceptan texto libre.

## Checklist del MVP

- [ ] Ingesta funcional de documentos técnicos (PDF, Markdown o texto)
- [ ] Pipeline de RAG con chunking, embeddings y búsqueda vectorial
- [ ] Orquestación con Gemini vía LangChain
- [ ] Adaptación funcionando para 2 perfiles y 2 formatos distintos
- [ ] Salida estructurada en JSON + interfaz interactiva (Streamlit o Gradio)
- [ ] Integración activa con OCI Object Storage, capa Always Free
- [ ] Mínimo 3 ejemplos de ejecución con documentos reales o simulados
- [ ] Documentación completa con diagrama de arquitectura

## Actualizar documentos de referencia

Pendiente: depende de `scripts/ingest.py` y del backend (ver "Próximamente (aún no implementado)").

## Despliegue

- **Frontend/Backend:** Streamlit Community Cloud, Render o una instancia OCI Compute (Always Free) si el equipo decide priorizarlo en la semana 4.
- **Almacenamiento:** OCI Object Storage, capa Always Free, es obligatorio independientemente de dónde corra la app — así lo exige el checklist del hackathon.

## Estructura del proyecto

```
nuevamente/
├── app/
│   ├── api/                      # Backend FastAPI (main, schemas, errores, servicio, dependencias)
│   ├── config.py                 # Settings (pydantic-settings + .env)
│   ├── ingesta/
│   │   ├── pdf_loader.py         # Extracción de texto desde PDF (PyPDF)
│   │   └── text_loader.py        # Lectura de Markdown/texto plano
│   ├── rag/
│   │   ├── chunking.py           # Segmentación del texto
│   │   ├── embeddings.py         # Generación de embeddings
│   │   └── vector_store.py       # Abstracción Chroma/FAISS
│   ├── llm/
│   │   ├── prompts.py            # Prompts por perfil y formato
│   │   ├── orquestacion.py       # Cadena LangChain + Gemini
│   │   └── verificacion.py       # Chequeo de fidelidad y metadatos
│   └── oci/
│       └── storage.py            # Subida/lectura en OCI Object Storage
├── frontend/
│   └── app.py                    # Interfaz Streamlit o Gradio
├── docs/                         # Documentos fuente para indexar
├── scripts/
│   └── ingest.py                 # CLI de ingesta
├── tests/                        # Test plan y casos automatizados (QA)
├── requirements.txt
└── .env.example
```

## Equipo — G10-LATAM-equipo 45

| Nombre | Rol |
|---|---|
| Jessica Escobar | QA Engineer |
| Larissa Cabrera | Full Stack Developer |
