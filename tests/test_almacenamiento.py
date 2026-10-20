"""
NM-12 / NM-22 — Tests de Almacenamiento (subida a OCI con fallback a disco local).

Usa un cliente falso (FakeClienteDeObjetos) en vez del SDK de OCI: los tests corren sin red ni
credenciales. Los errores del SDK (ServiceError, RequestException) sí son los reales, para probar
que el fallback atrapa lo que OCI realmente lanza.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import oci
import pytest

from app.oci.almacenamiento import Almacenamiento, ErrorDeAlmacenamiento, ResultadoSubida, sanitizar_nombre

BUCKET = "bucket-test"
NAMESPACE = "ns-test"
AHORA = datetime(2026, 10, 20, 15, 30, 45, 123456, tzinfo=timezone.utc)
MARCA = "20261020T153045123456Z"


class FakeClienteDeObjetos:
    """Guarda lo que se sube en memoria; puede simular un fallo configurable."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.objetos: dict[str, bytes] = {}
        self.llamadas_put: list[dict] = []

    def put_object(self, namespace_name, bucket_name, object_name, put_object_body, **kwargs):
        if self.error:
            raise self.error
        self.llamadas_put.append(
            {"namespace": namespace_name, "bucket": bucket_name, "objeto": object_name, **kwargs}
        )
        self.objetos[object_name] = put_object_body

    def get_object(self, namespace_name, bucket_name, object_name, **kwargs):
        if self.error:
            raise self.error
        return SimpleNamespace(data=SimpleNamespace(content=self.objetos[object_name]))


def _service_error(status: int) -> oci.exceptions.ServiceError:
    return oci.exceptions.ServiceError(status, f"Code{status}", {}, f"mensaje simulado {status}")


def _almacenamiento(tmp_path, cliente=None, **kwargs) -> Almacenamiento:
    return Almacenamiento(
        cliente=cliente,
        carpeta_local=tmp_path / "local",
        bucket=kwargs.pop("bucket", BUCKET),
        namespace=kwargs.pop("namespace", NAMESPACE),
        reloj=lambda: AHORA,
        **kwargs,
    )


class TestSubidaExitosa:
    def test_sube_a_oci_con_status_exito_y_objeto_id_correcto(self, tmp_path):
        cliente = FakeClienteDeObjetos()
        almacenamiento = _almacenamiento(tmp_path, cliente)

        resultado = almacenamiento.subir_documento("manual.pdf", b"contenido", "application/pdf")

        assert resultado == ResultadoSubida(
            bucket=BUCKET, objeto_id=f"documentos/{MARCA}-manual.pdf", status_upload="exito", ruta_local=None
        )
        assert cliente.objetos[resultado.objeto_id] == b"contenido"
        assert cliente.llamadas_put[0]["namespace"] == NAMESPACE
        assert cliente.llamadas_put[0]["bucket"] == BUCKET
        assert cliente.llamadas_put[0]["content_type"] == "application/pdf"

    def test_subida_exitosa_no_escribe_en_disco(self, tmp_path):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos())

        almacenamiento.subir_documento("manual.pdf", b"x")

        assert not (tmp_path / "local").exists()


class TestFallbackALocal:
    def test_oci_sin_configurar_guarda_en_local_como_pendiente_oci(self, tmp_path, caplog):
        almacenamiento = _almacenamiento(tmp_path, bucket="", namespace="")

        with caplog.at_level("WARNING"):
            resultado = almacenamiento.subir_documento("manual.pdf", b"contenido")

        assert resultado.status_upload == "pendiente_oci"
        assert resultado.objeto_id == f"documentos/{MARCA}-manual.pdf"
        assert resultado.ruta_local == str(
            (tmp_path / "local" / "documentos" / f"{MARCA}-manual.pdf").resolve()
        )
        assert (tmp_path / "local" / resultado.objeto_id).read_bytes() == b"contenido"
        assert "OCI_BUCKET_NAME" in caplog.text

    def test_sin_cliente_inyectado_y_sin_config_de_oci_cae_a_local(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.oci.almacenamiento.settings.oci_region", "")
        almacenamiento = _almacenamiento(tmp_path)  # bucket y namespace presentes, pero sin región

        resultado = almacenamiento.subir_documento("a.txt", b"hola")

        assert resultado.status_upload == "pendiente_oci"

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_service_error_cae_a_local(self, tmp_path, status, caplog):
        cliente = FakeClienteDeObjetos(error=_service_error(status))
        almacenamiento = _almacenamiento(tmp_path, cliente)

        with caplog.at_level("WARNING"):
            resultado = almacenamiento.subir_documento("manual.pdf", b"contenido")

        assert resultado.status_upload == "pendiente_oci"
        assert (tmp_path / "local" / resultado.objeto_id).read_bytes() == b"contenido"
        assert str(status) in caplog.text

    @pytest.mark.parametrize(
        "error",
        [oci.exceptions.RequestException("sin red"), oci.exceptions.ConnectTimeout("timeout"), ConnectionError("caído")],
    )
    def test_error_de_red_cae_a_local(self, tmp_path, error):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=error))

        resultado = almacenamiento.subir_documento("manual.pdf", b"contenido")

        assert resultado.status_upload == "pendiente_oci"
        assert (tmp_path / "local" / resultado.objeto_id).exists()

    def test_falla_oci_y_falla_el_disco_lanza_error_de_almacenamiento(self, tmp_path):
        # La "carpeta local" es en realidad un archivo: crear subcarpetas adentro es imposible.
        archivo = tmp_path / "no_es_carpeta"
        archivo.write_text("x")
        almacenamiento = Almacenamiento(
            cliente=FakeClienteDeObjetos(error=_service_error(403)),
            carpeta_local=archivo,
            bucket=BUCKET,
            namespace=NAMESPACE,
            reloj=lambda: AHORA,
        )

        with pytest.raises(ErrorDeAlmacenamiento, match="403"):
            almacenamiento.subir_documento("manual.pdf", b"contenido")


