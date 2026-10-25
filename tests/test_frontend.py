"""
NM-25 / NM-26 / NM-27 — Tests del frontend. Sin red (httpx.MockTransport) y sin levantar Streamlit,
salvo un humo con AppTest que solo comprueba que la app arranca.
"""

import csv
import io
import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.api.schemas import FormatoSalida, PerfilDestinatario
from app.config import settings
from frontend import cliente_api, componentes, ejemplos, formato
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
        assert formato.nombre_descarga({"metadatos": {"documento_titulo": "../../etc/passwd"}}) == "nuevamente-etc-passwd.json"
        assert formato.nombre_descarga({}) == "nuevamente-resultado.json"


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

    def test_error_con_detalle_igual_al_mensaje_no_muestra_lista(self):
        html = componentes.tarjeta_error("Documento sin texto.", [{"campo": "archivo", "problema": "  documento SIN texto. "}])
        assert "Documento sin texto." in html and "<ul>" not in html and "archivo" not in html

    def test_error_con_detalle_distinto_al_mensaje_muestra_lista(self):
        html = componentes.tarjeta_error("Revisá los datos", [{"campo": "archivo", "problema": "Vacío"}])
        assert "<ul>" in html and "<li>archivo: Vacío</li>" in html

    def test_error_con_varios_detalles_solo_muestra_los_distintos(self):
        html = componentes.tarjeta_error(
            "Revisá los datos",
            [
                {"campo": "a", "problema": "Revisá los datos"},
                {"campo": "b", "problema": "Vacío"},
                {"campo": "c", "problema": "revisá los datos "},
            ],
        )
        assert html.count("<li>") == 1 and "<li>b: Vacío</li>" in html and "a:" not in html and "c:" not in html

    def test_error_sin_detalles_no_muestra_lista(self):
        html = componentes.tarjeta_error("Algo falló", [])
        assert "Algo falló" in html and "<ul>" not in html

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
    assert [b.label for b in at.button] == ["Usar texto de ejemplo", "Generar contenido"]
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
    [b for b in at.button if b.label == "Generar contenido"][0].click().run()

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
    assert [b.label for b in at.button] == ["Usar texto de ejemplo", "Generar contenido", "Reintentar"]


@pytest.mark.parametrize(
    "mensaje, status",
    [
        ("El documento no tiene contenido útil para adaptar.", 422),
        ("El documento supera el tamaño máximo permitido (10 MB).", 413),
    ],
)
def test_un_error_de_validacion_muestra_el_mensaje_sin_boton_reintentar(app_sin_api, mensaje, status):
    app_sin_api.session_state["fase"] = "fallo"
    app_sin_api.session_state["error"] = ErrorDeApi(mensaje, cliente_api.VALIDACION, status)
    at = app_sin_api.run()
    assert not at.exception
    assert mensaje in _textos(at)
    assert [b.label for b in at.button] == ["Usar texto de ejemplo", "Generar contenido"]


# --------------------------------------------------------------------------------------
# Usabilidad: ejemplo, nota, slider, descargas, tiempo
# --------------------------------------------------------------------------------------

CALIDAD_OK = {"anclaje_fuente_score": 0.83, "baja_confianza": False, "umbral": 0.72}


class TestEjemplo:
    def test_el_ejemplo_respeta_el_limite_de_la_ui(self):
        from frontend.config import ConfigFrontend

        config = ConfigFrontend(_env_file=None)
        assert formato.validar_entrada(texto=ejemplos.TEXTO_EJEMPLO, archivo=None, max_bytes=config.max_upload_bytes, extensiones=config.extensiones_archivo) == []
        assert len(ejemplos.TITULO_EJEMPLO) <= 200  # el campo Título tiene max_chars=200

    def test_el_ejemplo_es_el_pedido(self):
        assert ejemplos.TITULO_EJEMPLO == "Redes virtuales en Oracle Cloud Infrastructure (OCI)"
        assert ejemplos.TEXTO_EJEMPLO.startswith("Redes virtuales en Oracle Cloud Infrastructure (OCI)\n\nUna Virtual Cloud Network (VCN)")
        assert ejemplos.TEXTO_EJEMPLO.endswith("eliminá las que ya no se usen.")
        for seccion in ("Subredes públicas y privadas", "Componentes de conectividad", "Seguridad de red", "Buenas prácticas"):
            assert seccion in ejemplos.TEXTO_EJEMPLO


