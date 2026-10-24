"""
NM-18 — Caso de uso "adaptar un documento": une ingesta, orquestación, fidelidad y almacenamiento.

Flujo, en este orden:
    entrada -> archivo temporal -> ingerir_y_subir (original a OCI) -> Orquestador.adaptar
    -> VerificadorDeFidelidad.verificar -> subir_json (salida a OCI) -> RespuestaAdaptacion

Todas las dependencias se inyectan: los tests usan fakes y no necesitan red ni credenciales.

Estado entre solicitudes: ninguno. El Orquestador indexa el documento en el vector store usando
`nombre_archivo` como clave de filtro; con dos solicitudes simultáneas del mismo nombre (o el mismo
documento subido dos veces) se pisarían los chunks y una respuesta se armaría con fragmentos de la otra.
Por eso cada solicitud usa una clave propia ("<uuid corto>-<nombre saneado>") y, al terminar, se
elimina ese documento del vector store (ya con la respuesta armada, o aunque haya fallado). La API
no acumula documentos ni depende de lo que haya quedado de una corrida anterior.
"""

import logging
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.api.errores import ErrorDeEntrada
from app.api.schemas import (
    AlmacenamientoOci,
    EvaluacionCalidad,
    Flashcard,
    GuiaPractica,
    Metadatos,
    PasoGuia,
    RespuestaAdaptacion,
    ResultadoAlmacenamiento,
    SolicitudAdaptacion,
)
from app.config import settings
from app.ingesta.subida import ingerir_y_subir
from app.llm.fidelidad import VerificadorDeFidelidad
from app.llm.orquestador import Orquestador, ResultadoOrquestacion
from app.llm.prompts import FormatoSalida
from app.oci.almacenamiento import Almacenamiento, ResultadoSubida, sanitizar_nombre
from app.rag.embeddings import ErrorDeEmbeddings
from app.rag.vector_store import VectorStore
from app.trazas import paso

logger = logging.getLogger(__name__)

TITULO_POR_DEFECTO = "documento"
NOMBRE_TEXTO_PEGADO = "documento.txt"
MOTIVO_FIDELIDAD_NO_VERIFICADA = "no se pudo verificar la fidelidad"


def _a_resultado(subida: ResultadoSubida) -> ResultadoAlmacenamiento:
    if subida.ruta_local:
        # La ruta del servidor queda solo en el log: no se devuelve en la respuesta HTTP.
        logger.info("Archivo %s guardado en disco local: %s", subida.objeto_id, subida.ruta_local)
    return ResultadoAlmacenamiento(
        bucket=subida.bucket, objeto_id=subida.objeto_id, status_upload=subida.status_upload
    )