ERRORES_ESPERADOS = [
    pytest.param(_service_error(401), id="service-401"),
    pytest.param(_service_error(403), id="service-403"),
    pytest.param(_service_error(404), id="service-404"),
    pytest.param(oci.exceptions.ConfigFileNotFound("no hay config"), id="config-inexistente"),
    pytest.param(oci.exceptions.ProfileNotFound("no hay perfil"), id="perfil-inexistente"),
    pytest.param(oci.exceptions.InvalidConfig({"user": "falta"}), id="config-invalida"),
    pytest.param(oci.exceptions.InvalidKeyFilePath("no existe el .pem"), id="key-file-path"),
    pytest.param(oci.exceptions.InvalidPrivateKey("clave inválida"), id="clave-privada-invalida"),
    pytest.param(oci.exceptions.RequestException("sin red"), id="request-exception"),
    pytest.param(oci.exceptions.ConnectTimeout("timeout"), id="connect-timeout"),
    pytest.param(ConnectionError("caído"), id="connection-error"),
    pytest.param(TimeoutError("timeout"), id="timeout-error"),
    pytest.param(FileNotFoundError("no se encuentra el .pem"), id="os-error"),
]
BUGS = [pytest.param(TypeError("bug"), id="type-error"), pytest.param(AttributeError("bug"), id="attribute-error")]


class TestSoloLosErroresEsperadosActivanElFallback:
    @pytest.mark.parametrize("error", ERRORES_ESPERADOS)
    def test_subir_documento_con_error_esperado_cae_a_local(self, tmp_path, error):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=error))

        resultado = almacenamiento.subir_documento("a.pdf", b"x")

        assert resultado.status_upload == "pendiente_oci"
        assert (tmp_path / "local" / resultado.objeto_id).read_bytes() == b"x"

    @pytest.mark.parametrize("error", ERRORES_ESPERADOS)
    def test_subir_json_con_error_esperado_cae_a_local(self, tmp_path, error):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=error))

        assert almacenamiento.subir_json("r", {"a": 1}).status_upload == "pendiente_oci"

    @pytest.mark.parametrize("error", ERRORES_ESPERADOS)
    def test_descargar_con_error_esperado_lee_la_copia_local(self, tmp_path, error):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=error))
        resultado = almacenamiento.subir_documento("a.pdf", b"x")

        assert almacenamiento.descargar(resultado.objeto_id) == b"x"

    def test_archivo_de_config_de_oci_inexistente_cae_a_local(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.oci.almacenamiento.settings.oci_region", "sa-saopaulo-1")
        monkeypatch.setattr(oci.config, "DEFAULT_LOCATION", str(tmp_path / "no_existe" / "config"))
        almacenamiento = _almacenamiento(tmp_path)  # sin cliente: intenta crear el real

        assert almacenamiento.subir_documento("a.pdf", b"x").status_upload == "pendiente_oci"

    @pytest.mark.parametrize("error", BUGS)
    def test_subir_documento_con_bug_sube_la_excepcion_y_no_escribe_nada(self, tmp_path, error):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=error))

        with pytest.raises(type(error)):
            almacenamiento.subir_documento("a.pdf", b"x")

        assert not (tmp_path / "local").exists()

    @pytest.mark.parametrize("error", BUGS)
    def test_subir_json_con_bug_sube_la_excepcion_y_no_escribe_nada(self, tmp_path, error):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=error))

        with pytest.raises(type(error)):
            almacenamiento.subir_json("r", {"a": 1})

        assert not (tmp_path / "local").exists()

    @pytest.mark.parametrize("error", BUGS)
    def test_descargar_con_bug_sube_la_excepcion(self, tmp_path, error):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=error))

        with pytest.raises(type(error)):
            almacenamiento.descargar("documentos/a.pdf")

    def test_el_warning_incluye_tipo_y_mensaje_de_la_causa(self, tmp_path, caplog):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=TimeoutError("se agotó")))

        with caplog.at_level("WARNING"):
            almacenamiento.subir_documento("a.pdf", b"x")

        assert "TimeoutError" in caplog.text and "se agotó" in caplog.text


