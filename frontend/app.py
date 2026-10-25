"""
NM-25 / NM-26 / NM-27 — Interfaz Streamlit de NuevaMente.

    streamlit run frontend/app.py

Lógica testeable: frontend/cliente_api.py y frontend/formato.py. HTML: frontend/componentes.py. CSS: frontend/estilos.py.
"""

import sys
import time
from pathlib import Path

# `streamlit run` pone frontend/ en el path, no la raíz del repo: se agrega para importar `frontend.*`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from frontend import cliente_api, componentes, ejemplos, formato  # noqa: E402
from frontend.config import cargar_config  # noqa: E402
from frontend.estilos import inyectar_estilos  # noqa: E402

config = cargar_config()

st.set_page_config(page_title="NuevaMente", page_icon="🧠", layout="wide")

OCIOSO, GENERANDO, LISTO, FALLO = "ocioso", "generando", "listo", "fallo"
ss = st.session_state
ss.setdefault("fase", OCIOSO)
ss.setdefault("resultado", None)
ss.setdefault("error", None)
ss.setdefault("problemas", [])
ss.setdefault("duracion_s", None)

inyectar_estilos()


def _entrada_actual() -> dict:
    """Lo que cargó el usuario, en la forma que espera el cliente de la API."""
    if ss.get("modo") == "Pegar texto":
        return {"texto": ss.get("texto_documento", ""), "archivo": None}
    subido = ss.get("archivo_subido")
    return {"texto": None, "archivo": (subido.name, subido.getvalue()) if subido else None}


def _usar_ejemplo() -> None:
    """
    Carga el texto de ejemplo y pasa al modo "Pegar texto". Es un on_click: corre ANTES de que se creen los widgets en
    el próximo rerun, que es cuando Streamlit permite escribir en el estado de un widget con key.
    """
    ss.modo = "Pegar texto"
    ss.texto_documento = ejemplos.TEXTO_EJEMPLO
    ss.titulo_documento = ejemplos.TITULO_EJEMPLO
    ss.problemas = []


def _volver_al_umbral_oficial() -> None:
    ss.umbral_usuario = formato.umbral_para_slider((ss.resultado or {}).get("evaluacion_calidad", {}).get("umbral"))


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
            inicio = time.perf_counter()
            ss.resultado = cliente_api.adaptar(
                config.api_base_url,
                formato.PERFILES[ss.perfil],
                formato.FORMATOS[ss.formato],
                texto=entrada["texto"],
                archivo=entrada["archivo"],
                titulo=(ss.get("titulo_documento") or "").strip() or None,
                timeout_s=config.api_timeout_s,
            )
            ss.duracion_s = time.perf_counter() - inicio
        ss.pop("umbral_usuario", None)  # el slider arranca en el umbral oficial del resultado nuevo
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
            with st.container(key=f"nm-item-paso-{numero}"):
                st.markdown(componentes.item("Paso", numero, titulo), unsafe_allow_html=True)
                st.write(detalle)
        return
    tarjetas = formato.items_flashcards(contenido)
    if not tarjetas:
        st.info("No se generaron flashcards.")
    for numero, (pregunta, respuesta) in enumerate(tarjetas, start=1):
        with st.container(key=f"nm-item-tarjeta-{numero}"):
            st.markdown(componentes.item("Tarjeta", numero, pregunta), unsafe_allow_html=True)
            with st.expander("Ver respuesta"):
                st.write(respuesta)


def _mostrar_metadatos(meta: dict, oci: dict, duracion_s) -> None:
    with st.expander("Detalles de la generación"):
        st.markdown(
            f"- **Modelo:** {meta.get('modelo', 'No disponible')}\n"
            f"- **Fragmentos usados:** {meta.get('fragmentos_usados', 'No disponible')}\n"
            f"- **Fecha:** {formato.texto_fecha(meta.get('fecha_generacion'), config.app_timezone)}\n"
            f"- **Tiempo de generación:** {formato.texto_duracion(duracion_s)}\n"
            f"- **Documento original:** {formato.texto_almacenamiento(oci.get('documento_original'))}\n"
            f"- **Resultado JSON:** {formato.texto_almacenamiento(oci.get('salida_json'))}"
        )


def _mostrar_score(respuesta: dict) -> None:
    calidad = respuesta.get("evaluacion_calidad") or {}
    meta = respuesta.get("metadatos") or {}
    oficial = formato.umbral_para_slider(calidad.get("umbral"))
    con_slider = oficial is not None and formato.porcentaje_barra(calidad.get("anclaje_fuente_score")) is not None
    if con_slider:
        # Se siembra el estado y el slider se crea SIN `value`: pasar un valor y además escribir la key por la API
        # de session_state (como hace "Volver al umbral oficial") hace que Streamlit muestre una advertencia.
        ss.setdefault("umbral_usuario", oficial)
    umbral_usuario = ss.get("umbral_usuario") if con_slider else None

    with st.container(key="nm-card-score"):
        st.markdown(componentes.tarjeta_score(calidad, umbral_usuario), unsafe_allow_html=True)
        if con_slider:
            st.slider(
                "¿Qué tan exigente querés ser al revisar?",
                min_value=formato.SLIDER_MIN,
                max_value=formato.SLIDER_MAX,
                step=formato.SLIDER_PASO,
                key="umbral_usuario",
            )
            st.caption(
                "Solo cambia cómo leés este resultado: no vuelve a generar, no cambia el contenido y no modifica lo que "
                f"guarda el sistema. El umbral oficial es {formato.texto_umbral(calidad.get('umbral'))}."
            )
            st.button(
                "Volver al umbral oficial",
                key="umbral_oficial",
                on_click=_volver_al_umbral_oficial,
                disabled=abs(ss.umbral_usuario - oficial) < 0.005,
            )
        with st.expander("¿Por qué esta nota?"):
            unidades = formato.unidades_de(respuesta.get("contenido_adaptado"))
            for parrafo in formato.explicacion_nota(calidad, unidades, meta.get("fragmentos_usados")):
                st.markdown(parrafo)


