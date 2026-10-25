"""
NM-06 / NM-18 / NM-19 — Tests del API.

Todo con fakes: embeddings por palabras clave, un VectorStore sobre chromadb.EphemeralClient, un modelo de
chat guionado y un cliente de OCI falso (sin red, sin Gemini, sin credenciales). Se usa el
ServicioDeAdaptacion real con esas dependencias, inyectado vía app.dependency_overrides, para probar el
flujo completo de punta a punta sin tocar servicios externos.
"""

import json
import uuid

import chromadb
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import schemas
from app.api.dependencias import obtener_servicio
from app.api.main import app
from app.api.schemas import SolicitudAdaptacion
from app.api.servicio import ServicioDeAdaptacion
from app.config import settings
from app.llm import prompts
from app.llm.fidelidad import VerificadorDeFidelidad
from app.llm.gemini_client import ClienteGemini
from app.llm.orquestador import Orquestador
from app.oci.almacenamiento import Almacenamiento
from app.rag.embeddings import GeneradorDeEmbeddings
from app.rag.vector_store import VectorStore

PALABRAS_CLAVE = ["redes", "almacenamiento", "seguridad"]
TEXTO = "Las redes conectan recursos.\n\nEl almacenamiento guarda datos.\n\nLa seguridad protege todo."
FLASHCARDS_JSON = json.dumps([{"pregunta": "¿Qué es una VCN?", "respuesta": "Una red privada: redes y seguridad."}])
GUIA_JSON = json.dumps({"pasos": [{"titulo": "Crear la VCN", "detalle": "Configurar las redes."}]})

PERFIL = "Principiante"
FORMATO = "Flashcards"


class FakeModeloDeEmbeddings:
    def __init__(self, fallar: bool = False):
        self.fallar = fallar

    def embed_documents(self, textos):
        if self.fallar:
            raise RuntimeError("fallo simulado")
        return [[float(t.lower().count(p)) + 0.01 for p in PALABRAS_CLAVE] for t in textos]

    def embed_query(self, texto):
        return self.embed_documents([texto])[0]


class FakeModeloDeChat:
    def __init__(self, respuestas, excepcion=None):
        self.respuestas = list(respuestas)
        self.excepcion = excepcion

    def invocar(self, prompt_sistema, prompt_usuario):
        if self.excepcion:
            raise self.excepcion
        return self.respuestas.pop(0)


class FakeClienteOci:
    def __init__(self):
        self.objetos: dict[str, bytes] = {}

    def put_object(self, namespace_name, bucket_name, object_name, put_object_body, **kwargs):
        self.objetos[object_name] = put_object_body

    def get_object(self, *a, **k):  # pragma: no cover
        raise AssertionError


class VerificadorQueExplota:
    def verificar(self, *a, **k):
        raise RuntimeError("secreto interno en /ruta/privada/clave.pem")


@pytest.fixture
def store():
    return VectorStore(
        generador_embeddings=GeneradorDeEmbeddings(modelo=FakeModeloDeEmbeddings()),
        cliente=chromadb.EphemeralClient(),
        nombre_coleccion=f"test_{uuid.uuid4().hex}",
    )


@pytest.fixture
def oci_falso():
    return FakeClienteOci()


@pytest.fixture
def construir(store, oci_falso, tmp_path):
    """Fábrica de clientes HTTP: permite elegir las respuestas del chat y variantes de los fakes."""

    def _construir(respuestas=None, excepcion=None, verificador=None, almacenamiento=None):
        modelo = FakeModeloDeChat(respuestas or [FLASHCARDS_JSON], excepcion)
        servicio = ServicioDeAdaptacion(
            orquestador=Orquestador(store, ClienteGemini(modelo=modelo)),
            verificador=verificador
            or VerificadorDeFidelidad(GeneradorDeEmbeddings(modelo=FakeModeloDeEmbeddings()), umbral=0.5),
            almacenamiento=almacenamiento
            or Almacenamiento(cliente=oci_falso, carpeta_local=tmp_path, bucket="bucket-test", namespace="ns"),
            vector_store=store,
            modelo="modelo-fake",
        )
        app.dependency_overrides[obtener_servicio] = lambda: servicio
        return TestClient(app, raise_server_exceptions=False)

    yield _construir
    app.dependency_overrides.clear()


