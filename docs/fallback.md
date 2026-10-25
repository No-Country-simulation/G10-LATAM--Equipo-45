# Cadena de modelos con fallback

Implementada en `ClienteGemini` (`app/llm/gemini_client.py`); la cadena se arma en `Settings.gemini_cadena_modelos` (`app/config.py`).

## Orden de la cadena

`[GEMINI_MODEL] + GEMINI_MODEL_FALLBACKS`, en ese orden. Se ignoran espacios, entradas vacías, duplicados y el prefijo `models/`. Valores por defecto:

| Posición | Modelo | Origen |
|---|---|---|
| 1 | `gemini-3.5-flash` | `GEMINI_MODEL` |
| 2 | `gemini-3.8-flash` | `GEMINI_MODEL_FALLBACKS` |
| 3 | `gemini-3.5-flash-lite` | `GEMINI_MODEL_FALLBACKS` |

Con `GEMINI_MODEL_FALLBACKS` vacía no hay respaldos. `metadatos.modelo` de la respuesta informa el modelo que realmente respondió.

## Qué errores pasan al siguiente modelo

| Error | Significado |
|---|---|
| 503 (`ServiceUnavailable`) | alta demanda / servicio no disponible |
| 504 o deadline (`GatewayTimeout`, `DeadlineExceeded`) | timeout del proveedor |
| 429 (`TooManyRequests`, `ResourceExhausted`) | cuota excedida |
| 404 (`NotFound`) | modelo no disponible |
| tope de reloj propio de la llamada (`TiempoAgotado`) | la llamada no respetó su plazo |

## Qué errores NO cambian de modelo

- **400 / 401 / 403** (`InvalidArgument`, `Unauthenticated`, `PermissionDenied`): credenciales o pedido inválidos; otro modelo fallaría igual. Se normaliza a `ErrorDeLLM` y la API responde 503.
- Errores no clasificados (bugs propios) y respuesta vacía del modelo: también se normalizan a `ErrorDeLLM` sin probar otro modelo.
- **JSON inválido**: tiene su propio reintento en el orquestador (una vez más) y sigue con el modelo que respondió, no vuelve a probar uno que había fallado.

Si fallan todos los modelos, o se agota el presupuesto total, la API responde 503 `servicio_no_disponible`; el log lista cada modelo probado y el tipo de su error.

## Tiempos

| Variable | Por defecto | Qué acota |
|---|---|---|
| `GEMINI_TIMEOUT_S` | 45 s | cada solicitud a Gemini (deadline gRPC); el tope de reloj por llamada es este valor + 5 s |
| `GEMINI_TIMEOUT_TOTAL_S` | 100 s | toda la generación, todos los modelos incluidos: al agotarse no se prueban más |
| `GEMINI_BACKOFF_S` | 2 s | espera antes de pasar al siguiente modelo; no se espera tras un 404 |

Detalles de implementación relevantes:

- La librería `langchain-google-genai` 2.0.6 hace como mucho 2 intentos por llamada (no configurable), por eso el peor caso de un modelo es mayor que `GEMINI_TIMEOUT_S`; el presupuesto total lo acota.
- Los plazos se pasan por llamada (los del constructor se ignoran en la ruta síncrona) y se desactiva el reintento gRPC por defecto (`retry=None`), que ante un 503 insistía hasta 600 s.
- El frontend usa `API_TIMEOUT_S` = 150 s, por encima del peor caso del backend.

## Líneas de log

Formato real (de `app/logging_config.py` y `ClienteGemini`): un fallo con paso al siguiente modelo, y el modelo que finalmente respondió.

```
2026-10-24 15:30:01 INFO    app.llm.orquestador: paso=generacion inicio
2026-10-24 15:30:03 WARNING app.llm.gemini_client: paso=generacion modelo=gemini-3.5-flash intento=1 fallo=ServiceUnavailable pasando_a=gemini-3.8-flash
2026-10-24 15:30:07 INFO    app.llm.gemini_client: paso=generacion modelo_usado=gemini-3.8-flash intentos=2
```

(Las marcas de tiempo y los nombres de modelo del ejemplo son ilustrativos del formato.) Al terminar la solicitud, `app.api.servicio` registra `Adaptación completada: ... modelo_usado=<modelo> intentos_modelo=<n> duracion=<s>`. Si ningún modelo respondió: `pasando_a=ninguno` en el último intento y 503 al cliente.

En la corrida E2E del 25/10/2026 `gemini-3.5-flash` respondió 503 y la app pasó sola a `gemini-3.5-flash-lite` (`intentos=2`, 14,7 s totales); ver la sección de calidad del [README](../README.md#6-calidad-y-pruebas).

## Pruebas

`tests/test_fallback_modelos.py` (29 tests) cubre la cadena con modelos falsos, sin red; ver [test_plan.md](test_plan.md).
