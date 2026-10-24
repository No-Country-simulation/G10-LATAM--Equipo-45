"""
NM-25 / NM-26 / NM-27 — Interfaz Streamlit de NuevaMente.

    streamlit run frontend/app.py

Toda la lógica testeable vive en frontend/cliente_api.py y frontend/formato.py; acá solo se dibuja.
"""

import sys
from pathlib import Path

# `streamlit run` pone frontend/ en el path, no la raíz del repo: se agrega para importar `frontend.*`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from frontend import cliente_api, formato  # noqa: E402
from frontend.config import cargar_config  # noqa: E402

config = cargar_config()

st.set_page_config(page_title="NuevaMente", page_icon="🧠", layout="wide")

OCIOSO, GENERANDO, LISTO, FALLO = "ocioso", "generando", "listo", "fallo"
ss = st.session_state
ss.setdefault("fase", OCIOSO)
ss.setdefault("resultado", None)
ss.setdefault("error", None)
ss.setdefault("problemas", [])


def _entrada_actual() -> dict:
    """Lo que cargó el usuario, en la forma que espera el cliente de la API."""
    if ss.get("modo") == "Pegar texto":
        return {"texto": ss.get("texto_documento", ""), "archivo": None}
    subido = ss.get("archivo_subido")
    return {"texto": None, "archivo": (subido.name, subido.getvalue()) if subido else None}


def _lanzar() -> None:
    """Valida y, si está todo bien, pasa a GENERANDO (el próximo rerun llama a la API con el botón deshabilitado)."""
    entrada = _entrada_actual()
    if entrada["texto"] is None and entrada["archivo"] is None:
        ss.problemas = ["Subí un archivo o pegá el texto del documento."]
        return
    ss.problemas = formato.validar_entrada(
        texto=entrada["texto"],
        archivo=entrada["archivo"],
        max_bytes=config.max_upload_bytes,
        extensiones=config.extensiones_archivo,
    )
    if not ss.problemas:
        ss.fase, ss.error, ss.resultado = GENERANDO, None, None


def _generar() -> None:
    entrada = _entrada_actual()
    try:
        with st.spinner("Generando contenido... puede tardar hasta un par de minutos"):
            ss.resultado = cliente_api.adaptar(
                config.api_base_url,
                formato.PERFILES[ss.perfil],
                formato.FORMATOS[ss.formato],
                texto=entrada["texto"],
                archivo=entrada["archivo"],
                titulo=(ss.get("titulo_documento") or "").strip() or None,
                timeout_s=config.api_timeout_s,
            )
        ss.fase = LISTO
    except cliente_api.ErrorDeApi as e:
        ss.error, ss.fase = e, FALLO
    except Exception:  # la UI nunca muestra un stack trace
        ss.error, ss.fase = cliente_api.ErrorDeApi(cliente_api.MENSAJE_GENERICO, cliente_api.SERVIDOR), FALLO
    st.rerun()


# --------------------------------------------------------------------------------------
# Resultado
# --------------------------------------------------------------------------------------


def _mostrar_contenido(contenido) -> None:
    if formato.es_guia(contenido):
        pasos = formato.items_guia(contenido)
        if not pasos:
            st.info("La guía no trae pasos.")
        for numero, (titulo, detalle) in enumerate(pasos, start=1):
            st.markdown(f"**{numero}. {titulo}**")
            st.write(detalle)
        return
    tarjetas = formato.items_flashcards(contenido)
    if not tarjetas:
        st.info("No se generaron flashcards.")
    for pregunta, respuesta in tarjetas:
        with st.container(border=True):
            st.markdown(f"**{pregunta}**")
            with st.expander("Ver respuesta"):
                st.write(respuesta)