def _datos(**extra):
    datos = {"perfil_destinatario": PERFIL, "formato_salida": FORMATO}
    datos.update(extra)
    return datos


def _post_texto(cliente, texto=TEXTO, **extra):
    return cliente.post("/api/v1/adaptar", data=_datos(documento_contenido=texto, **extra))


def _post_archivo(cliente, nombre="manual.md", contenido=TEXTO.encode(), **extra):
    return cliente.post("/api/v1/adaptar", data=_datos(**extra), files={"archivo": (nombre, contenido)})


class TestHealth:
    def test_health_no_requiere_servicios(self):
        # Sin dependency_overrides: si tocara el servicio real intentaría abrir Chroma/Gemini/OCI.
        respuesta = TestClient(app).get("/health")

        assert respuesta.status_code == 200
        assert respuesta.json() == {"status": "ok"}

    def test_ruta_inexistente_usa_el_formato_de_error(self):
        respuesta = TestClient(app).get("/no-existe")

        assert respuesta.status_code == 404
        assert respuesta.json()["status"] == "error"
        assert respuesta.json()["codigo"] == "no_encontrado"


class TestCaminoFeliz:
    def test_flashcards_por_texto_forma_exacta(self, construir):
        cliente = construir()

        respuesta = _post_texto(cliente, documento_titulo="Guía de VCN", nicho_sector="Cloud", nivel_detalle="Didactico")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert set(cuerpo) == {"status", "metadatos", "contenido_adaptado", "evaluacion_calidad", "almacenamiento_oci"}
        assert cuerpo["status"] == "ok"
        assert cuerpo["contenido_adaptado"] == [
            {"pregunta": "¿Qué es una VCN?", "respuesta": "Una red privada: redes y seguridad."}
        ]
        meta = cuerpo["metadatos"]
        assert set(meta) == {
            "documento_titulo", "perfil_destinatario", "formato_salida", "nombre_archivo",
            "fragmentos_usados", "nicho_sector", "nivel_detalle", "fecha_generacion", "modelo",
        }
        assert meta["documento_titulo"] == "Guía de VCN"
        assert meta["perfil_destinatario"] == "Principiante"
        assert meta["formato_salida"] == "Flashcards"
        assert meta["nombre_archivo"] is None
        assert meta["fragmentos_usados"] >= 1
        assert (meta["nicho_sector"], meta["nivel_detalle"]) == ("Cloud", "Didactico")
        assert meta["fecha_generacion"].endswith("Z") or "+00:00" in meta["fecha_generacion"]
        assert meta["modelo"] == "modelo-fake"
        calidad = cuerpo["evaluacion_calidad"]
        assert set(calidad) == {"anclaje_fuente_score", "baja_confianza", "umbral", "motivo", "claridad_pedagogica"}
        assert 0.0 <= calidad["anclaje_fuente_score"] <= 1.0
        assert calidad["umbral"] == 0.5
        assert calidad["claridad_pedagogica"] is None

    def test_guia_practica_por_archivo_forma_exacta(self, construir):
        cliente = construir([GUIA_JSON])

        respuesta = _post_archivo(cliente, "guia.txt", formato_salida="Guia Practica Paso a Paso")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["contenido_adaptado"] == {"pasos": [{"titulo": "Crear la VCN", "detalle": "Configurar las redes."}]}
        assert cuerpo["metadatos"]["formato_salida"] == "Guia Practica Paso a Paso"
        assert cuerpo["metadatos"]["nombre_archivo"] == "guia.txt"
        assert cuerpo["metadatos"]["documento_titulo"] == "guia.txt"  # título por defecto: el nombre del archivo

    def test_titulo_por_defecto_en_texto_es_documento(self, construir):
        assert _post_texto(construir()).json()["metadatos"]["documento_titulo"] == "documento"

    def test_pdf_valido(self, construir, pdf_valido):
        respuesta = _post_archivo(construir(), "manual.pdf", pdf_valido.read_bytes())

        assert respuesta.status_code == 200
        assert respuesta.json()["metadatos"]["nombre_archivo"] == "manual.pdf"

    def test_sube_el_original_y_el_json_de_salida(self, construir, oci_falso):
        respuesta = _post_archivo(construir(), "manual.md")

        oci = respuesta.json()["almacenamiento_oci"]
        assert oci["documento_original"]["status_upload"] == "exito"
        assert oci["documento_original"]["objeto_id"].startswith("documentos/")
        assert oci["salida_json"]["objeto_id"].startswith("salidas/")
        assert oci["salida_json"]["bucket"] == "bucket-test"
        assert oci["documento_original"]["objeto_id"] in oci_falso.objetos
        subido = json.loads(oci_falso.objetos[oci["salida_json"]["objeto_id"]])
        assert subido["status"] == "ok"
        assert subido["almacenamiento_oci"]["salida_json"] is None  # un JSON no puede contener su propio id


