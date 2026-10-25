"""
NM-25 / NM-26 / NM-27 — Tests del frontend. Sin red (httpx.MockTransport) y sin levantar Streamlit,
salvo un humo con AppTest que solo comprueba que la app arranca.
"""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.api.schemas import FormatoSalida, PerfilDestinatario
from app.config import settings
from frontend import cliente_api, componentes, formato
from frontend.cliente_api import ErrorDeApi, adaptar

PERFIL = "Principiante"
FORMATO = "Flashcards"
EXITO = {
    "status": "ok",
    "metadatos": {"documento_titulo": "Doc", "modelo": "gemini-3.5-flash", "fragmentos_usados": 3},
    "contenido_adaptado": [{"pregunta": "¿Qué es una VCN?", "respuesta": "Una red privada."}],
    "evaluacion_calidad": {"anclaje_fuente_score": 0.83, "baja_confianza": False, "umbral": 0.72},
    "almacenamiento_oci": {"documento_original": {"bucket": "b", "objeto_id": "o", "status_upload": "exito"}},
}


def _transporte(handler):
    return httpx.MockTransport(handler)


def _llamar(handler, **kwargs):
    kwargs.setdefault("texto", "Una VCN es una red.")
    return adaptar("http://api.test", PERFIL, FORMATO, transport=_transporte(handler), **kwargs)


# --------------------------------------------------------------------------------------
# Mapeo UI -> enum del backend
# --------------------------------------------------------------------------------------


class TestMapeoConEnumsDelBackend:
    def test_perfiles_de_la_ui_son_exactamente_los_del_enum(self):
        assert set(formato.PERFILES.values()) == {p.value for p in PerfilDestinatario}

    def test_formatos_de_la_ui_son_exactamente_los_del_enum(self):
        assert set(formato.FORMATOS.values()) == {f.value for f in FormatoSalida}

    def test_etiquetas_amigables_esperadas(self):
        assert formato.PERFILES["Líder técnico / Arquitecto"] == "Lider Tecnico / Arquitecto"
        assert formato.FORMATOS["Guía práctica paso a paso"] == "Guia Practica Paso a Paso"
        assert formato.PERFILES["Principiante"] == "Principiante"
        assert formato.FORMATOS["Flashcards"] == "Flashcards"

    def test_la_validacion_usa_los_mismos_limites_que_el_backend_por_defecto(self):
        from frontend.config import ConfigFrontend

        config = ConfigFrontend(_env_file=None)
        assert config.max_upload_bytes == settings.max_upload_bytes
        assert config.extensiones_archivo == settings.extensiones_archivo


# --------------------------------------------------------------------------------------
# Cliente HTTP
# --------------------------------------------------------------------------------------