class TestSanitizacionDeNombres:
    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            ("../../etc/passwd", "passwd"),
            ("/etc/passwd", "passwd"),
            ("..\\..\\windows\\system32\\x.pdf", "x.pdf"),
            ("..", "archivo"),
            ("...pdf", "pdf"),
            ("mi guía técnica (v2).pdf", "mi_guia_tecnica_v2.pdf"),
            ("", "archivo"),
        ],
    )
    def test_sanitizar_nombre(self, entrada, esperado):
        assert sanitizar_nombre(entrada) == esperado

    def test_nombre_con_traversal_no_escapa_de_la_carpeta_local(self, tmp_path):
        almacenamiento = _almacenamiento(tmp_path, bucket="", namespace="")

        resultado = almacenamiento.subir_documento("../../../evil.txt", b"x")

        assert resultado.objeto_id == f"documentos/{MARCA}-evil.txt"
        assert not (tmp_path / "evil.txt").exists()
        assert (tmp_path / "local" / "documentos" / f"{MARCA}-evil.txt").exists()

    def test_nombre_con_ruta_absoluta_no_llega_a_la_clave_de_oci(self, tmp_path):
        cliente = FakeClienteDeObjetos()
        almacenamiento = _almacenamiento(tmp_path, cliente)

        resultado = almacenamiento.subir_documento("/tmp/secreto/doc.md", b"x")

        assert resultado.objeto_id == f"documentos/{MARCA}-doc.md"
        assert list(cliente.objetos) == [resultado.objeto_id]


class TestSubirJson:
    def test_dict_se_serializa_con_tildes_legibles_y_prefijo_salidas(self, tmp_path):
        cliente = FakeClienteDeObjetos()
        almacenamiento = _almacenamiento(tmp_path, cliente)

        resultado = almacenamiento.subir_json("resultado", {"título": "Introducción", "n": 1})

        assert resultado.status_upload == "exito"
        assert resultado.objeto_id == f"salidas/{MARCA}-resultado.json"
        cuerpo = cliente.objetos[resultado.objeto_id].decode("utf-8")
        assert "Introducción" in cuerpo  # ensure_ascii=False: sin ó
        assert json.loads(cuerpo) == {"título": "Introducción", "n": 1}
        assert cliente.llamadas_put[0]["content_type"] == "application/json; charset=utf-8"

    def test_str_se_sube_tal_cual(self, tmp_path):
        cliente = FakeClienteDeObjetos()
        almacenamiento = _almacenamiento(tmp_path, cliente)

        resultado = almacenamiento.subir_json("salida.json", '{"a": 1}')

        assert resultado.objeto_id == f"salidas/{MARCA}-salida.json"
        assert cliente.objetos[resultado.objeto_id] == b'{"a": 1}'

    def test_json_con_oci_caido_cae_a_local(self, tmp_path):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=_service_error(401)))

        resultado = almacenamiento.subir_json("r", {"a": 1})

        assert resultado.status_upload == "pendiente_oci"
        assert json.loads((tmp_path / "local" / resultado.objeto_id).read_text(encoding="utf-8")) == {"a": 1}


class TestDescargar:
    def test_descarga_desde_oci(self, tmp_path):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos())
        resultado = almacenamiento.subir_documento("manual.pdf", b"contenido")

        assert almacenamiento.descargar(resultado.objeto_id) == b"contenido"

    def test_descarga_la_copia_local_si_el_objeto_quedo_pendiente(self, tmp_path):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=_service_error(404)))
        resultado = almacenamiento.subir_documento("manual.pdf", b"contenido")

        assert almacenamiento.descargar(resultado.objeto_id) == b"contenido"

    def test_objeto_inexistente_lanza_error_de_almacenamiento(self, tmp_path):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos(error=_service_error(404)))

        with pytest.raises(ErrorDeAlmacenamiento):
            almacenamiento.descargar("documentos/no-existe.pdf")

    @pytest.mark.parametrize("objeto_id", ["../secreto", "/etc/passwd", "documentos/../../x", ""])
    def test_objeto_id_malicioso_se_rechaza(self, tmp_path, objeto_id):
        almacenamiento = _almacenamiento(tmp_path, FakeClienteDeObjetos())

        with pytest.raises(ErrorDeAlmacenamiento, match="inválido"):
            almacenamiento.descargar(objeto_id)
