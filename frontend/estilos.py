"""
Estilos de la interfaz: todo el CSS vive acá y se inyecta con una sola función.

Las clases `nm-*` las usa frontend/componentes.py; las tarjetas de Streamlit se enganchan por la clase
`st-key-<key>` que genera `st.container(key=...)` (claves `nm-card-*` para tarjetas, `nm-item-*` para las internas).
Poppins y JetBrains Mono se piden a Google Fonts; si no cargan, quedan system-ui y monospace.
"""

import re

import streamlit as st

from frontend.config import cargar_config

CSS_BASE = """
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Poppins:wght@400;500;600;700&display=swap');

:root {
  --nm-fondo: #F5F2F8;
  --nm-texto: #1A0F24;
  --nm-texto-2: #4F4560;
  --nm-texto-3: #3A2F4A;
  --nm-borde: #DAD3E2;
  --nm-borde-campo: #B8AEC6;
  --nm-campo: #FCFBFD;
  --nm-violeta: #5D0F85;
  --nm-magenta: #CA00CA;
  --nm-lima: #DDDD37;
  --nm-barra: #E8DCF0;
  --nm-fuente: 'Poppins', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --nm-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
}

/* --- Tipografía (los span no se tocan: los íconos de Streamlit son una fuente de glifos) --- */
.stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp li, .stApp label,
.stApp button, .stApp input, .stApp textarea, .stApp summary, .stApp a {
  font-family: var(--nm-fuente);
}
.stApp { background: var(--nm-fondo); color: var(--nm-texto); }
.nm-mono { font-family: var(--nm-mono) !important; }
.block-container { padding-top: 1.5rem; max-width: 1280px; }
header[data-testid="stHeader"] { background: transparent; }

/* --- Encabezado --- */
.nm-encabezado {
  background: var(--nm-texto); border-radius: 16px; padding: 28px 32px;
  border-bottom: 6px solid var(--nm-magenta); margin-bottom: 8px;
}
.stApp .nm-encabezado h1 {
  color: #FFFFFF; font-weight: 700; font-size: 32px; line-height: 1.25; margin: 0; padding: 0;
}
.stApp .nm-encabezado-sub { color: #E8DCF0; font-weight: 400; font-size: 16px; line-height: 1.5; margin: 8px 0 0 0; }

/* --- Tarjetas --- */
[class*="st-key-nm-card"] {
  background: #FFFFFF; border: 1px solid var(--nm-borde); border-radius: 14px; padding: 20px;
}
[class*="st-key-nm-item"] {
  background: var(--nm-campo); border: 1px solid var(--nm-borde); border-radius: 12px; padding: 16px;
}
[class*="st-key-nm-item"] [data-testid="stMarkdownContainer"] p {
  font-size: 14px; line-height: 1.6; color: var(--nm-texto-3);
}
.nm-titulo-tarjeta { font-weight: 600; font-size: 15px; color: var(--nm-texto); margin: 0 0 4px 0; }
.nm-titulo-contenido { font-weight: 600; font-size: 17px; color: var(--nm-texto); margin: 0; padding-top: 8px; }
.nm-chip-ok {
  display: inline-block; white-space: nowrap; margin-left: 6px; padding: 2px 10px; border-radius: 999px; vertical-align: middle;
  background: #F4F4C6; color: #3F3F00; font-size: 12px; font-weight: 600; line-height: 1.5;
}
.nm-contador { font-size: 13px; color: var(--nm-texto-2); margin: 2px 0 0 0; }
.nm-etiqueta {
  font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--nm-violeta); margin-bottom: 4px;
}
.nm-pregunta { font-size: 16px; font-weight: 600; color: var(--nm-texto); margin-bottom: 8px; }

/* --- Etiquetas de los campos --- */
[data-testid="stWidgetLabel"] p { font-size: 13px; font-weight: 500; color: var(--nm-texto-2); }

/* --- Campos de texto --- */
div[data-baseweb="textarea"], div[data-baseweb="input"], div[data-baseweb="base-input"] {
  background: var(--nm-campo) !important; border-radius: 10px !important;
}
div[data-baseweb="textarea"], div[data-baseweb="input"] { border: 1px solid var(--nm-borde-campo) !important; }
.stApp textarea, .stApp input[type="text"] { background: var(--nm-campo); color: var(--nm-texto); }
.stApp input[type="text"]:not([data-baseweb="select"] input) { min-height: 44px; }
[data-testid="stFileUploaderDropzone"] {
  background: var(--nm-campo); border: 1px dashed var(--nm-borde-campo); border-radius: 10px;
}

/* --- Selectbox (perfil, formato): igual que el resto de los campos --- */
[data-testid="stSelectbox"] { width: 100%; max-width: 100%; box-sizing: border-box; }
[data-testid="stSelectbox"] div[data-baseweb="select"] { width: 100%; max-width: 100%; box-sizing: border-box; }
[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
  background: var(--nm-campo); border: 1px solid var(--nm-borde-campo); border-radius: 10px;
  min-height: 44px; box-sizing: border-box; color: var(--nm-texto);
}
[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within {
  border-color: var(--nm-magenta); outline: 3px solid var(--nm-magenta); outline-offset: 2px;
}
[data-testid="stSelectbox"] div[data-baseweb="select"] div, [data-testid="stSelectbox"] div[data-baseweb="select"] input {
  color: var(--nm-texto); font-family: var(--nm-fuente); font-size: 14px;
}
/* El menú desplegado se renderiza en un portal fuera de .stApp: no se puede acotar por esa clase. */
div[data-baseweb="popover"] div[data-baseweb="menu"], div[data-baseweb="popover"] ul[role="listbox"] { background: #FFFFFF; }
div[data-baseweb="popover"] li[role="option"] {
  min-height: 44px; color: var(--nm-texto); background: #FFFFFF; font-family: var(--nm-fuente); font-size: 14px;
}
div[data-baseweb="popover"] li[role="option"]:hover, div[data-baseweb="popover"] li[role="option"][aria-selected="true"],
div[data-baseweb="popover"] li[role="option"][data-highlighted="true"] {
  background: var(--nm-violeta) !important; color: #FFFFFF !important;
}
div[data-baseweb="popover"] li[role="option"]:hover *, div[data-baseweb="popover"] li[role="option"][aria-selected="true"] *,
div[data-baseweb="popover"] li[role="option"][data-highlighted="true"] * { color: #FFFFFF !important; }
div[data-baseweb="popover"] li[role="option"]:focus-visible { outline: 3px solid var(--nm-magenta); outline-offset: -3px; }

/* --- Foco visible --- */
/* El input interno del selectbox (búsqueda de baseweb) no lleva outline propio: el foco ya se ve en el
   contenedor. Se oculta el cursor y se deja pasar el clic al contenedor, que es el que abre el menú. El foco
   por teclado no se afecta: pointer-events solo alcanza al mouse. */
div[data-baseweb="select"] input { caret-color: transparent; pointer-events: none; }
[data-baseweb] input:focus, [data-baseweb] input:focus-visible,
[data-baseweb] textarea:focus, [data-baseweb] textarea:focus-visible { outline: none !important; box-shadow: none; }
/* El foco de input y textarea va solo en el contenedor (data-baseweb="input" / "textarea"): sin borde interior. */
div[data-baseweb="base-input"] { border: 0 !important; box-shadow: none !important; outline: none !important; }
/* Contador nativo ("52/200") de st.text_input con max_chars: se superpone al texto; el límite lo sigue aplicando el navegador. */
[data-testid="InputInstructions"] { display: none; }
.stApp button:focus-visible, .stApp input:focus-visible:not([data-baseweb] input), .stApp textarea:focus-visible:not([data-baseweb] textarea),
.stApp summary:focus-visible, .stApp [role="radio"]:focus-visible {
  outline: 3px solid var(--nm-magenta) !important; outline-offset: 2px;
}
div[data-baseweb="textarea"]:focus-within, div[data-baseweb="input"]:focus-within {
  border-color: var(--nm-magenta) !important; outline: 3px solid var(--nm-magenta); outline-offset: 2px;
}

/* --- Botones --- */
.stApp button[data-testid="stBaseButton-primary"] {
  background: var(--nm-magenta); border: 1px solid var(--nm-magenta); color: #FFFFFF;
  min-height: 48px; border-radius: 10px; font-size: 16px; font-weight: 600;
}
.stApp button[data-testid="stBaseButton-primary"] p { font-size: 16px; font-weight: 600; color: #FFFFFF; }
.stApp button[data-testid="stBaseButton-primary"]:hover:not(:disabled) { background: #A800A8; border-color: #A800A8; }
.stApp button[data-testid="stBaseButton-primary"]:disabled { opacity: 0.55; cursor: not-allowed; }
.stApp button[data-testid="stBaseButton-secondary"] {
  min-height: 44px; border-radius: 10px; border: 2px solid var(--nm-borde-campo);
  background: #FFFFFF; color: var(--nm-texto); font-weight: 600;
}
.stApp button[data-testid="stBaseButton-secondary"] p { font-size: 14px; font-weight: 600; }

/* --- Selector segmentado (solo la vista legible / JSON) --- */
[data-testid="stButtonGroup"] { gap: 8px; flex-wrap: wrap; }
[data-testid="stButtonGroup"] button {
  min-height: 44px; border-radius: 10px !important; border: 2px solid var(--nm-borde-campo);
  background: #FFFFFF; color: var(--nm-texto); font-weight: 500; padding: 0 16px;
}
[data-testid="stButtonGroup"] button p { color: var(--nm-texto); font-size: 14px; }
[data-testid="stButtonGroup"] button[data-testid="stBaseButton-segmented_controlActive"] {
  background: var(--nm-violeta); border-color: var(--nm-violeta);
}
[data-testid="stButtonGroup"] button[data-testid="stBaseButton-segmented_controlActive"] p { color: #FFFFFF; font-weight: 600; }
[data-testid="stButtonGroup"] button:disabled { opacity: 0.6; cursor: not-allowed; }

/* --- Expanders --- */
[data-testid="stExpander"] details {
  border: 1px solid var(--nm-borde); border-radius: 10px; background: #FFFFFF;
}
[data-testid="stExpander"] summary { min-height: 44px; }
[data-testid="stExpander"] summary p { font-size: 14px; font-weight: 500; color: var(--nm-texto-3); }

/* --- Estado vacío --- */
.nm-vacio {
  border: 2px dashed var(--nm-borde-campo); border-radius: 14px; padding: 48px 24px; text-align: center;
  display: flex; flex-direction: column; align-items: center;
}
.nm-vacio-titulo { font-size: 18px; font-weight: 600; color: var(--nm-texto); margin: 0 0 8px 0; }
.nm-vacio-texto { font-size: 14px; color: var(--nm-texto-2); max-width: 360px; margin: 0; line-height: 1.6; }

/* --- Score --- */
.nm-score-fila { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px 12px; flex-wrap: wrap; width: 100%; max-width: 100%; }
.nm-score-etiqueta { font-size: 13px; font-weight: 500; color: var(--nm-texto-2); }
.nm-score-valor { font-size: 40px; font-weight: 600; line-height: 1.2; color: var(--nm-texto); }
.nm-score-nd { font-size: 22px; font-weight: 600; line-height: 1.8; color: var(--nm-texto); }
.nm-comparacion { font-size: 14px; font-weight: 500; line-height: 1.5; margin-top: 4px; }
.nm-comparacion-supera { color: #3F3F00; }
.nm-comparacion-debajo { color: #6B006B; }
.nm-score, .nm-score * { box-sizing: border-box; font-family: var(--nm-fuente); }  /* .nm-mono (con !important) lo pisa solo en el número */
.nm-score { width: 100%; max-width: 100%; min-width: 0; }
.nm-score-bloque { min-width: 0; }
.nm-barra-caja { position: relative; width: 100%; max-width: 100%; margin: 18px 0 34px 0; }
/* Marca del umbral: 3px de lima + 1.5px de borde oscuro (content-box: 6px x 24px en total), centrada en su posición y
   sobresaliendo 6px de la barra por arriba y por abajo para que se vea sobre el relleno y sobre la pista. */
.nm-score .nm-marca {
  position: absolute; top: -6px; box-sizing: content-box; width: 3px; height: 21px;
  background: var(--nm-lima); border: 1.5px solid var(--nm-texto); border-radius: 2px; transform: translateX(-50%);
}
.nm-marca-etiqueta {
  position: absolute; top: 22px; transform: translateX(-50%); white-space: nowrap;
  font-size: 12px; font-weight: 600; line-height: 1.4; color: var(--nm-texto);
}
.nm-pastilla {
  font-size: 13px; font-weight: 600; padding: 6px 14px; border-radius: 999px; white-space: nowrap; flex-shrink: 0;
}
.nm-pastilla-normal { background: #F4F4C6; color: #3F3F00; }
.nm-pastilla-baja { background: #F6D9F6; color: #6B006B; }
.nm-barra { width: 100%; max-width: 100%; height: 12px; border-radius: 999px; background: var(--nm-barra); overflow: hidden; }
.nm-barra-relleno { height: 100%; border-radius: 999px; }
.nm-barra-normal { background: var(--nm-violeta); }
.nm-barra-baja { background: var(--nm-magenta); }
.nm-nota { font-size: 13px; color: var(--nm-texto-2); margin: 8px 0 0 0; line-height: 1.6; }
.nm-aviso {
  font-size: 14px; color: #5A005A; margin: 12px 0 0 0; line-height: 1.6;
  border-left: 4px solid var(--nm-magenta); padding-left: 12px;
}

/* --- JSON --- */
.nm-json {
  background: var(--nm-texto); color: #F1EAF7; font-family: var(--nm-mono); font-size: 12.5px;
  line-height: 1.6; border-radius: 10px; padding: 16px; overflow-x: auto; max-height: 520px; margin: 0 0 12px 0;
}

/* --- Errores --- */
.nm-error {
  background: #F6D9F6; border: 1px solid var(--nm-magenta); border-radius: 14px; padding: 16px 20px;
  color: #6B006B; margin-bottom: 12px;
}
.nm-error p { margin: 0; font-size: 15px; font-weight: 500; }
.nm-error ul { margin: 8px 0 0 0; padding-left: 20px; font-size: 13px; }

/* --- Anchos: el padding de las tarjetas se descuenta del contenido; nada se sale del borde --- */
[class*="st-key-nm-card"], [class*="st-key-nm-item"] { box-sizing: border-box; max-width: 100%; min-width: 0; }
[class*="st-key-nm-card"] *, [class*="st-key-nm-item"] * { box-sizing: border-box; }
[class*="st-key-nm-item"], [class*="st-key-nm-item"] * { min-width: 0; max-width: 100%; overflow-wrap: anywhere; word-break: normal; }
[class*="st-key-nm-item"] pre { overflow-x: auto; white-space: pre; }
/* Causa del desborde de la tarjeta de score: Streamlit fija en st.markdown un `style="width: Npx"` inline con el ancho
   de la columna, sin descontar el padding de la tarjeta. Un width inline solo se pisa con !important. */
[class*="st-key-nm-card"] [data-testid="stMarkdown"], [class*="st-key-nm-item"] [data-testid="stMarkdown"] {
  width: 100% !important; max-width: 100%; min-width: 0;
}
[class*="st-key-nm-card"] [data-testid="stMarkdownContainer"] { max-width: 100%; min-width: 0; }
/* Streamlit resta 16px al final de todo st.markdown (para compensar el margen del último <p>); en la tarjeta de score
   el último elemento ya no lleva margen, y esa resta dejaba solo ~5px de padding inferior. */
.st-key-nm-card-score [data-testid="stMarkdownContainer"]:has(> .nm-score) { margin-bottom: 0; }
.st-key-nm-card-score [data-testid="stExpander"] { margin-top: 8px; }
.st-key-nm-card-score [data-testid="stExpanderDetails"] p { font-size: 14px; line-height: 1.6; color: var(--nm-texto-3); }
.st-key-nm-card-score [data-testid="stSlider"] { padding-top: 4px; }
.st-key-nm-card-score [data-testid="stCaptionContainer"] p { font-size: 13px; color: var(--nm-texto-2); line-height: 1.6; }
.st-key-nm-card-score [data-baseweb="slider"] [role="slider"]:focus-visible { outline: 3px solid var(--nm-magenta); outline-offset: 2px; }
[class*="st-key-nm-card"] > div, [class*="st-key-nm-item"] > div,
[class*="st-key-nm-card"] [data-testid="stElementContainer"], [class*="st-key-nm-item"] [data-testid="stElementContainer"],
[class*="st-key-nm-card"] [data-testid="stFileUploader"], [class*="st-key-nm-card"] [data-testid="stTextInput"],
[class*="st-key-nm-card"] [data-testid="stTextArea"], [class*="st-key-nm-card"] [data-testid="stButton"],
[class*="st-key-nm-card"] [data-testid="stDownloadButton"], [class*="st-key-nm-card"] [data-testid="stSlider"], [class*="st-key-nm-card"] [data-testid="stSelectbox"], [class*="st-key-nm-card"] [data-testid="stExpander"] {
  width: 100% !important; max-width: 100%; min-width: 0;
}
[class*="st-key-nm-card"] [data-testid="stFileUploaderDropzone"], [class*="st-key-nm-card"] div[data-baseweb="textarea"],
[class*="st-key-nm-card"] div[data-baseweb="input"], [class*="st-key-nm-card"] div[data-baseweb="base-input"],
[class*="st-key-nm-card"] button[data-testid="stBaseButton-primary"] { width: 100%; max-width: 100%; }
[class*="st-key-nm-card"] textarea, [class*="st-key-nm-card"] input[type="text"]:not([data-baseweb="select"] input) { width: 100%; }
[data-testid="stExpander"] { max-width: 100%; box-sizing: border-box; }
.nm-json, .nm-vacio, .nm-error { box-sizing: border-box; max-width: 100%; }
.nm-json { white-space: pre; }

/* --- Pantallas angostas --- */
@media (max-width: 640px) {
  .nm-encabezado { padding: 20px; }
  .stApp .nm-encabezado h1 { font-size: 24px; }
  [class*="st-key-nm-card"] { padding: 16px; }
  .nm-score-valor { font-size: 34px; }
}
"""


