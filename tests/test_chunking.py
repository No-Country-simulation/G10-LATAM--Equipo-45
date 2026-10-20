"""NM-14 — Tests unitarios de chunking (NM-09)."""

import pytest

from app.ingesta.models import DocumentoIngerido, FormatoOrigen
from app.rag.chunking import dividir_en_chunks


def _doc(texto: str) -> DocumentoIngerido:
    return DocumentoIngerido(texto=texto, nombre_archivo="test.md", formato_origen=FormatoOrigen.MARKDOWN)


class TestDividirEnChunks:
    def test_texto_vacio_devuelve_lista_vacia(self):
        assert dividir_en_chunks(_doc(""), tamano_chunk=100, overlap=10) == []

    def test_texto_mas_corto_que_el_chunk_devuelve_un_solo_chunk(self):
        chunks = dividir_en_chunks(_doc("Texto corto."), tamano_chunk=100, overlap=10)

        assert len(chunks) == 1
        assert chunks[0].texto == "Texto corto."
        assert chunks[0].indice == 0

    def test_texto_largo_se_divide_en_varios_chunks(self):
        texto = "Parrafo uno con bastante contenido. " * 20
        chunks = dividir_en_chunks(_doc(texto), tamano_chunk=100, overlap=20)

        assert len(chunks) > 1
        assert all(len(c.texto) <= 100 + 20 for c in chunks)  # +overlap por el prefijo agregado

    def test_indices_son_secuenciales_desde_cero(self):
        texto = "a " * 200
        chunks = dividir_en_chunks(_doc(texto), tamano_chunk=50, overlap=5)

        assert [c.indice for c in chunks] == list(range(len(chunks)))

    def test_chunk_ids_son_unicos_y_deterministicos(self):
        texto = "contenido repetido " * 50
        chunks = dividir_en_chunks(_doc(texto), tamano_chunk=80, overlap=10)

        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids))  # todos únicos
        assert ids[0] == "test.md::chunk_0"

    def test_overlap_mayor_o_igual_a_tamano_chunk_lanza_error(self):
        with pytest.raises(ValueError):
            dividir_en_chunks(_doc("algo"), tamano_chunk=50, overlap=50)

    def test_tamano_chunk_cero_o_negativo_lanza_error(self):
        with pytest.raises(ValueError):
            dividir_en_chunks(_doc("algo"), tamano_chunk=0, overlap=0)

    def test_respeta_parrafos_cuando_es_posible(self):
        texto = "Primer parrafo corto.\n\nSegundo parrafo corto.\n\nTercer parrafo corto."
        chunks = dividir_en_chunks(_doc(texto), tamano_chunk=200, overlap=0)

        # Entra todo en un chunk porque el tamano_chunk es generoso
        assert len(chunks) == 1
        assert "Primer parrafo" in chunks[0].texto
        assert "Tercer parrafo" in chunks[0].texto

    def test_overlap_empieza_en_limite_de_palabra_y_con_separador(self):
        texto = (
            "Una VCN permite aislar tus recursos. Cada VCN tiene su bloque CIDR propio y sus subredes. "
            "Las reglas de seguridad controlan el trafico entre subredes publicas y privadas dentro de la red."
        )
        chunks = dividir_en_chunks(_doc(texto), tamano_chunk=110, overlap=25)

        assert len(chunks) == 2
        # Antes del fix salía "IDR propio y sus subredesLas reglas...": palabra cortada y sin separador.
        assert chunks[1].texto.startswith("propio y sus subredes. Las reglas")

    def test_overlap_nunca_agrega_mas_de_overlap_caracteres(self):
        texto = " ".join(f"palabra{i:03d}" for i in range(300))
        tamano, overlap = 100, 30
        chunks = dividir_en_chunks(_doc(texto), tamano_chunk=tamano, overlap=overlap)

        assert len(chunks) > 1
        assert all(len(c.texto) <= tamano + overlap for c in chunks)

    def test_metadata_incluye_formato_origen(self):
        chunks = dividir_en_chunks(_doc("texto cualquiera"), tamano_chunk=100, overlap=0)
        assert chunks[0].metadata["formato_origen"] == FormatoOrigen.MARKDOWN.value


class TestPuntoEnCortesPorOracion:
    def test_corte_por_punto_no_pierde_el_punto(self):
        texto = "Oracion uno es larga. Oracion dos es larga."
        chunks = dividir_en_chunks(_doc(texto), tamano_chunk=25, overlap=0)

        assert [c.texto for c in chunks] == ["Oracion uno es larga.", "Oracion dos es larga."]


class TestChunksSinContenido:
    def test_documento_con_solo_numeral_no_genera_chunks(self):
        assert dividir_en_chunks(_doc("#"), tamano_chunk=100, overlap=10) == []

    def test_chunk_sin_alfanumericos_se_descarta_y_los_indices_siguen_secuenciales(self):
        texto = "Texto uno\n\n#\n\nTexto dos"
        chunks = dividir_en_chunks(_doc(texto), tamano_chunk=9, overlap=0)

        assert [c.texto for c in chunks] == ["Texto uno", "Texto dos"]
        assert [c.indice for c in chunks] == [0, 1]