class TestAlmacenamientoYEstado:
    def test_oci_caido_se_refleja_como_pendiente_oci_sin_fallar(self, construir, tmp_path):
        sin_oci = Almacenamiento(cliente=None, carpeta_local=tmp_path, bucket="", namespace="")

        respuesta = _post_texto(construir(almacenamiento=sin_oci))

        assert respuesta.status_code == 200
        oci = respuesta.json()["almacenamiento_oci"]
        assert oci["documento_original"]["status_upload"] == "pendiente_oci"
        assert oci["salida_json"]["status_upload"] == "pendiente_oci"
        assert "ruta_local" not in oci["documento_original"]
        assert "ruta_local" not in oci["salida_json"]

    def test_el_documento_se_elimina_del_vector_store_al_terminar(self, construir, store):
        cliente = construir()

        assert _post_texto(cliente).status_code == 200

        assert store.cantidad_indexada() == 0

    def test_el_documento_se_elimina_del_vector_store_aunque_falle_la_generacion(self, construir, store):
        cliente = construir(["no json", "tampoco"])

        assert _post_texto(cliente).status_code == 502

        assert store.cantidad_indexada() == 0

    def test_dos_solicitudes_con_el_mismo_nombre_usan_claves_distintas(self, construir, store, monkeypatch):
        cliente = construir([FLASHCARDS_JSON, FLASHCARDS_JSON])
        claves = []
        original = store.eliminar_documento
        monkeypatch.setattr(store, "eliminar_documento", lambda n: (claves.append(n), original(n))[1])

        _post_archivo(cliente, "mismo.md")
        _post_archivo(cliente, "mismo.md")

        # Cada solicitud borra su propia clave (la del Orquestador antes de indexar, más la de limpieza).
        propias = [c for c in claves if c.endswith("-mismo.md")]
        assert len(set(propias)) == 2


class TestSinRutasDelServidor:
    """Ninguna respuesta HTTP debe filtrar rutas del servidor (carpeta local, temporales, home)."""

    @staticmethod
    def _sin_rutas(respuesta, tmp_path):
        texto = respuesta.text
        assert "ruta_local" not in texto
        assert str(tmp_path) not in texto
        assert "nuevamente_" not in texto  # prefijo de la carpeta temporal
        assert "/tmp" not in texto and "/var/" not in texto and "/Users/" not in texto

    def test_exito_con_fallback_local(self, construir, tmp_path):
        sin_oci = Almacenamiento(cliente=None, carpeta_local=tmp_path, bucket="", namespace="")

        respuesta = _post_archivo(construir(almacenamiento=sin_oci))

        assert respuesta.status_code == 200
        assert respuesta.json()["almacenamiento_oci"]["documento_original"]["status_upload"] == "pendiente_oci"
        self._sin_rutas(respuesta, tmp_path)

    def test_exito_con_oci(self, construir, tmp_path):
        self._sin_rutas(_post_archivo(construir()), tmp_path)

    @pytest.mark.parametrize("caso", ["ilegible", "invalida", "llm", "inesperado"])
    def test_errores(self, construir, tmp_path, pdf_corrupto, caso):
        if caso == "ilegible":
            respuesta = _post_archivo(construir(), "roto.pdf", pdf_corrupto.read_bytes())
        elif caso == "invalida":
            respuesta = _post_archivo(construir(), "informe.docx")
        elif caso == "llm":
            respuesta = _post_texto(construir(excepcion=RuntimeError(f"fallo en {tmp_path}/x")))
        else:
            respuesta = _post_texto(construir(verificador=VerificadorQueExplota()))

        assert respuesta.status_code >= 400
        self._sin_rutas(respuesta, tmp_path)