class TestExplicacionDeLaNota:
    def _texto(self, calidad, unidades=4, fragmentos=3):
        return "\n".join(formato.explicacion_nota(calidad, unidades, fragmentos))

    def test_explica_el_calculo_y_la_linea_dinamica(self):
        texto = self._texto(CALIDAD_OK)
        assert "se toma la similitud más alta" in texto and "promedio de esas similitudes" in texto
        assert "En este resultado se compararon 4 unidades contra 3 fragmentos del documento." in texto
        assert "no verifica" in texto and "Revisá siempre contra la fuente" in texto
        assert "por debajo del umbral" not in texto

    def test_singular(self):
        assert "se compararon 1 unidad contra 1 fragmento del documento." in self._texto(CALIDAD_OK, 1, 1)

    @pytest.mark.parametrize("unidades,fragmentos", [(0, 3), (4, 0), (4, None), (4, "3"), (4, True)])
    def test_sin_datos_para_la_linea_dinamica_se_omite(self, unidades, fragmentos):
        assert "se compararon" not in self._texto(CALIDAD_OK, unidades, fragmentos)

    def test_baja_confianza_agrega_el_aviso(self):
        assert "La nota quedó por debajo del umbral" in self._texto(CALIDAD_OK | {"baja_confianza": True})

    def test_score_null_explica_sin_inventar_causas_ni_numeros(self):
        texto = self._texto({"anclaje_fuente_score": None, "baja_confianza": True, "umbral": 0.72})
        assert "no se pudo calcular la nota" in texto and "servicio de embeddings" in texto
        assert "se compararon" not in texto and "promedio" not in texto

    @pytest.mark.parametrize("calidad", [CALIDAD_OK, CALIDAD_OK | {"baja_confianza": True}, {"anclaje_fuente_score": None, "baja_confianza": False}])
    def test_nunca_presenta_la_nota_como_verdad_ni_porcentaje(self, calidad):
        texto = self._texto(calidad).lower()
        assert "coincidencia factual" not in texto and "%" not in texto and "aciertos" not in texto and "porcentaje" not in texto

    def test_unidades(self):
        assert formato.unidades_de([{"pregunta": "p", "respuesta": "r"}] * 3) == 3
        assert formato.unidades_de({"pasos": [{"titulo": "t", "detalle": "d"}] * 2}) == 2
        assert formato.unidades_de(None) == 0


class TestUmbralDelSlider:
    @pytest.mark.parametrize("umbral,esperado", [(0.72, 0.72), (0.7249, 0.72), (0.3, 0.5), (0.99, 0.95), (None, None), ("x", None)])
    def test_valor_inicial(self, umbral, esperado):
        assert formato.umbral_para_slider(umbral) == esperado

    def test_comparacion_con_el_umbral_propio(self):
        assert formato.comparacion_umbral(0.83, 0.90, propio=True) == ("debajo", "Con tu umbral (0.90): queda por debajo")
        assert formato.comparacion_umbral(0.83, 0.80, propio=True) == ("supera", "Con tu umbral (0.80): lo supera")

    def test_la_tarjeta_mueve_la_marca_y_la_frase_pero_no_la_pildora(self):
        html = componentes.tarjeta_score(CALIDAD_OK, 0.90)
        assert 'class="nm-marca" style="left:90.0%"' in html and "Tu umbral 0.90" in html
        assert "Con tu umbral (0.90): queda por debajo" in html
        assert "Confianza normal" in html and "nm-aviso" not in html  # lo oficial sigue reflejando a la API
        oficial = componentes.tarjeta_score(CALIDAD_OK, 0.72)
        assert "Supera el umbral mínimo (0.72)" in oficial and "Tu umbral" not in oficial


