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

> **Requisito:** Python 3.10 o superior. Hoy lo que funciona es instalar las dependencias y correr `pytest`.

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

## Próximamente (aún no implementado)

Estos comandos apuntan a archivos que todavía no existen en el repo (`app/main.py`, `frontend/app.py`, `scripts/ingest.py`):

```bash
uvicorn app.main:app --reload     # backend FastAPI (uvicorn es el servidor ASGI que ejecuta la app)
streamlit run frontend/app.py     # interfaz Streamlit
python scripts/ingest.py          # CLI de ingesta de docs/
```

## Contrato del endpoint principal

```python
POST /adaptar-contenido

# Entrada
{
  "documento_titulo": "Introduccion a la Arquitectura de Redes VCN en OCI",
  "documento_contenido": "...",
  "perfil_destinatario": "Principiante",       # o "Lider Tecnico / Arquitecto"
  "formato_salida": "Flashcards",              # o "Guia Practica Paso a Paso"
  "nicho_sector": "General",
  "nivel_detalle": "Didactico"
}

# Salida
{
  "status": "exito",
  "metadatos": { "perfil_aplicado": "...", "formato_generado": "...", "conceptos_clave": [...] },
  "contenido_adaptado": { ... },
  "evaluacion_calidad": { "anclaje_fuente_score": 0.0, "claridad_pedagogica": "..." },
  "almacenamiento_oci": { "bucket": "...", "objeto_id": "...", "status_upload": "..." }
}
```

`perfil_destinatario` y `formato_salida` están limitados a los valores definidos por el equipo (ver `NM-06` en el tablero de tareas), no aceptan texto libre.

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
│   ├── main.py                   # Entry point del backend FastAPI
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