def _mostrar_calidad(calidad: dict) -> None:
    st.subheader("Calidad")
    if calidad.get("baja_confianza"):
        st.warning("Baja confianza: el contenido generado podría no reflejar bien el documento. Revisalo con cuidado.")
    col_score, col_umbral = st.columns(2)
    col_score.metric("Anclaje al documento", formato.texto_score(calidad.get("anclaje_fuente_score")))
    col_umbral.metric("Umbral", formato.texto_umbral(calidad.get("umbral")))
    if calidad.get("anclaje_fuente_score") is None and calidad.get("motivo"):
        st.caption(f"No se pudo medir el anclaje: {calidad['motivo']}")
    st.caption(formato.AVISO_ANCLAJE)


def _mostrar_metadatos(meta: dict, oci: dict) -> None:
    st.subheader("Detalles de la generación")
    st.markdown(
        f"- **Modelo:** {meta.get('modelo', 'No disponible')}\n"
        f"- **Fragmentos usados:** {meta.get('fragmentos_usados', 'No disponible')}\n"
        f"- **Fecha:** {formato.texto_fecha(meta.get('fecha_generacion'))}"
    )
    st.markdown("**Almacenamiento en OCI**")
    st.markdown(
        f"- **Documento original:** {formato.texto_almacenamiento(oci.get('documento_original'))}\n"
        f"- **Resultado JSON:** {formato.texto_almacenamiento(oci.get('salida_json'))}"
    )


def _mostrar_resultado(respuesta: dict) -> None:
    st.divider()
    st.header("Resultado")
    pestana_contenido, pestana_json = st.tabs(["Contenido", "JSON"])
    with pestana_contenido:
        _mostrar_contenido(respuesta.get("contenido_adaptado"))
    with pestana_json:
        st.json(respuesta)
    st.download_button(
        "Descargar JSON",
        data=formato.json_formateado(respuesta),
        file_name=formato.nombre_descarga(respuesta),
        mime="application/json",
    )
    col_calidad, col_meta = st.columns(2)
    with col_calidad:
        _mostrar_calidad(respuesta.get("evaluacion_calidad") or {})
    with col_meta:
        _mostrar_metadatos(respuesta.get("metadatos") or {}, respuesta.get("almacenamiento_oci") or {})


# --------------------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------------------

st.title("NuevaMente")
st.caption("Adaptá documentación técnica a distintos perfiles y formatos de estudio, anclada al documento original.")

ocupado = ss.fase == GENERANDO
col_entrada, col_parametros = st.columns([3, 2], gap="large")

with col_entrada:
    st.subheader("1. Documento")
    st.radio("¿Cómo querés cargarlo?", ["Subir archivo", "Pegar texto"], key="modo", horizontal=True, disabled=ocupado)
    if ss.modo == "Pegar texto":
        st.text_area("Texto del documento", key="texto_documento", height=260, disabled=ocupado)
    else:
        st.file_uploader(
            "Archivo",
            type=[e.lstrip(".") for e in config.extensiones_archivo],
            key="archivo_subido",
            disabled=ocupado,
            help=f"Tamaño máximo: {config.max_upload_mb} MB.",
        )
    st.text_input("Título (opcional)", key="titulo_documento", max_chars=200, disabled=ocupado)

with col_parametros:
    st.subheader("2. Parámetros")
    st.selectbox("Perfil del destinatario", list(formato.PERFILES), key="perfil", disabled=ocupado)
    st.selectbox("Formato de salida", list(formato.FORMATOS), key="formato", disabled=ocupado)
    st.button("Generar contenido", type="primary", disabled=ocupado, on_click=_lanzar, use_container_width=True)
    for problema in ss.problemas:
        st.error(problema)

if ss.fase == GENERANDO:
    _generar()
elif ss.fase == FALLO and ss.error is not None:
    st.error(ss.error.mensaje)
    for detalle in ss.error.detalles:
        st.caption(f"• {detalle['campo']}: {detalle['problema']}".replace("• : ", "• "))
    st.button("Reintentar", on_click=_lanzar)
elif ss.fase == LISTO and ss.resultado:
    _mostrar_resultado(ss.resultado)
