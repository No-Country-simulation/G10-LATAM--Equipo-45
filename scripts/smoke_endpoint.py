"""
Smoke test MANUAL del endpoint POST /api/v1/adaptar con el servidor levantado. No es parte de pytest.

Envía UN documento de ejemplo (la misma fuente de scripts/smoke_gemini.py) en formato Flashcards y muestra
el status HTTP, un resumen del resultado y el score de anclaje. Hace UNA sola solicitud por corrida: la
cuota gratuita de Gemini es de 20 generaciones por día y la API reintenta una vez si el JSON sale mal,
así que una corrida puede gastar hasta 2.

Uso (con el servidor levantado y el .env completo):
    uvicorn app.api.main:app --reload          # en otra terminal
    python scripts/smoke_endpoint.py [URL_BASE]   # por defecto http://127.0.0.1:8000

Sale con código 0 si la API respondió 200, 1 si respondió un error o falló la solicitud y 2 si el
servidor no está levantado.
"""

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import httpx  # noqa: E402

from smoke_gemini import TEXTO_EJEMPLO  # noqa: E402

TIMEOUT_SEGUNDOS = 120  # la generación con Gemini puede tardar


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")

    try:
        salud = httpx.get(f"{base}/health", timeout=5)
    except httpx.TransportError:
        print(f"No se pudo conectar con {base}. Levantá el servidor: uvicorn app.api.main:app --reload")
        return 2
    print(f"GET /health -> {salud.status_code} {salud.text}")

    print("\nPOST /api/v1/adaptar (1 solicitud real; consume cuota de Gemini)...")
    try:
        respuesta = httpx.post(
            f"{base}/api/v1/adaptar",
            data={
                "perfil_destinatario": "Principiante",
                "formato_salida": "Flashcards",
                "documento_titulo": "Introducción a las VCN en OCI",
                "documento_contenido": TEXTO_EJEMPLO,
            },
            timeout=TIMEOUT_SEGUNDOS,
        )
    except httpx.HTTPError as e:
        print(f"FALLÓ la solicitud: {type(e).__name__}: {e}")
        return 1

    print(f"Status HTTP: {respuesta.status_code}")
    try:
        cuerpo = respuesta.json()
    except ValueError:
        print(f"La respuesta no es JSON: {respuesta.text[:200]}")
        return 1

    if respuesta.status_code != 200:
        print(f"ERROR de la API: [{cuerpo.get('codigo')}] {cuerpo.get('mensaje')}")
        for d in cuerpo.get("detalles") or []:
            print(f"  - {d['campo']}: {d['problema']}")
        return 1

    meta, calidad, oci = cuerpo["metadatos"], cuerpo["evaluacion_calidad"], cuerpo["almacenamiento_oci"]
    print(f"Modelo: {meta['modelo']}   Fragmentos usados: {meta['fragmentos_usados']}")
    print(f"Flashcards generadas: {len(cuerpo['contenido_adaptado'])}")
    print(json.dumps(cuerpo["contenido_adaptado"][:2], ensure_ascii=False, indent=2))
    print(f"\nScore de anclaje: {calidad['anclaje_fuente_score']}  (umbral {calidad['umbral']})   "
          f"baja_confianza: {calidad['baja_confianza']}")
    print("Nota: el score mide anclaje temático, no veracidad.")
    print(f"OCI original: {oci['documento_original']['status_upload']}   "
          f"OCI salida: {(oci['salida_json'] or {}).get('status_upload')}")
    print("\nResultado: TODO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