class TestClienteApi:
    def test_exito_devuelve_el_json_y_envia_los_valores_del_enum(self):
        visto = {}

        def handler(request: httpx.Request) -> httpx.Response:
            visto["url"] = str(request.url)
            visto["campos"] = parse_qs(request.content.decode("utf-8"))
            return httpx.Response(200, json=EXITO)

        resultado = adaptar(
            "http://api.test/", "Lider Tecnico / Arquitecto", "Guia Practica Paso a Paso",
            texto="Una VCN es una red.", titulo="Mi doc", transport=_transporte(handler),
        )
        assert resultado == EXITO
        assert visto["url"] == "http://api.test/api/v1/adaptar"
        assert visto["campos"] == {
            "perfil_destinatario": ["Lider Tecnico / Arquitecto"],
            "formato_salida": ["Guia Practica Paso a Paso"],
            "documento_titulo": ["Mi doc"],
            "documento_contenido": ["Una VCN es una red."],
        }

    def test_envia_archivo_como_multipart(self):
        visto = {}

        def handler(request: httpx.Request) -> httpx.Response:
            visto["cuerpo"] = request.content
            return httpx.Response(200, json=EXITO)

        _llamar(handler, texto=None, archivo=("manual.md", b"# Hola"))
        assert b'name="archivo"; filename="manual.md"' in visto["cuerpo"]
        assert b"documento_contenido" not in visto["cuerpo"]

    def test_422_muestra_el_mensaje_y_detalles_del_formato_de_error_de_la_api(self):
        cuerpo = {
            "status": "error",
            "codigo": "entrada_invalida",
            "mensaje": "Revisá los datos enviados: hay campos con problemas.",
            "detalles": [{"campo": "archivo", "problema": "El archivo está vacío."}],
        }
        with pytest.raises(ErrorDeApi) as exc:
            _llamar(lambda r: httpx.Response(422, json=cuerpo))
        assert exc.value.tipo == cliente_api.VALIDACION
        assert exc.value.status == 422
        assert exc.value.mensaje == cuerpo["mensaje"]
        assert exc.value.detalles == [{"campo": "archivo", "problema": "El archivo está vacío."}]

    def test_413_se_trata_como_error_de_validacion(self):
        cuerpo = {"status": "error", "codigo": "documento_demasiado_grande", "mensaje": "El documento supera el tamaño máximo permitido (10 MB)."}
        with pytest.raises(ErrorDeApi) as exc:
            _llamar(lambda r: httpx.Response(413, json=cuerpo))
        assert exc.value.tipo == cliente_api.VALIDACION and "10 MB" in exc.value.mensaje

    def test_4xx_sin_formato_de_la_api_no_copia_el_cuerpo_crudo(self):
        with pytest.raises(ErrorDeApi) as exc:
            _llamar(lambda r: httpx.Response(400, text="<html>Traceback secreto</html>"))
        assert "Traceback" not in exc.value.mensaje

    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_errores_del_modelo_dan_mensaje_claro(self, status):
        cuerpo = {"status": "error", "codigo": "servicio_no_disponible", "mensaje": "texto del servidor"}
        with pytest.raises(ErrorDeApi) as exc:
            _llamar(lambda r: httpx.Response(status, json=cuerpo))
        assert exc.value.tipo == cliente_api.SERVIDOR
        assert exc.value.mensaje == cliente_api.MENSAJE_MODELO

    def test_500_usa_el_mensaje_de_la_api_o_uno_generico(self):
        cuerpo = {"status": "error", "codigo": "error_interno", "mensaje": "Ocurrió un error inesperado. Probá de nuevo más tarde."}
        with pytest.raises(ErrorDeApi) as exc:
            _llamar(lambda r: httpx.Response(500, json=cuerpo))
        assert exc.value.mensaje == cuerpo["mensaje"]
        with pytest.raises(ErrorDeApi) as exc:
            _llamar(lambda r: httpx.Response(500, text="Internal Server Error"))
        assert exc.value.mensaje == cliente_api.MENSAJE_GENERICO

    def test_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("lento", request=request)

        with pytest.raises(ErrorDeApi) as exc:
            _llamar(handler)
        assert exc.value.tipo == cliente_api.TIMEOUT and exc.value.mensaje == cliente_api.MENSAJE_TIMEOUT

    def test_api_caida(self):
        def handler(request):
            raise httpx.ConnectError("Connection refused", request=request)

        with pytest.raises(ErrorDeApi) as exc:
            _llamar(handler)
        assert exc.value.tipo == cliente_api.CONEXION and exc.value.mensaje == cliente_api.MENSAJE_CONEXION
        assert "refused" not in exc.value.mensaje

    def test_200_con_cuerpo_invalido_es_un_error_controlado(self):
        for respuesta in (httpx.Response(200, text="no es json"), httpx.Response(200, json={"otra": "cosa"})):
            with pytest.raises(ErrorDeApi) as exc:
                _llamar(lambda r, resp=respuesta: resp)
            assert exc.value.mensaje == cliente_api.MENSAJE_RESPUESTA_INVALIDA

    def test_exige_exactamente_uno_entre_texto_y_archivo(self):
        with pytest.raises(ValueError):
            _llamar(lambda r: httpx.Response(200, json=EXITO), texto=None)
        with pytest.raises(ValueError):
            _llamar(lambda r: httpx.Response(200, json=EXITO), archivo=("a.txt", b"x"))

    def test_el_timeout_por_defecto_supera_el_peor_caso_del_backend(self):
        from frontend.config import ConfigFrontend

        assert ConfigFrontend(_env_file=None).api_timeout_s > settings.gemini_timeout_total_s


# --------------------------------------------------------------------------------------
# Validación previa
# --------------------------------------------------------------------------------------