class ServicioDeAdaptacion:
    def __init__(
        self,
        orquestador: Orquestador,
        verificador: VerificadorDeFidelidad,
        almacenamiento: Almacenamiento,
        vector_store: VectorStore,
        modelo: str | None = None,
    ):
        self._orquestador = orquestador
        self._verificador = verificador
        self._almacenamiento = almacenamiento
        self._vector_store = vector_store
        self._modelo = modelo or settings.gemini_model

    def adaptar(self, solicitud: SolicitudAdaptacion) -> RespuestaAdaptacion:
        """
        Raises:
            ErrorDeEntrada: documento sin texto útil (ej. PDF escaneado).
            ErrorDeIngesta, ErrorDeLLM, ErrorDeOrquestacion, ErrorDeEmbeddings, ErrorDeAlmacenamiento:
                se propagan; los traducen los manejadores de errores (app/api/errores.py).
            Un ErrorDeEmbeddings de la verificación de fidelidad NO sube: se degrada la evaluación.
        """
        inicio = time.perf_counter()
        nombre_archivo = solicitud.nombre_archivo
        titulo = solicitud.documento_titulo or nombre_archivo or TITULO_POR_DEFECTO

        # Solo metadatos de la solicitud: nunca el contenido ni el nombre del documento.
        logger.info(
            "Solicitud: perfil=%s formato=%s origen=%s",
            solicitud.perfil_destinatario.value,
            solicitud.formato_salida.value,
            "archivo" if solicitud.contenido_archivo is not None else "texto",
        )
        with tempfile.TemporaryDirectory(prefix="nuevamente_") as carpeta:
            with paso(logger, "guardar_entrada"):
                ruta = self._escribir_entrada(Path(carpeta), solicitud)
            documento, subida_original = ingerir_y_subir(ruta, self._almacenamiento)  # pasos: ingesta, subida_original

        if subida_original is None or documento.esta_vacio:
            raise ErrorDeEntrada(
                "El documento no contiene texto que se pueda procesar. "
                "Si es un PDF escaneado (imágenes), necesitás una versión con texto seleccionable.",
                campo="archivo" if nombre_archivo else "documento_contenido",
                codigo="documento_sin_texto",
            )

        resultado = self._orquestar(solicitud, titulo, documento.texto, ruta.name)
        evaluacion = self._evaluar(resultado)

        respuesta = RespuestaAdaptacion(
            metadatos=Metadatos(
                documento_titulo=titulo,
                perfil_destinatario=resultado.perfil,
                formato_salida=resultado.formato,
                nombre_archivo=nombre_archivo,
                fragmentos_usados=len(resultado.fragmentos_usados),
                nicho_sector=solicitud.nicho_sector,
                nivel_detalle=solicitud.nivel_detalle,
                fecha_generacion=datetime.now(timezone.utc),
                modelo=self._modelo,
            ),
            contenido_adaptado=self._dar_forma(resultado),
            evaluacion_calidad=evaluacion,
            almacenamiento_oci=AlmacenamientoOci(documento_original=_a_resultado(subida_original)),
        )

        # El JSON subido no puede incluir su propio objeto_id: se sube con salida_json=null y recién
        # después se completa en la respuesta.
        with paso(logger, "subida_json"):
            subida_json = self._almacenamiento.subir_json(
                f"adaptacion-{Path(ruta.name).stem}", respuesta.model_dump(mode="json")
            )
        respuesta.almacenamiento_oci.salida_json = _a_resultado(subida_json)

        logger.info(
            "Adaptación completada: perfil=%s formato=%s duracion=%.2fs status_upload=%s/%s baja_confianza=%s",
            resultado.perfil.value,
            resultado.formato.value,
            time.perf_counter() - inicio,
            subida_original.status_upload,
            subida_json.status_upload,
            evaluacion.baja_confianza,
        )
        return respuesta

    # --- Pasos internos ---

    @staticmethod
    def _escribir_entrada(carpeta: Path, solicitud: SolicitudAdaptacion) -> Path:
        """
        Guarda la entrada en un archivo temporal para reusar los loaders (que leen de disco).

        El archivo se nombra con el nombre saneado del original (así el objeto de OCI queda legible y
        el nombre del usuario nunca se usa como ruta): se conserva solo la extensión, ya validada.
        """
        if solicitud.contenido_archivo is not None:
            nombre = solicitud.nombre_archivo or ""
            extension = "." + nombre.rsplit(".", 1)[-1].lower()
            ruta = carpeta / f"{sanitizar_nombre(nombre.rsplit('.', 1)[0])}{extension}"
            ruta.write_bytes(solicitud.contenido_archivo)
        else:
            ruta = carpeta / NOMBRE_TEXTO_PEGADO
            ruta.write_text(solicitud.documento_contenido or "", encoding="utf-8")
        return ruta

    def _orquestar(
        self, solicitud: SolicitudAdaptacion, titulo: str, texto: str, nombre_seguro: str
    ) -> ResultadoOrquestacion:
        # Clave única por solicitud en el vector store (ver docstring del módulo).
        clave = f"{uuid.uuid4().hex[:8]}-{nombre_seguro}"
        try:
            return self._orquestador.adaptar(
                nombre_archivo=clave,
                documento_titulo=titulo,
                documento_contenido=texto,
                perfil=solicitud.perfil_destinatario,
                formato=solicitud.formato_salida,
            )
        finally:
            try:
                with paso(logger, "limpieza"):
                    self._vector_store.eliminar_documento(clave)
            except Exception:  # noqa: BLE001 — una limpieza fallida no debe tapar la respuesta ni el error original
                logger.exception("No se pudo eliminar el documento %s del vector store", clave)

    def _evaluar(self, resultado: ResultadoOrquestacion) -> EvaluacionCalidad:
        """Verifica el anclaje a la fuente; si los embeddings fallan, degrada en vez de tumbar la respuesta."""
        try:
            with paso(logger, "fidelidad"):
                fidelidad = self._verificador.verificar(
                    resultado.items, resultado.formato, resultado.fragmentos_usados
                )
        except ErrorDeEmbeddings as e:
            logger.error("No se pudo verificar la fidelidad: %s", e)
            return EvaluacionCalidad(
                anclaje_fuente_score=None, baja_confianza=True, motivo=MOTIVO_FIDELIDAD_NO_VERIFICADA
            )
        return EvaluacionCalidad(
            anclaje_fuente_score=fidelidad.anclaje_fuente_score,
            baja_confianza=fidelidad.baja_confianza,
            umbral=fidelidad.umbral,
            motivo=fidelidad.motivo or None,
        )

    @staticmethod
    def _dar_forma(resultado: ResultadoOrquestacion) -> list[Flashcard] | GuiaPractica:
        if resultado.formato == FormatoSalida.FLASHCARDS:
            return [Flashcard(**item) for item in resultado.items]
        return GuiaPractica(pasos=[PasoGuia(**item) for item in resultado.items])
