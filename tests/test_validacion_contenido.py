"""Validación de contenido (N4, N5): texto sin contenido útil o demasiado corto. Unitarios, sin fakes."""

import pytest

from app.config import Settings
from app.ingesta.subida import ingerir_y_subir
from app.ingesta.validacion import (
    CODIGO_MUY_CORTO,
    CODIGO_SIN_CONTENIDO,
    MENSAJE_SIN_CONTENIDO,
    evaluar_contenido,
)

MIN = 200
FRASE = "Las redes virtuales conectan recursos de la nube. "


def texto_de(n: int) -> str:
    """Texto normal de exactamente n caracteres (sin espacios al final)."""
    return (FRASE * (n // len(FRASE) + 1))[: n - 1] + "a"


def test_el_helper_mide_lo_que_dice():
    assert len(texto_de(MIN)) == MIN and len(texto_de(MIN - 1)) == MIN - 1


def test_el_minimo_por_defecto_es_200(monkeypatch):
    monkeypatch.delenv("MIN_CHARS_DOCUMENTO", raising=False)
    assert Settings(_env_file=None).min_chars_documento == 200


def test_el_minimo_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("MIN_CHARS_DOCUMENTO", "350")
    assert Settings(_env_file=None).min_chars_documento == 350


@pytest.mark.parametrize("texto", ["", "   \n\t "])
def test_vacio_no_se_juzga_aca(texto):
    assert evaluar_contenido(texto, MIN) is None  # lo cubre el flujo existente de "documento_sin_texto"


def test_solo_simbolos_corto():
    problema = evaluar_contenido("asdnasdndneedc ad@####", MIN)
    assert problema.codigo == CODIGO_SIN_CONTENIDO and problema.mensaje == MENSAJE_SIN_CONTENIDO


@pytest.mark.parametrize("texto", ["@#$%^&*() " * 100, "1234567890 " * 50, "a@#$%&/() " * 100])
def test_solo_simbolos_o_numeros_largos_se_rechazan_por_proporcion(texto):
    assert len(texto) > MIN
    assert evaluar_contenido(texto, MIN).codigo == CODIGO_SIN_CONTENIDO


def test_25_caracteres_se_rechaza_por_falta_de_texto():
    texto = "Hola, esto es una prueba."
    assert len(texto) == 25
    assert evaluar_contenido(texto, MIN).codigo == CODIGO_SIN_CONTENIDO  # 19 letras (< 50)


def test_limite_exacto():
    assert evaluar_contenido(texto_de(MIN - 1), MIN).codigo == CODIGO_MUY_CORTO
    assert evaluar_contenido(texto_de(MIN), MIN) is None


def test_con_letras_suficientes_pero_corto_es_muy_corto():
    texto = texto_de(120)  # ~100 letras
    problema = evaluar_contenido(texto, MIN)
    assert problema.codigo == CODIGO_MUY_CORTO and "200" in problema.mensaje


def test_el_relleno_en_blanco_no_cuenta():
    assert evaluar_contenido("hola mundo" + " \n\n  " * 200, MIN) is not None  # ~9 letras, no ~1000 caracteres


def test_texto_normal_con_codigo_y_tildes_pasa():
    texto = "git checkout -b feature/nueva-rama && git push -u origin HEAD. " * 6 + "Además, ¿qué pasa con la integración?"
    assert evaluar_contenido(texto, MIN) is None


def test_se_exigen_50_letras_o_el_minimo_si_es_menor():
    texto = "abcde fghij klmno"  # 15 letras
    assert evaluar_contenido(texto, 200).codigo == CODIGO_SIN_CONTENIDO
    assert evaluar_contenido(texto, 15) is None  # min_chars=15: bajar el mínimo apaga la regla de letras


def test_un_documento_rechazado_no_se_sube(tmp_path):
    class Espia:
        def subir_documento(self, *a, **k):
            raise AssertionError("no debe subirse")

    class Rechazo(Exception):
        pass

    def validar(doc):
        raise Rechazo

    archivo = tmp_path / "corto.txt"
    archivo.write_text("Hola, esto es una prueba", encoding="utf-8")
    with pytest.raises(Rechazo):
        ingerir_y_subir(archivo, Espia(), validar=validar)