class TestDescargas:
    def test_csv_escapa_comas_comillas_y_saltos_de_linea(self):
        filas = list(csv.reader(io.StringIO(formato.csv_flashcards([("¿a, b?", 'dijo "hola"\nen dos líneas')]))))
        assert filas == [["¿a, b?", 'dijo "hola"\nen dos líneas']]

    def test_csv_conserva_tildes_y_es_utf8(self):
        texto = formato.csv_flashcards([("¿Qué es una VCN?", "Una red privada, ñandú.")])
        assert "¿Qué es una VCN?" in texto and texto.encode("utf-8").decode("utf-8") == texto

    @pytest.mark.parametrize("celda", ["=1+1", "+cmd", "-2", "@SUMA(A1)", "\t=1"])
    def test_csv_neutraliza_formulas_en_cualquiera_de_las_dos_columnas(self, celda):
        pregunta, respuesta = list(csv.reader(io.StringIO(formato.csv_flashcards([(celda, celda)]))))[0]
        assert pregunta == "'" + celda and respuesta == "'" + celda

    def test_csv_no_toca_celdas_normales(self):
        assert list(csv.reader(io.StringIO(formato.csv_flashcards([("a=b", "c-d")])))) == [["a=b", "c-d"]]

    def test_csv_lista_vacia(self):
        assert formato.csv_flashcards([]) == ""

    def test_markdown_de_la_guia(self):
        texto = formato.markdown_guia("Mi guía", [("Crear la VCN", "Entrá a la consola."), ("Subredes", "Una pública.\nUna privada.")])
        assert texto == "# Mi guía\n\n## 1. Crear la VCN\n\nEntrá a la consola.\n\n## 2. Subredes\n\nUna pública.\nUna privada.\n"

    def test_markdown_con_titulo_vacio_o_multilinea_y_sin_pasos(self):
        assert formato.markdown_guia("", []).startswith("# Guía práctica\n")
        assert formato.markdown_guia(None, []).startswith("# Guía práctica\n")
        assert formato.markdown_guia("Uno\ndos", []).startswith("# Uno dos\n")

    @pytest.mark.parametrize(
        "titulo,esperado",
        [
            ("Redes virtuales en OCI", "Redes-virtuales-en-OCI"),
            ("¿Qué es una VCN? (guía)", "Que-es-una-VCN-guia"),
            ("../../etc/passwd", "etc-passwd"),
            ("a/b\\c:d*e?\"f<g>h|i", "a-b-c-d-e-f-g-h-i"),
            ("", "resultado"),
            (None, "resultado"),
            ("¡¡¡???", "resultado"),
            ("日本語", "resultado"),
        ],
    )
    def test_nombre_saneado(self, titulo, esperado):
        assert formato.slug_titulo(titulo) == esperado

    def test_el_nombre_es_acotado_y_lleva_la_extension(self):
        nombre = formato.nombre_descarga({"metadatos": {"documento_titulo": "x" * 500}}, "csv")
        assert nombre == "nuevamente-" + "x" * 60 + ".csv"
        assert formato.nombre_descarga({"metadatos": {"documento_titulo": "Guía OCI"}}, "md") == "nuevamente-Guia-OCI.md"


class TestTiempoYChip:
    @pytest.mark.parametrize("segundos,esperado", [(12.34, "12,3 s"), (0, "0,0 s"), (2, "2,0 s"), (None, "No disponible"), (-1, "No disponible"), (True, "No disponible"), ("x", "No disponible")])
    def test_duracion(self, segundos, esperado):
        assert formato.texto_duracion(segundos) == esperado

    def test_chip_completado_en_el_titulo_del_contenido(self):
        html = componentes.titulo_contenido({"metadatos": {"formato_salida": "Flashcards", "perfil_destinatario": "Principiante"}})
        assert '<span class="nm-chip-ok">Completado</span>' in html

    def test_estilo_del_chip_y_del_slider(self):
        from frontend.estilos import CSS

        chip = CSS.split(".nm-chip-ok {")[1].split("}")[0]
        assert "#F4F4C6" in chip and "#3F3F00" in chip
        assert 'st-key-nm-card"] [data-testid="stSlider"]' in CSS or '[data-testid="stSlider"]' in CSS