class TestValidarEntrada:
    LIMITE = 1024
    EXT = (".pdf", ".md", ".txt")

    def _v(self, **kwargs):
        kwargs.setdefault("texto", None)
        kwargs.setdefault("archivo", None)
        return formato.validar_entrada(max_bytes=self.LIMITE, extensiones=self.EXT, **kwargs)

    def test_texto_valido(self):
        assert self._v(texto="hola") == []

    @pytest.mark.parametrize("texto", [None, "", "   \n "])
    def test_texto_vacio(self, texto):
        assert self._v(texto=texto)

    def test_texto_demasiado_grande_cuenta_bytes_utf8(self):
        assert self._v(texto="a" * self.LIMITE) == []
        assert self._v(texto="ñ" * (self.LIMITE // 2 + 1))  # 2 bytes por carácter

    def test_archivo_valido(self):
        assert self._v(archivo=("a.PDF", b"contenido")) == []

    def test_archivo_vacio_extension_invalida_y_tamano(self):
        assert self._v(archivo=("a.txt", b"  \n"))
        assert self._v(archivo=("a.docx", b"x"))
        assert self._v(archivo=("sin_extension", b"x"))
        assert self._v(archivo=("a.txt", b"x" * (self.LIMITE + 1)))


# --------------------------------------------------------------------------------------
# Formateo del resultado
# --------------------------------------------------------------------------------------


class TestFormateo:
    def test_flashcards(self):
        contenido = [{"pregunta": "P1", "respuesta": "R1"}, {"pregunta": "sin respuesta"}, "basura", {"pregunta": "P2", "respuesta": "R2"}]
        assert formato.items_flashcards(contenido) == [("P1", "R1"), ("P2", "R2")]
        assert not formato.es_guia(contenido)

    def test_guia(self):
        contenido = {"pasos": [{"titulo": "T1", "detalle": "D1"}, {"titulo": "sin detalle"}, {"titulo": "T2", "detalle": "D2"}]}
        assert formato.es_guia(contenido)
        assert formato.items_guia(contenido) == [("T1", "D1"), ("T2", "D2")]

    def test_contenido_malformado_no_rompe(self):
        assert formato.items_flashcards(None) == []
        assert formato.items_guia(None) == []
        assert formato.items_guia({"pasos": "x"}) == []

    @pytest.mark.parametrize("score,esperado", [(0.83, "0.83"), (1, "1.00"), (0, "0.00"), (None, "No disponible"), ("x", "No disponible"), (True, "No disponible")])
    def test_score(self, score, esperado):
        assert formato.texto_score(score) == esperado

    def test_fecha(self):
        assert formato.texto_fecha("2026-10-24T15:30:00Z") == "24/10/2026 15:30 UTC"
        assert formato.texto_fecha("2026-10-24T12:30:00-03:00") == "24/10/2026 15:30 UTC"
        assert formato.texto_fecha("2026-10-24T15:30:00") == "24/10/2026 15:30 UTC"
        assert formato.texto_fecha(None) == "No disponible"

    def test_almacenamiento_no_expone_bucket_ni_objeto(self):
        resultado = {"bucket": "mi-bucket", "objeto_id": "documentos/secreto.pdf", "status_upload": "pendiente_oci"}
        texto = formato.texto_almacenamiento(resultado)
        assert "mi-bucket" not in texto and "secreto" not in texto
        assert formato.texto_almacenamiento({"status_upload": "exito"}) == "Guardado en OCI"
        assert formato.texto_almacenamiento({"status_upload": "error"}) == "No se pudo guardar"
        assert formato.texto_almacenamiento(None) == "No disponible"

    def test_json_formateado_conserva_tildes_y_es_valido(self):
        texto = formato.json_formateado(EXITO)
        assert "¿Qué es una VCN?" in texto
        assert json.loads(texto) == EXITO

    def test_nombre_de_descarga_es_seguro(self):
        assert formato.nombre_descarga({"metadatos": {"documento_titulo": "../../etc/passwd"}}) == "nuevamente_etc_passwd.json"
        assert formato.nombre_descarga({}) == "nuevamente_resultado.json"


class TestMarcaDeUmbral:
    @pytest.mark.parametrize("umbral,esperado", [(0, 0.0), (0.72, 72.0), (1, 100.0), (None, None), (1.7, 100.0), (-0.3, 0.0), ("x", None)])
    def test_posicion_de_la_marca(self, umbral, esperado):
        assert formato.posicion_umbral(umbral) == esperado

    def test_la_marca_usa_el_mismo_calculo_que_la_barra(self):
        for valor in (0, 0.33, 0.72, 1, 2, None):
            assert formato.posicion_umbral(valor) == formato.porcentaje_barra(valor)

    def test_marca_etiqueta_y_frase_en_la_tarjeta(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": 0.83, "baja_confianza": False, "umbral": 0.72})
        assert '<div class="nm-marca" style="left:72.0%"></div>' in html
        assert '<div class="nm-marca-etiqueta" style="left:72.0%">Umbral 0.72</div>' in html
        assert '<div class="nm-comparacion nm-comparacion-supera">Supera el umbral mínimo (0.72)</div>' in html
        assert "Umbral mínimo:" not in html and "nm-umbral-texto" not in html and "nm-marca-der" not in html

    def test_score_por_debajo_del_umbral(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": 0.5, "baja_confianza": True, "umbral": 0.72})
        assert '<div class="nm-comparacion nm-comparacion-debajo">Queda por debajo del umbral mínimo (0.72)</div>' in html

    def test_la_etiqueta_se_limita_pero_la_marca_no(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": 0.5, "baja_confianza": False, "umbral": 0.98})
        assert 'class="nm-marca" style="left:98.0%"' in html and 'class="nm-marca-etiqueta" style="left:88.0%">Umbral 0.98' in html
        html = componentes.tarjeta_score({"anclaje_fuente_score": 0.5, "baja_confianza": False, "umbral": 0.02})
        assert 'class="nm-marca" style="left:2.0%"' in html and 'class="nm-marca-etiqueta" style="left:12.0%">Umbral 0.02' in html

    def test_sin_umbral_no_hay_marca_etiqueta_ni_frase(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": 0.83, "baja_confianza": False, "umbral": None})
        assert "nm-marca" not in html and "nm-comparacion" not in html and "nm-barra-relleno" in html

    def test_sin_score_no_hay_barra_marca_ni_frase(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": None, "baja_confianza": False, "umbral": 0.72})
        assert "nm-barra" not in html and "nm-marca" not in html and "nm-comparacion" not in html and "No disponible" in html

    def test_la_monoespaciada_queda_solo_para_el_score(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": 0.83, "baja_confianza": False, "umbral": 0.72})
        assert html.count("nm-mono") == 1 and 'nm-score-valor nm-mono' in html
        assert "nm-mono" not in componentes.tarjeta_score({"anclaje_fuente_score": None, "baja_confianza": True, "umbral": 0.72})


class TestComparacionConElUmbral:
    @pytest.mark.parametrize(
        "score,umbral,esperado",
        [
            (0.90, 0.72, ("supera", "Supera el umbral mínimo (0.72)")),
            (0.72, 0.72, ("supera", "Supera el umbral mínimo (0.72)")),  # igual cuenta como que supera
            (0.50, 0.72, ("debajo", "Queda por debajo del umbral mínimo (0.72)")),
            (None, 0.72, None),
            (0.90, None, None),
            (None, None, None),
        ],
    )
    def test_comparacion(self, score, umbral, esperado):
        assert formato.comparacion_umbral(score, umbral) == esperado

    @pytest.mark.parametrize("umbral,esperado", [(0, 12.0), (0.02, 12.0), (0.72, 72.0), (0.98, 88.0), (1, 88.0), (None, None)])
    def test_posicion_limitada_de_la_etiqueta(self, umbral, esperado):
        assert formato.posicion_etiqueta_umbral(umbral) == esperado

    def test_el_limite_de_la_etiqueta_es_configurable(self):
        assert formato.posicion_etiqueta_umbral(0.01, minimo=5, maximo=95) == 5
        assert formato.posicion_etiqueta_umbral(0.99, minimo=5, maximo=95) == 95


class TestEstilos:
    def test_css_de_la_tarjeta_de_score_no_desborda(self):
        from frontend.estilos import CSS

        assert ".nm-score, .nm-score * { box-sizing: border-box;" in CSS
        assert "flex-wrap: wrap" in CSS.split(".nm-score-fila")[1].split("}")[0]
        assert "flex-shrink: 0" in CSS.split(".nm-pastilla {")[1].split("}")[0]
        assert "height: 12px" in CSS.split(".nm-barra {")[1].split("}")[0]
        # causa real del desborde: st.markdown trae un width inline en px que solo se pisa con !important
        regla = CSS.split('[class*="st-key-nm-card"] [data-testid="stMarkdown"],')[1].split("}")[0]
        assert "width: 100% !important" in regla
        assert "width: 100%; max-width: 100%" in CSS.split(".nm-barra {")[1].split("}")[0]

    def test_css_de_la_marca_del_umbral(self):
        from frontend.estilos import CSS

        marca = CSS.split(".nm-score .nm-marca {")[1].split("}")[0]
        assert "width: 3px" in marca and "#DDDD37".lower() in CSS.lower() and "1.5px solid var(--nm-texto)" in marca
        assert "top: -6px" in marca and "content-box" in marca  # 3px + 2 x 1.5px de borde, 6px de alto extra
        etiqueta = CSS.split(".nm-marca-etiqueta {")[1].split("}")[0]
        assert "font-size: 12px" in etiqueta and "font-weight: 600" in etiqueta
        assert ".nm-comparacion-supera { color: #3F3F00; }" in CSS and ".nm-comparacion-debajo { color: #6B006B; }" in CSS

    def test_las_tarjetas_internas_parten_el_texto_largo(self):
        from frontend.estilos import CSS

        regla = CSS.split('[class*="st-key-nm-item"], [class*="st-key-nm-item"] * {')[1].split("}")[0]
        assert "overflow-wrap: anywhere" in regla and "word-break: normal" in regla
        assert "min-width: 0" in regla and "max-width: 100%" in regla
        base = CSS.split('[class*="st-key-nm-card"], [class*="st-key-nm-item"] {')[1].split("}")[0]
        assert "box-sizing: border-box" in base

    def test_el_json_hace_scroll_horizontal_dentro_de_la_tarjeta(self):
        from frontend.estilos import CSS

        regla = CSS.split(".nm-json {")[1].split("}")[0]
        assert "overflow-x: auto" in regla

    def test_el_contador_nativo_del_input_esta_oculto(self):
        from frontend.estilos import CSS

        assert '[data-testid="InputInstructions"] { display: none; }' in CSS

    def test_el_encabezado_nuevo_tiene_sus_estilos(self):
        from frontend.estilos import CSS

        sub = CSS.split(".stApp .nm-encabezado-sub {")[1].split("}")[0]
        assert "#E8DCF0" in sub and "font-weight: 400" in sub and "font-size: 16px" in sub
        assert "nm-encabezado-sup" not in CSS

    def test_el_foco_de_inputs_y_textareas_va_solo_en_el_contenedor(self):
        from frontend.estilos import CSS

        assert 'div[data-baseweb="textarea"]:focus-within, div[data-baseweb="input"]:focus-within' in CSS
        assert "[data-baseweb] textarea:focus-visible" in CSS
        assert 'div[data-baseweb="base-input"] { border: 0 !important' in CSS

    def test_el_css_del_uploader_usa_el_limite_y_las_extensiones_reales(self):
        from frontend import estilos
        from frontend.config import cargar_config

        config = cargar_config()
        assert f"Hasta {config.max_upload_mb} MB" in estilos.CSS
        for extension in config.extensiones_archivo:
            assert extension.lstrip(".").upper() in estilos.CSS

    def test_css_uploader_con_valores_propios_y_sanitiza_las_extensiones(self):
        from frontend.estilos import css_uploader

        css = css_uploader(25, (".pdf", ".md", '.t"x}t'))
        assert 'content: "Hasta 25 MB · PDF, MD, TXT";' in css

    def test_el_css_del_uploader_esta_en_espanol_y_oculta_los_originales(self):
        from frontend.estilos import css_uploader

        css = css_uploader(10, (".pdf",))
        assert "Arrastrá y soltá el archivo acá" in css and "Elegir archivo" in css
        assert css.count("font-size: 0") >= 3  # el texto original de las tres piezas queda oculto
        assert "Drag and drop" not in css and "Browse files" not in css and "Limit 200MB" not in css

    def test_el_outline_global_excluye_el_input_interno_del_select_y_el_contenedor_lo_conserva(self):
        from frontend.estilos import CSS

        assert ".stApp input:focus-visible:not([data-baseweb] input)" in CSS  # la regla global lo excluye (select, input, textarea)
        assert "[data-baseweb] input:focus-visible" in CSS and "outline: none !important" in CSS  # y hay una que lo anula
        assert 'div[data-baseweb="select"] input { caret-color: transparent; pointer-events: none; }' in CSS
        # el contenedor del selectbox sigue con su foco visible (outline magenta de 3px, offset 2px)
        regla = CSS[CSS.index('div[data-baseweb="select"] > div:focus-within'):]
        regla = regla[: regla.index("}")]
        assert "outline: 3px solid var(--nm-magenta)" in regla and "outline-offset: 2px" in regla

    def test_las_tarjetas_descuentan_el_padding(self):
        from frontend.estilos import CSS

        assert "box-sizing: border-box" in CSS and 'st-key-nm-card' in CSS


# --------------------------------------------------------------------------------------
# Humo de la UI
# --------------------------------------------------------------------------------------


class TestHelpersVisuales:
    @pytest.mark.parametrize("score,esperado", [(0, 0.0), (0.72, 72.0), (1, 100.0), (0.833, 83.3), (None, None), (1.7, 100.0), (-1, 0.0), ("x", None), (True, None)])
    def test_porcentaje_de_la_barra(self, score, esperado):
        assert formato.porcentaje_barra(score) == esperado

    def test_estado_de_confianza_lleva_texto(self):
        assert formato.estado_confianza(False) == ("normal", "Confianza normal")
        assert formato.estado_confianza(True) == ("baja", "Baja confianza")
        assert formato.estado_confianza(None) == ("normal", "Confianza normal")

    def test_fecha_en_zona_local(self):
        # Asunción es UTC-3 en octubre de 2026 (Paraguay quedó en UTC-3 permanente desde octubre de 2024).
        assert formato.texto_fecha("2026-10-24T15:30:00Z", "America/Asuncion") == "24/10/2026 12:30 (America/Asuncion)"

    def test_fecha_en_utc(self):
        assert formato.texto_fecha("2026-10-24T15:30:00Z", "UTC") == "24/10/2026 15:30 UTC"

    @pytest.mark.parametrize("zona", ["Marte/Olimpo", "", "../etc", "no valida"])
    def test_fecha_con_zona_invalida_cae_a_utc_y_lo_dice(self, zona):
        assert formato.texto_fecha("2026-10-24T15:30:00Z", zona) == "24/10/2026 15:30 UTC"

    def test_la_zona_por_defecto_de_la_config_es_asuncion(self):
        from frontend.config import ConfigFrontend

        assert ConfigFrontend(_env_file=None).app_timezone == "America/Asuncion"

    def test_caracteres(self):
        assert formato.texto_caracteres(0) == "0 caracteres"
        assert formato.texto_caracteres(1) == "1 carácter"
        assert formato.texto_caracteres(12345) == "12.345 caracteres"

    def test_etiqueta_del_enum(self):
        assert formato.etiqueta_de(formato.PERFILES, "Lider Tecnico / Arquitecto") == "Líder técnico / Arquitecto"
        assert formato.etiqueta_de(formato.FORMATOS, "Guia Practica Paso a Paso") == "Guía práctica paso a paso"
        assert formato.etiqueta_de(formato.FORMATOS, "Otro") == "Otro"
        assert formato.etiqueta_de(formato.FORMATOS, None) == "No disponible"


class TestComponentes:
    def test_score_normal_con_barra_y_pastilla(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": 0.83, "baja_confianza": False, "umbral": 0.72})
        assert "0.83" in html and "Supera el umbral mínimo (0.72)" in html
        assert "Confianza normal" in html and "nm-barra-normal" in html and "width:83.0%" in html
        assert componentes.NOTA_ANCLAJE in html and "nm-aviso" not in html

    def test_score_con_baja_confianza_muestra_aviso_y_barra_magenta(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": 0.5, "baja_confianza": True, "umbral": 0.72})
        assert "Baja confianza" in html and "nm-barra-baja" in html
        assert componentes.AVISO_BAJA_CONFIANZA in html

    def test_score_null_no_disponible_sin_barra_y_no_rompe(self):
        html = componentes.tarjeta_score({"anclaje_fuente_score": None, "baja_confianza": False, "motivo": "Sin <b>embeddings</b>"})
        assert "No disponible" in html and "nm-barra" not in html and "Confianza normal" not in html
        assert "&lt;b&gt;" in html and "<b>" not in html
        assert "No disponible" in componentes.tarjeta_score({})

    def test_el_html_escapa_el_contenido_del_modelo(self):
        assert "<script>" not in componentes.item("Tarjeta", 1, "<script>alert(1)</script>")
        assert "<script>" not in componentes.bloque_json({"x": "<script>"})
        assert "<img" not in componentes.tarjeta_error("<img src=x>", [{"campo": "<i>", "problema": "<u>"}])

    def test_titulo_del_contenido_usa_etiquetas_amigables(self):
        html = componentes.titulo_contenido({"metadatos": {"formato_salida": "Guia Practica Paso a Paso", "perfil_destinatario": "Principiante"}})
        assert "Guía práctica paso a paso · Principiante" in html

    def test_error_con_detalles(self):
        html = componentes.tarjeta_error("Revisá los datos", [{"campo": "archivo", "problema": "Vacío"}])
        assert "Revisá los datos" in html and "<li>archivo: Vacío</li>" in html

    def test_el_encabezado_no_trae_la_pildora_maqueta(self):
        html = componentes.encabezado()
        assert "<h1>NuevaMente - Adaptación de contenido educativo</h1>" in html
        assert '<p class="nm-encabezado-sub">Material educativo, adaptado a cada perfil y verificado</p>' in html
        assert "Maqueta" not in html and "nm-encabezado-sup" not in html and "NuevaMente ·" not in html


# --------------------------------------------------------------------------------------
# Humo de la UI
# --------------------------------------------------------------------------------------

GUIA = EXITO | {
    "metadatos": EXITO["metadatos"] | {"formato_salida": "Guia Practica Paso a Paso", "perfil_destinatario": "Lider Tecnico / Arquitecto", "fecha_generacion": "2026-10-24T15:30:00Z"},
    "contenido_adaptado": {"pasos": [{"titulo": "Crear la VCN", "detalle": "Configurar las redes."}]},
    "evaluacion_calidad": {"anclaje_fuente_score": None, "baja_confianza": True, "umbral": 0.72, "motivo": "Sin embeddings"},
}


@pytest.fixture
def app_sin_api(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def no_debe_llamarse(*args, **kwargs):
        raise AssertionError("el humo no debe llamar a la API")

    monkeypatch.setattr(cliente_api, "adaptar", no_debe_llamarse)
    return AppTest.from_file("frontend/app.py", default_timeout=30)


def _con_resultado(at, respuesta):
    # Se precarga el estado y se corre UNA vez: AppTest 1.40 no soporta una segunda corrida con st.segmented_control.
    at.session_state["fase"] = "listo"
    at.session_state["resultado"] = respuesta
    return at.run()


def _textos(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(e.label for e in at.expander)


def test_la_app_arranca_en_estado_vacio(app_sin_api):
    at = app_sin_api.run()
    assert not at.exception
    texto = _textos(at)
    assert "NuevaMente - Adaptación de contenido educativo" in texto
    assert "Material educativo, adaptado a cada perfil y verificado" in texto
    assert "Todavía no hay resultado" in texto
    assert [b.label for b in at.button] == ["Generar contenido"]
    assert [sb.label for sb in at.selectbox] == ["Perfil de quien lo va a usar", "Formato de salida"]
    assert list(at.selectbox[0].options) == ["Principiante", "Líder técnico / Arquitecto"]
    assert list(at.selectbox[1].options) == ["Flashcards", "Guía práctica paso a paso"]
    assert (at.selectbox[0].value, at.selectbox[1].value) == ("Principiante", "Flashcards")


def test_elegir_perfil_y_formato_envia_los_valores_del_enum_a_la_api(monkeypatch):
    from streamlit.testing.v1 import AppTest

    llamadas = []

    def falsa(base_url, perfil, formato_salida, **kwargs):
        llamadas.append((perfil, formato_salida, kwargs))
        return GUIA

    monkeypatch.setattr(cliente_api, "adaptar", falsa)
    at = AppTest.from_file("frontend/app.py", default_timeout=30).run()
    at.radio[0].set_value("Pegar texto").run()
    at.text_area[0].set_value("Una VCN es una red privada.").run()
    at.selectbox[0].select("Líder técnico / Arquitecto").run()
    at.selectbox[1].select("Guía práctica paso a paso").run()
    at.button[0].click().run()

    assert not at.exception
    assert len(llamadas) == 1
    perfil, formato_salida, kwargs = llamadas[0]
    assert (perfil, formato_salida) == ("Lider Tecnico / Arquitecto", "Guia Practica Paso a Paso")
    assert perfil == PerfilDestinatario.LIDER_TECNICO.value and formato_salida == FormatoSalida.GUIA_PRACTICA.value
    assert kwargs["texto"] == "Una VCN es una red privada." and kwargs["archivo"] is None
    assert "PASO 1" in _textos(at).upper()


def test_la_app_muestra_un_resultado_de_flashcards(app_sin_api):
    at = _con_resultado(app_sin_api, EXITO | {"metadatos": EXITO["metadatos"] | {"fecha_generacion": "2026-10-24T15:30:00Z"}})
    assert not at.exception
    texto = _textos(at)
    assert "Anclaje a la fuente" in texto and "0.83" in texto and "TARJETA 1" in texto.upper()
    assert "¿Qué es una VCN?" in texto and "Ver respuesta" in texto and "Detalles de la generación" in texto
    assert "Todavía no hay resultado" not in texto


def test_la_app_muestra_una_guia_con_score_null_y_baja_confianza(app_sin_api):
    at = _con_resultado(app_sin_api, GUIA)
    assert not at.exception
    texto = _textos(at)
    assert "PASO 1" in texto.upper() and "Crear la VCN" in texto
    assert "No disponible" in texto and "Baja confianza" in texto
    assert "Guía práctica paso a paso · Líder técnico / Arquitecto" in texto


def test_la_app_muestra_el_error_sin_romper(app_sin_api):
    app_sin_api.session_state["fase"] = "fallo"
    app_sin_api.session_state["error"] = ErrorDeApi("El modelo no respondió", cliente_api.SERVIDOR, 503)
    at = app_sin_api.run()
    assert not at.exception
    assert "El modelo no respondió" in _textos(at)
    assert [b.label for b in at.button] == ["Generar contenido", "Reintentar"]


@pytest.mark.parametrize("status", [413, 422])
def test_un_4xx_no_ofrece_reintentar(app_sin_api, status):
    mensaje = "El documento no contiene texto suficiente para adaptar. Subí un material con al menos algunos párrafos."
    app_sin_api.session_state["fase"] = "fallo"
    app_sin_api.session_state["error"] = ErrorDeApi(mensaje, cliente_api.VALIDACION, status)
    at = app_sin_api.run()
    assert not at.exception
    assert mensaje in _textos(at)
    assert "Reintentar" not in [b.label for b in at.button]


@pytest.mark.parametrize(
    "tipo, status", [(cliente_api.SERVIDOR, 503), (cliente_api.SERVIDOR, 502), (cliente_api.CONEXION, None), (cliente_api.TIMEOUT, None)]
)
def test_los_errores_de_servicio_y_conexion_si_ofrecen_reintentar(app_sin_api, tipo, status):
    app_sin_api.session_state["fase"] = "fallo"
    app_sin_api.session_state["error"] = ErrorDeApi("No disponible", tipo, status)
    assert "Reintentar" in [b.label for b in app_sin_api.run().button]


def test_solo_los_4xx_no_son_reintentables():
    def error(status):
        return httpx.Response(status, json={"status": "error", "codigo": "x", "mensaje": "m"})

    assert not cliente_api._error_http(error(422)).reintentable
    assert not cliente_api._error_http(error(413)).reintentable
    assert all(cliente_api._error_http(error(s)).reintentable for s in (500, 502, 503, 504))