def css_uploader(max_upload_mb: int, extensiones: tuple[str, ...]) -> str:
    """
    Traduce al español los textos del file_uploader (Streamlit 1.40.2 no lo permite) y arma el límite real.

    Cada texto original se oculta con font-size: 0 y se dibuja el nuevo en ::after. Si Streamlit cambia el
    DOM y un selector deja de coincidir, no pasa nada: queda el texto en inglés. Las extensiones se
    reducen a [A-Za-z0-9] porque van dentro de un string CSS.
    """
    tipos = ", ".join(re.sub(r"[^A-Za-z0-9]", "", e).upper() for e in extensiones)
    limite = f"Hasta {int(max_upload_mb)} MB" + (f" · {tipos}" if tipos else "")
    instrucciones = '[data-testid="stFileUploaderDropzoneInstructions"] > div:last-child'
    return f"""
/* --- file_uploader en español --- */
{instrucciones} > :first-child {{ font-size: 0; line-height: 0; }}
{instrucciones} > :first-child::after {{
  content: "Arrastrá y soltá el archivo acá"; display: block; font-size: 14px; line-height: 1.5; color: var(--nm-texto);
}}
{instrucciones} > :last-child:not(:first-child) {{ font-size: 0; line-height: 0; }}
{instrucciones} > :last-child:not(:first-child)::after {{
  content: "{limite}"; display: block; font-size: 13px; line-height: 1.5; color: var(--nm-texto-2);
}}
[data-testid="stFileUploaderDropzone"] > button {{ font-size: 0; min-width: 130px; }}
[data-testid="stFileUploaderDropzone"] > button::after {{
  content: "Elegir archivo"; font-size: 14px; font-weight: 600; color: var(--nm-texto);
}}
"""


_config = cargar_config()
CSS = CSS_BASE + css_uploader(_config.max_upload_mb, _config.extensiones_archivo)


def inyectar_estilos() -> None:
    """Única puerta de entrada del CSS."""
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