def _botones_de_descarga(respuesta: dict) -> None:
    """Descarga propia del formato (CSV para Anki o Markdown) y, siempre, el JSON crudo."""
    contenido = respuesta.get("contenido_adaptado")
    titulo = (respuesta.get("metadatos") or {}).get("documento_titulo")
    col_formato, col_json = st.columns([3, 2])
    if formato.es_guia(contenido):
        col_formato.download_button(
            "Descargar Markdown",
            data=formato.markdown_guia(titulo, formato.items_guia(contenido)),
            file_name=formato.nombre_descarga(respuesta, "md"),
            mime="text/markdown",
            key="descarga_md",
            use_container_width=True,
        )
    else:
        col_formato.download_button(
            "Descargar CSV (compatible con Anki)",
            data=formato.csv_flashcards(formato.items_flashcards(contenido)),
            file_name=formato.nombre_descarga(respuesta, "csv"),
            mime="text/csv",
            key="descarga_csv",
            use_container_width=True,
        )
    col_json.download_button(
        "Descargar JSON",
        data=formato.json_formateado(respuesta),
        file_name=formato.nombre_descarga(respuesta),
        mime="application/json",
        key="descarga_json",
        use_container_width=True,
    )


def _mostrar_resultado(respuesta: dict) -> None:
    _mostrar_score(respuesta)
    with st.container(key="nm-card-contenido"):
        col_titulo, col_vista = st.columns([3, 2])
        col_titulo.markdown(componentes.titulo_contenido(respuesta), unsafe_allow_html=True)
        vista = col_vista.segmented_control(
            "Vista", ["Vista legible", "JSON"], default="Vista legible", key="vista", label_visibility="collapsed"
        )
        if vista == "JSON":
            st.markdown(componentes.bloque_json(respuesta), unsafe_allow_html=True)
            st.download_button(
                "Descargar JSON",
                data=formato.json_formateado(respuesta),
                file_name=formato.nombre_descarga(respuesta),
                mime="application/json",
                key="descarga_json_vista",
            )
        else:
            _botones_de_descarga(respuesta)
            _mostrar_contenido(respuesta.get("contenido_adaptado"))
    _mostrar_metadatos(
        respuesta.get("metadatos") or {}, respuesta.get("almacenamiento_oci") or {}, ss.get("duracion_s")
    )


# --------------------------------------------------------------------------------------
# Página
# --------------------------------------------------------------------------------------

st.markdown(componentes.encabezado(), unsafe_allow_html=True)

ocupado = ss.fase == GENERANDO
col_entrada, col_resultado = st.columns([1, 1.2], gap="large")

with col_entrada:
    with st.container(key="nm-card-fuente"):
        st.markdown(componentes.titulo_tarjeta("1 · Material fuente"), unsafe_allow_html=True)
        st.radio("¿Cómo querés cargarlo?", ["Subir archivo", "Pegar texto"], key="modo", horizontal=True, disabled=ocupado)
        st.button("Usar texto de ejemplo", key="usar_ejemplo", on_click=_usar_ejemplo, disabled=ocupado)
        if ss.modo == "Pegar texto":
            st.text_area("Texto del documento", key="texto_documento", height=250, disabled=ocupado)
            st.markdown(componentes.contador(len(ss.get("texto_documento", ""))), unsafe_allow_html=True)
        else:
            st.file_uploader(
                "Archivo",
                type=[e.lstrip(".") for e in config.extensiones_archivo],
                key="archivo_subido",
                disabled=ocupado,
                help=f"Tamaño máximo: {config.max_upload_mb} MB.",
            )
        st.text_input("Título (opcional)", key="titulo_documento", max_chars=200, disabled=ocupado)

    with st.container(key="nm-card-parametros"):
        st.markdown(componentes.titulo_tarjeta("2 · Perfil y formato"), unsafe_allow_html=True)
        st.selectbox("Perfil de quien lo va a usar", list(formato.PERFILES), index=0, key="perfil", disabled=ocupado)
        st.selectbox("Formato de salida", list(formato.FORMATOS), index=0, key="formato", disabled=ocupado)
        st.button("Generar contenido", type="primary", disabled=ocupado, on_click=_lanzar, use_container_width=True)
        for problema in ss.problemas:
            st.markdown(componentes.tarjeta_error(problema, []), unsafe_allow_html=True)

with col_resultado:
    if ss.fase == GENERANDO:
        _generar()
    elif ss.fase == FALLO and ss.error is not None:
        st.markdown(componentes.tarjeta_error(ss.error.mensaje, ss.error.detalles), unsafe_allow_html=True)
        st.button("Reintentar", on_click=_lanzar)
    elif ss.fase == LISTO and ss.resultado:
        _mostrar_resultado(ss.resultado)
    else:
        st.markdown(componentes.estado_vacio(), unsafe_allow_html=True)
