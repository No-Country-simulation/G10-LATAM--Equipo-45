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
from frontend import cliente_api, formato
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


# --------------------------------------------------------------------------------------
# Humo de la UI
# --------------------------------------------------------------------------------------


def test_la_app_arranca_con_la_api_mockeada(monkeypatch):
    from streamlit.testing.v1 import AppTest

    def no_debe_llamarse(*args, **kwargs):
        raise AssertionError("la app no debe llamar a la API al arrancar")

    monkeypatch.setattr(cliente_api, "adaptar", no_debe_llamarse)
    at = AppTest.from_file("frontend/app.py", default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "NuevaMente"
    assert [b.label for b in at.button] == ["Generar contenido"]
    assert at.selectbox[0].options == list(formato.PERFILES)
    assert at.selectbox[1].options == list(formato.FORMATOS)