@pytest.fixture
def at_con_resultado(monkeypatch):
    """AppTest con el cliente mockeado y una solicitud completa; `llamadas` cuenta cuántas veces se llamó a la API."""
    from streamlit.testing.v1 import AppTest, element_tree

    # AppTest 1.40 no sabe reponer el estado de un st.segmented_control de selección simple (busca un str entre protobufs).
    def indices(self):
        valor = self.value
        valores = [] if valor is None else valor if isinstance(valor, list) else [valor]
        contenidos = [o.content for o in self.options]
        return [contenidos.index(v) for v in valores]

    monkeypatch.setattr(element_tree.ButtonGroup, "indices", property(indices))

    llamadas = []

    def falsa(base_url, perfil, formato_salida, **kwargs):
        llamadas.append(perfil)
        return EXITO | {"metadatos": EXITO["metadatos"] | {"fecha_generacion": "2026-10-24T15:30:00Z", "fragmentos_usados": 3}}

    monkeypatch.setattr(cliente_api, "adaptar", falsa)
    at = AppTest.from_file("frontend/app.py", default_timeout=30).run()
    at.radio[0].set_value("Pegar texto").run()
    at.text_area[0].set_value("Una VCN es una red privada.").run()
    at.button(key="usar_ejemplo")  # el botón existe
    generar = [b for b in at.button if b.label == "Generar contenido"][0]
    generar.click().run()
    assert not at.exception and len(llamadas) == 1
    return at, llamadas


def _markdown(at):
    return " ".join(m.value for m in at.markdown)


def test_el_boton_de_ejemplo_completa_texto_y_titulo(app_sin_api):
    at = app_sin_api.run()
    assert at.radio[0].value == "Subir archivo"  # desde el modo archivo también funciona: cambia a "Pegar texto"
    at.button(key="usar_ejemplo").click().run()
    assert not at.exception
    assert at.radio[0].value == "Pegar texto"
    assert at.text_area[0].value == ejemplos.TEXTO_EJEMPLO
    assert at.text_input[0].value == ejemplos.TITULO_EJEMPLO
    assert "caracteres" in _markdown(at)


def test_resultado_con_slider_nota_tiempo_y_chip(at_con_resultado):
    at, _ = at_con_resultado
    assert at.slider[0].label == "¿Qué tan exigente querés ser al revisar?"
    assert (at.slider[0].min, at.slider[0].max, at.slider[0].step, at.slider[0].value) == (0.5, 0.95, 0.01, 0.72)
    assert "¿Por qué esta nota?" in [e.label for e in at.expander]
    texto = _markdown(at)
    assert "El umbral oficial es 0.72" in " ".join(c.value for c in at.caption)
    assert "Completado" in texto and "Tiempo de generación:" in texto and "Supera el umbral mínimo (0.72)" in texto
    assert "se compararon 1 unidad contra 3 fragmentos" in texto


def test_mover_el_slider_no_vuelve_a_llamar_a_la_api_ni_borra_el_resultado(at_con_resultado):
    at, llamadas = at_con_resultado
    at.slider[0].set_value(0.90).run()
    assert not at.exception
    assert len(llamadas) == 1
    texto = _markdown(at)
    assert "Con tu umbral (0.90): queda por debajo" in texto and "Tu umbral 0.90" in texto
    assert "Confianza normal" in texto  # la píldora oficial no depende del slider
    assert "¿Qué es una VCN?" in texto  # el resultado sigue ahí
    assert at.session_state["resultado"] is not None


def test_volver_al_umbral_oficial(at_con_resultado):
    at, llamadas = at_con_resultado
    assert at.button(key="umbral_oficial").disabled
    at.slider[0].set_value(0.60).run()
    assert not at.button(key="umbral_oficial").disabled
    at.button(key="umbral_oficial").click().run()
    assert not at.exception and not at.warning
    assert at.slider[0].value == 0.72 and len(llamadas) == 1
    assert "Supera el umbral mínimo (0.72)" in _markdown(at)


def test_sin_umbral_no_hay_slider(app_sin_api):
    sin_umbral = EXITO | {"evaluacion_calidad": {"anclaje_fuente_score": 0.8, "baja_confianza": False, "umbral": None}}
    at = _con_resultado(app_sin_api, sin_umbral)
    assert not at.exception and len(at.slider) == 0


def test_las_descargas_segun_el_formato(app_sin_api):
    at = _con_resultado(app_sin_api, EXITO)
    etiquetas = [b.proto.label for b in at.get("download_button")]
    assert etiquetas == ["Descargar CSV (compatible con Anki)", "Descargar JSON"]


def test_la_guia_ofrece_markdown(app_sin_api):
    at = _con_resultado(app_sin_api, GUIA)
    assert [b.proto.label for b in at.get("download_button")] == ["Descargar Markdown", "Descargar JSON"]
