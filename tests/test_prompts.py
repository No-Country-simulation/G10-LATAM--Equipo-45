"""NM-14 — Tests unitarios de los prompts base (NM-13)."""

import json

import pytest

from app.llm.orquestador import _validar_items
from app.llm.prompts import (
    _EJEMPLO_FEW_SHOT,
    _INSTRUCCION_POR_FORMATO,
    _ROL_POR_PERFIL,
    FormatoSalida,
    PerfilDestinatario,
    construir_prompt_sistema,
    construir_prompt_usuario,
)

COMBINACIONES = [(p, f) for p in PerfilDestinatario for f in FormatoSalida]


class TestConstruirPromptSistema:
    def test_hay_cuatro_combinaciones_de_perfil_y_formato(self):
        assert len(COMBINACIONES) == 4

    @pytest.mark.parametrize("perfil,formato", COMBINACIONES)
    def test_incluye_rol_formato_reglas_y_ejemplo(self, perfil, formato):
        prompt = construir_prompt_sistema(perfil, formato)

        assert _ROL_POR_PERFIL[perfil] in prompt
        assert _INSTRUCCION_POR_FORMATO[formato] in prompt
        assert "Reglas estrictas:" in prompt
        assert "JSON válido" in prompt
        assert _EJEMPLO_FEW_SHOT[formato] in prompt

    @pytest.mark.parametrize("perfil,formato", COMBINACIONES)
    def test_orden_rol_formato_reglas_ejemplo(self, perfil, formato):
        prompt = construir_prompt_sistema(perfil, formato)

        posiciones = [
            prompt.index(_ROL_POR_PERFIL[perfil]),
            prompt.index(_INSTRUCCION_POR_FORMATO[formato]),
            prompt.index("Reglas estrictas:"),
            prompt.index(_EJEMPLO_FEW_SHOT[formato]),
        ]
        assert posiciones == sorted(posiciones)

    def test_las_cuatro_combinaciones_generan_prompts_distintos(self):
        prompts = {construir_prompt_sistema(p, f) for p, f in COMBINACIONES}

        assert len(prompts) == 4

    def test_valores_de_los_enums_coinciden_con_el_contrato_del_endpoint(self):
        assert {p.value for p in PerfilDestinatario} == {"Principiante", "Lider Tecnico / Arquitecto"}
        assert {f.value for f in FormatoSalida} == {"Flashcards", "Guia Practica Paso a Paso"}


class TestFormaDeSalidaDeLaGuiaPractica:
    def test_instruccion_pide_un_objeto_con_la_clave_pasos(self):
        instruccion = _INSTRUCCION_POR_FORMATO[FormatoSalida.GUIA_PRACTICA]

        assert "objeto" in instruccion
        assert "'pasos'" in instruccion
        assert "'titulo'" in instruccion and "'detalle'" in instruccion

    def test_ejemplo_few_shot_es_un_objeto_con_lista_de_pasos(self):
        ejemplo = json.loads(_EJEMPLO_FEW_SHOT[FormatoSalida.GUIA_PRACTICA])

        assert list(ejemplo) == ["pasos"]
        assert all(set(paso) == {"titulo", "detalle"} for paso in ejemplo["pasos"])

    @pytest.mark.parametrize("formato", list(FormatoSalida))
    def test_el_ejemplo_few_shot_pasa_la_validacion_del_orquestador(self, formato):
        ejemplo = json.loads(_EJEMPLO_FEW_SHOT[formato])

        assert len(_validar_items(ejemplo, formato)) >= 1


class TestConstruirPromptUsuario:
    def test_incluye_titulo_y_contenido_del_documento(self):
        prompt = construir_prompt_usuario("Redes VCN", "Una VCN es una red privada.")

        assert "Documento fuente: Redes VCN" in prompt
        assert "Una VCN es una red privada." in prompt
