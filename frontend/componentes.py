"""
Bloques HTML de la interfaz como funciones puras (devuelven str; no importan Streamlit, se testean solos).

Todo texto que viene de la API o del modelo pasa por `html.escape`: el HTML se inyecta con unsafe_allow_html.
"""

from html import escape

from frontend import formato

NOTA_ANCLAJE = "El puntaje mide anclaje temático al documento, no si los datos son verdaderos. Revisá siempre el resultado contra la fuente."
AVISO_BAJA_CONFIANZA = (
    "La respuesta se devuelve igual, pero marcada como de baja confianza: parte del contenido se parece poco al "
    "material. Conviene que una persona lo revise antes de usarlo."
)


def encabezado() -> str:
    return (
        '<div class="nm-encabezado">'
        "<h1>NuevaMente - Adaptación de contenido educativo</h1>"
        '<p class="nm-encabezado-sub">Material educativo, adaptado a cada perfil y verificado</p>'
        "</div>"
    )


def titulo_tarjeta(texto: str) -> str:
    return f'<p class="nm-titulo-tarjeta">{escape(texto)}</p>'


def contador(cantidad: int) -> str:
    return f'<p class="nm-contador">{formato.texto_caracteres(cantidad)}</p>'


def estado_vacio() -> str:
    return (
        '<div class="nm-vacio">'
        '<p class="nm-vacio-titulo">Todavía no hay resultado</p>'
        '<p class="nm-vacio-texto">Elegí perfil y formato, y tocá “Generar contenido” para ver el resultado '
        "y su score de fidelidad.</p>"
        "</div>"
    )


def tarjeta_score(calidad: dict, umbral_usuario: float | None = None) -> str:
    """`umbral_usuario`: el que eligió la persona con el slider; si difiere del oficial, mueve la marca y la frase."""
    score = calidad.get("anclaje_fuente_score")
    barra = formato.porcentaje_barra(score)
    baja = bool(calidad.get("baja_confianza"))
    clave, texto_estado = formato.estado_confianza(baja)
    oficial = calidad.get("umbral")
    propio = umbral_usuario is not None and formato.porcentaje_barra(oficial) is not None and abs(umbral_usuario - oficial) >= 0.005
    umbral = umbral_usuario if propio else oficial
    marca = formato.posicion_umbral(umbral)

    if barra is None:
        valor = f'<span class="nm-score-nd">{formato.MENSAJE_SCORE_NO_DISPONIBLE}</span>'
    else:
        valor = f'<span class="nm-score-valor nm-mono">{formato.texto_score(score)}</span>'
    comparacion = formato.comparacion_umbral(score, umbral, propio=propio)
    frase = f'<div class="nm-comparacion nm-comparacion-{comparacion[0]}">{comparacion[1]}</div>' if comparacion else ""

    # Sin score y sin baja confianza no hay estado que informar: la píldora diría "normal" sin haber medido nada.
    pastilla = ""
    if barra is not None or baja:
        pastilla = f'<span class="nm-pastilla nm-pastilla-{clave}">{texto_estado}</span>'

    html = (
        '<div class="nm-score">'
        '<div class="nm-score-fila">'
        f'<div class="nm-score-bloque"><div class="nm-score-etiqueta">Anclaje a la fuente</div><div>{valor}</div>{frase}</div>'
        f"{pastilla}</div>"
    )
    if barra is not None:
        html += (
            '<div class="nm-barra-caja">'
            f'<div class="nm-barra" role="progressbar" aria-label="Anclaje a la fuente" aria-valuemin="0" '
            f'aria-valuemax="100" aria-valuenow="{barra}">'
            f'<div class="nm-barra-relleno nm-barra-{clave}" style="width:{barra}%"></div></div>'
        )
        if marca is not None:
            html += (
                f'<div class="nm-marca" style="left:{marca}%"></div>'
                f'<div class="nm-marca-etiqueta" style="left:{formato.posicion_etiqueta_umbral(umbral)}%">'
                f"{'Tu umbral' if propio else 'Umbral'} {formato.texto_umbral(umbral)}</div>"
            )
        html += "</div>"
    elif calidad.get("motivo"):
        html += f'<p class="nm-nota">No se pudo medir el anclaje: {escape(str(calidad["motivo"]))}</p>'
    html += f'<p class="nm-nota">{NOTA_ANCLAJE}</p>'
    if baja:
        html += f'<p class="nm-aviso">{AVISO_BAJA_CONFIANZA}</p>'
    return html + "</div>"


def titulo_contenido(respuesta: dict) -> str:
    meta = respuesta.get("metadatos") or {}
    formato_ui = formato.etiqueta_de(formato.FORMATOS, meta.get("formato_salida"))
    perfil_ui = formato.etiqueta_de(formato.PERFILES, meta.get("perfil_destinatario"))
    return (
        f'<p class="nm-titulo-contenido">{escape(formato_ui)} · {escape(perfil_ui)} '
        '<span class="nm-chip-ok">Completado</span></p>'
    )


def item(etiqueta: str, numero: int, titulo: str) -> str:
    """Cabecera de una tarjeta interna: 'TARJETA 1' / 'PASO 1' y el texto principal (pregunta o título del paso)."""
    return (
        f'<div class="nm-etiqueta nm-mono">{escape(etiqueta)} {numero}</div>'
        f'<div class="nm-pregunta">{escape(titulo)}</div>'
    )


def bloque_json(respuesta: dict) -> str:
    return f'<pre class="nm-json">{escape(formato.json_formateado(respuesta))}</pre>'


def tarjeta_error(mensaje: str, detalles: list[dict]) -> str:
    html = f'<div class="nm-error" role="alert"><p>{escape(mensaje)}</p>'
    lineas = []
    principal = mensaje.strip().casefold()
    for d in detalles:
        if str(d.get("problema", "")).strip().casefold() == principal:
            continue  # repite el mensaje principal: no aporta nada y muestra el nombre técnico del campo
        campo, problema = escape(d.get("campo", "")), escape(d.get("problema", ""))
        lineas.append(f"<li>{campo + ': ' if campo else ''}{problema}</li>")
    if lineas:
        html += "<ul>" + "".join(lineas) + "</ul>"
    return html + "</div>"