class TestFidelidadDegradada:
    def test_error_de_embeddings_en_fidelidad_devuelve_200_degradado(self, construir):
        verificador = VerificadorDeFidelidad(GeneradorDeEmbeddings(modelo=FakeModeloDeEmbeddings(fallar=True)))

        respuesta = _post_texto(construir(verificador=verificador))

        assert respuesta.status_code == 200
        calidad = respuesta.json()["evaluacion_calidad"]
        assert calidad["anclaje_fuente_score"] is None
        assert calidad["baja_confianza"] is True
        assert calidad["motivo"] == "no se pudo verificar la fidelidad"
        assert respuesta.json()["contenido_adaptado"]  # el contenido generado se entrega igual


def _texto_de(n):
    """Texto normal de exactamente n caracteres."""
    base = "Las redes virtuales conectan recursos de la nube. "
    return (base * (n // len(base) + 1))[: n - 1] + "a"


class TestValidacionDeContenido:
    """N4 / N5: se rechaza con 422 antes de subir a OCI y de llamar al LLM (un LLM llamado daría 500 con este fake)."""

    @pytest.fixture(autouse=True)
    def _minimo_real(self, monkeypatch):
        monkeypatch.setattr(settings, "min_chars_documento", 200)

    @pytest.mark.parametrize(
        "texto, codigo",
        [
            ("asdnasdndneedc ad@####", "documento_sin_contenido_util"),
            ("@#$%^&*() " * 100, "documento_sin_contenido_util"),
            ("Hola, esto es una prueba", "documento_sin_contenido_util"),
            (_texto_de(120), "documento_muy_corto"),
            (_texto_de(199), "documento_muy_corto"),
        ],
    )
    def test_rechaza_con_422(self, construir, oci_falso, texto, codigo):
        cliente = construir(excepcion=AssertionError("el LLM no debe llamarse"))
        respuesta = _post_texto(cliente, texto)

        assert respuesta.status_code == 422
        cuerpo = respuesta.json()
        assert (cuerpo["status"], cuerpo["codigo"]) == ("error", codigo)
        assert cuerpo["detalles"] == [{"campo": "documento_contenido", "problema": cuerpo["mensaje"]}]
        assert oci_falso.objetos == {}  # ni el original ni el JSON se subieron

    def test_mensaje_de_sin_contenido(self, construir):
        mensaje = _post_texto(construir(), "asdnasdndneedc ad@####").json()["mensaje"]
        assert mensaje == "El documento no contiene texto suficiente para adaptar. Subí un material con al menos algunos párrafos."

    def test_en_el_limite_pasa(self, construir):
        assert _post_texto(construir(), _texto_de(200)).status_code == 200

    def test_un_archivo_corto_se_rechaza_y_apunta_al_campo_archivo(self, construir):
        respuesta = construir().post(
            "/api/v1/adaptar", data=_datos(), files={"archivo": ("a.txt", b"Hola, esto es una prueba")}
        )
        assert respuesta.status_code == 422
        assert respuesta.json()["detalles"][0]["campo"] == "archivo"

    def test_el_minimo_es_configurable(self, construir, monkeypatch):
        monkeypatch.setattr(settings, "min_chars_documento", 100)
        assert _post_texto(construir(), _texto_de(100)).status_code == 200
        assert _post_texto(construir(), _texto_de(99)).status_code == 422


class TestValidacionDeEntrada:
    @pytest.mark.parametrize("enviar", ["ninguno", "ambos"])
    def test_exactamente_uno_de_archivo_o_texto(self, construir, enviar):
        cliente = construir()
        kwargs = {"data": _datos()}
        if enviar == "ambos":
            kwargs["data"] = _datos(documento_contenido=TEXTO)
            kwargs["files"] = {"archivo": ("a.md", TEXTO.encode())}

        respuesta = cliente.post("/api/v1/adaptar", **kwargs)

        assert respuesta.status_code == 422
        cuerpo = respuesta.json()
        assert cuerpo["status"] == "error"
        assert cuerpo["codigo"] == "entrada_invalida"
        assert cuerpo["detalles"][0]["campo"] == "archivo / documento_contenido"

    def test_texto_en_blanco_cuenta_como_ausente(self, construir):
        respuesta = _post_texto(construir(), texto="   ")

        assert respuesta.status_code == 422

    def test_texto_en_blanco_junto_a_un_archivo_usa_el_archivo(self, construir):
        respuesta = construir().post(
            "/api/v1/adaptar", data=_datos(documento_contenido=""), files={"archivo": ("a.md", TEXTO.encode())}
        )

        assert respuesta.status_code == 200

    @pytest.mark.parametrize("campo", ["perfil_destinatario", "formato_salida"])
    def test_valor_fuera_del_enum_indica_el_campo(self, construir, campo):
        datos = _datos(documento_contenido=TEXTO)
        datos[campo] = "Inventado"

        respuesta = construir().post("/api/v1/adaptar", data=datos)

        assert respuesta.status_code == 422
        detalle = respuesta.json()["detalles"][0]
        assert detalle["campo"] == campo
        assert "Valores válidos" in detalle["problema"]
        assert "Inventado" not in respuesta.text  # no se devuelve el valor enviado

    @pytest.mark.parametrize("campo", ["perfil_destinatario", "formato_salida"])
    def test_campo_obligatorio_faltante(self, construir, campo):
        datos = _datos(documento_contenido=TEXTO)
        del datos[campo]

        respuesta = construir().post("/api/v1/adaptar", data=datos)

        assert respuesta.status_code == 422
        assert respuesta.json()["detalles"] == [{"campo": campo, "problema": "Este campo es obligatorio."}]

    def test_titulo_demasiado_largo(self, construir):
        respuesta = _post_texto(construir(), documento_titulo="x" * 201)

        assert respuesta.status_code == 422
        assert respuesta.json()["detalles"][0]["campo"] == "documento_titulo"

    def test_extension_no_soportada(self, construir):
        respuesta = _post_archivo(construir(), "informe.docx")

        assert respuesta.status_code == 422
        assert respuesta.json()["detalles"][0]["campo"] == "archivo"
        assert ".docx" in respuesta.json()["detalles"][0]["problema"]

    @pytest.mark.parametrize("contenido", [b"", b"  \n "])
    def test_archivo_vacio(self, construir, contenido):
        respuesta = _post_archivo(construir(), "vacio.txt", contenido)

        assert respuesta.status_code == 422
        assert respuesta.json()["detalles"][0] == {"campo": "archivo", "problema": "El archivo está vacío."}

    def test_pdf_corrupto(self, construir, pdf_corrupto):
        respuesta = _post_archivo(construir(), "roto.pdf", pdf_corrupto.read_bytes())

        assert respuesta.status_code == 422
        assert respuesta.json()["codigo"] == "documento_ilegible"
        assert "roto" not in respuesta.text and "/" not in respuesta.json()["mensaje"]

    def test_pdf_escaneado_sin_texto(self, construir, pdf_escaneado_sin_texto, oci_falso):
        respuesta = _post_archivo(construir(), "escaneado.pdf", pdf_escaneado_sin_texto.read_bytes())

        assert respuesta.status_code == 422
        assert respuesta.json()["codigo"] == "documento_sin_texto"
        assert oci_falso.objetos == {}

    def test_archivo_no_utf8(self, construir):
        respuesta = _post_archivo(construir(), "latin.txt", "ñandú".encode("latin-1") * 3)

        assert respuesta.status_code == 422
        assert respuesta.json()["codigo"] == "documento_ilegible"

    def test_archivo_demasiado_grande_es_413(self, construir, monkeypatch):
        monkeypatch.setattr("app.api.main.settings.max_upload_mb", 1)

        respuesta = _post_archivo(construir(), "grande.txt", b"a" * (1024 * 1024 + 1))

        assert respuesta.status_code == 413
        assert respuesta.json()["codigo"] == "documento_demasiado_grande"
        assert "1 MB" in respuesta.json()["mensaje"]

    def test_texto_demasiado_grande_es_413(self, construir, monkeypatch):
        monkeypatch.setattr("app.api.main.settings.max_upload_mb", 1)

        assert _post_texto(construir(), "a" * (1024 * 1024 + 1)).status_code == 413


class TestErroresDelPipeline:
    def test_error_de_llm_es_503(self, construir):
        respuesta = _post_texto(construir(excepcion=RuntimeError("429 rate limit key=AIza123")))

        assert respuesta.status_code == 503
        assert respuesta.json()["codigo"] == "servicio_no_disponible"
        assert "AIza123" not in respuesta.text and "429" not in respuesta.text

    def test_salida_invalida_del_modelo_es_502(self, construir):
        respuesta = _post_texto(construir(["no es json", "tampoco"]))

        assert respuesta.status_code == 502
        assert respuesta.json()["codigo"] == "respuesta_invalida_del_modelo"

    def test_error_de_embeddings_al_indexar_es_503(self, construir, store, monkeypatch):
        cliente = construir()
        store._generador = GeneradorDeEmbeddings(modelo=FakeModeloDeEmbeddings(fallar=True))

        assert _post_texto(cliente).status_code == 503

    def test_error_de_almacenamiento_es_500_amable(self, construir, tmp_path):
        class OciRoto:
            def put_object(self, *a, **k):
                raise OSError("disco lleno en /var/secreto")

        archivo_en_lugar_de_carpeta = tmp_path / "no_es_carpeta"
        archivo_en_lugar_de_carpeta.write_text("x")
        roto = Almacenamiento(
            cliente=OciRoto(), carpeta_local=archivo_en_lugar_de_carpeta, bucket="b", namespace="n"
        )

        respuesta = _post_texto(construir(almacenamiento=roto))

        assert respuesta.status_code == 500
        assert "secreto" not in respuesta.text and "no_es_carpeta" not in respuesta.text

    def test_excepcion_inesperada_es_500_generico_sin_detalles(self, construir):
        respuesta = _post_texto(construir(verificador=VerificadorQueExplota()))

        assert respuesta.status_code == 500
        cuerpo = respuesta.json()
        assert cuerpo["status"] == "error"
        assert cuerpo["codigo"] == "error_interno"
        assert "secreto" not in respuesta.text and "clave.pem" not in respuesta.text
        assert "Traceback" not in respuesta.text


class TestEsquemas:
    def test_los_enums_son_los_de_prompts(self):
        assert schemas.PerfilDestinatario is prompts.PerfilDestinatario
        assert schemas.FormatoSalida is prompts.FormatoSalida
        assert {p.value for p in schemas.PerfilDestinatario} == {"Principiante", "Lider Tecnico / Arquitecto"}

    def test_solicitud_valida_con_texto(self):
        s = SolicitudAdaptacion(perfil_destinatario=PERFIL, formato_salida=FORMATO, documento_contenido="hola")

        assert s.contenido_archivo is None

    def test_campos_opcionales_en_blanco_pasan_a_none(self):
        s = SolicitudAdaptacion(
            perfil_destinatario=PERFIL, formato_salida=FORMATO, documento_contenido="hola",
            documento_titulo="  ", nicho_sector="", nivel_detalle=" ",
        )

        assert (s.documento_titulo, s.nicho_sector, s.nivel_detalle) == (None, None, None)

    def test_ambos_o_ninguno_lanza_error(self):
        with pytest.raises(ValidationError):
            SolicitudAdaptacion(perfil_destinatario=PERFIL, formato_salida=FORMATO)
        with pytest.raises(ValidationError):
            SolicitudAdaptacion(
                perfil_destinatario=PERFIL, formato_salida=FORMATO,
                documento_contenido="x", nombre_archivo="a.md", contenido_archivo=b"x",
            )

    def test_respuesta_de_error_tiene_la_forma_del_contrato(self):
        e = schemas.ErrorRespuesta(codigo="c", mensaje="m")

        assert e.model_dump(exclude_none=True) == {"status": "error", "codigo": "c", "mensaje": "m"}
