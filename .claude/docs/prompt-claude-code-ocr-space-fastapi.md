# Prompt para Claude Code — Backend FastAPI proxy de OCR.space

> Copia todo lo que sigue (desde "Contexto" hasta el final) como prompt inicial en Claude Code.

---

## Contexto

Necesito un microservicio en **Python 3.12 + FastAPI** que actúe como proxy hacia la API de OCR de
**OCR.space** (`https://api.ocr.space/parse/image`). El servicio recibe un archivo (imagen o PDF),
lo prepara para cumplir los límites de OCR.space, lo envía, y devuelve una respuesta JSON
normalizada y fácil de consumir.

Antes de escribir código, lee la documentación oficial en https://ocr.space/ocrapi para confirmar
parámetros y formato de respuesta. Los datos clave ya verificados son:

- Endpoint POST: `https://api.ocr.space/parse/image`
- La API key va en el **header** `apikey`, NO como campo del form.
- Plan Free: **1 MB** por archivo, **3 páginas** máximo por PDF, 500 requests/día por IP.
- El body es `multipart/form-data`; el archivo va en el campo `file`.
- OCR.space responde **HTTP 200 incluso cuando falla**; el error real viene en el JSON
  (`IsErroredOnProcessing`, `OCRExitCode`, `ErrorMessage`, `ErrorDetails`).

## Endpoint que debo exponer

```
POST /api/v1/ocr
Content-Type: multipart/form-data
```

Campos:

| Campo | Tipo | Requerido | Default |
|---|---|---|---|
| `file` | UploadFile | sí | — |
| `language` | str | no | `spa` |
| `ocr_engine` | int (1,2,3) | no | `2` |
| `detect_orientation` | bool | no | `true` |
| `is_create_searchable_pdf` | bool | no | `false` |
| `is_overlay_required` | bool | no | `false` |
| `is_table` | bool | no | `false` |
| `scale` | bool | no | `false` |
| `include_raw` | bool | no | `false` |

Los defaults obligatorios (no negociables) son: **`language=spa`**, **`detectOrientation=true`**,
**`isCreateSearchablePdf=false`**, **`OCREngine=2`**. El resto de parámetros de OCR.space se
exponen pero con los defaults de arriba.

Además: `GET /health` (liveness) y `GET /api/v1/ocr/limits` (devuelve los límites configurados).

## Requisito 1 — Detección automática del tipo de archivo

- Detectar el tipo **por los magic bytes del contenido**, usando la librería `filetype` o
  `python-magic`. **No confiar** en la extensión del nombre ni en el `Content-Type` que manda el
  cliente (pueden venir mal o como `application/octet-stream`).
- Mapear el resultado a los valores exactos que acepta OCR.space en el parámetro `filetype`:
  `PDF`, `GIF`, `PNG`, `JPG`, `TIF`, `BMP`. (JPEG → `JPG`, TIFF → `TIF`.)
- **Siempre mandar el parámetro `filetype` explícito** en la petición, para no depender de la
  detección por content-type que hace OCR.space.
- Si el archivo no es ninguno de esos tipos → responder **415 Unsupported Media Type** con el tipo
  detectado en el detalle.
- Si el tipo cambia por la compresión (ej. un PNG que se convierte a JPEG), recalcular `filetype`
  **después** de comprimir. Este es un error fácil de cometer: el `filetype` enviado debe describir
  el archivo que realmente se sube, no el original.

## Requisito 2 — Compresión automática por debajo de 1 MB

Umbral configurable vía env (`OCR_MAX_UPLOAD_BYTES`, default `1048576`). Si el archivo ya pesa
menos, **no tocarlo** (pasa tal cual, sin recomprimir). Todo el procesamiento en memoria
(`BytesIO`) o en `tempfile` con limpieza garantizada; nunca escribir en un directorio persistente.

El objetivo es "sin perder calidad" en el sentido de **no degradar la legibilidad para el OCR**.
La prioridad es esta, en orden: primero optimizaciones sin pérdida, luego pérdida de compresión, y
sólo al final reducción de resolución.

### Imágenes (Pillow)

1. Aplicar `ImageOps.exif_transpose()` para respetar la orientación EXIF antes de cualquier otra
   cosa, y descartar metadatos EXIF al guardar (ahorra bytes gratis).
2. **Nunca** convertir a escala de grises ni binarizar por defecto: degrada el OCR de sellos,
   tintas de color y documentos con fondo. Dejarlo como flag opcional apagado.
3. Estrategia:
   - Si es PNG/BMP/GIF/TIFF: intentar primero re-guardar como PNG con `optimize=True`. Si cabe,
     terminar aquí (sin pérdida).
   - Si no cabe: convertir a JPEG y hacer **búsqueda binaria de calidad** entre 95 y 60, con
     `subsampling=0` (4:4:4, no destruye bordes de texto), `optimize=True`, `progressive=True`.
     Quedarse con la mayor calidad que quepa bajo el umbral.
   - Si con calidad 60 sigue sin caber: reducir la escala en pasos del 10% con `Image.LANCZOS` y
     repetir la búsqueda de calidad en cada paso. **Piso duro**: no bajar de 1500 px en el lado
     mayor ni por debajo del 50% del original (configurable). Menos que eso destruye texto chico.
4. Las imágenes con transparencia (RGBA/LA/P) deben aplanarse sobre fondo blanco antes de pasar a
   JPEG, si no salen artefactos negros.

### PDF

1. **Intento 1 (sin pérdida):** `pikepdf` con `compress_streams=True`,
   `object_stream_mode=ObjectStreamMode.generate`, `linearize=False`. Muchos PDF bajan de 1 MB
   sólo con esto.
2. **Intento 2:** PyMuPDF (`pymupdf`) reescribiendo con `garbage=4, deflate=True, clean=True`, y
   recomprimiendo las imágenes embebidas que superen cierto tamaño.
3. **Intento 3 (con pérdida):** rasterizar las páginas a JPEG y reconstruir el PDF, probando DPI
   descendente: 300 → 250 → 200 → 150. **No bajar de 150 DPI**, es el piso razonable para OCR.
4. Validar el **límite de páginas** (`OCR_MAX_PDF_PAGES`, default 3) *antes* de comprimir: si el
   PDF trae más páginas de las permitidas, responder **422** con un mensaje explícito
   (`"El plan actual de OCR.space acepta máximo 3 páginas; el PDF tiene N"`). No intentar
   dividirlo automáticamente.

### Si aún así no cabe

Responder **413 Payload Too Large** con un detalle útil: tamaño original, tamaño final alcanzado,
estrategia aplicada y último parámetro probado. Nunca mandar a OCR.space un archivo que sabemos
que va a ser rechazado.

## Requisito 3 — Llamada a OCR.space

- Cliente `httpx.AsyncClient` reutilizado vía lifespan de FastAPI (no crear uno por request).
- Timeout de 120 s (configurable). PDFs y el engine 3 son lentos.
- Header `apikey` desde `OCR_SPACE_API_KEY` (env var, obligatoria al arrancar; fallar rápido si
  falta). **Nunca** hardcodear la key ni loguearla.
- Reintentos: máximo 2, con backoff exponencial, **sólo** ante timeout, error de red o 5xx.
  Nunca reintentar ante 4xx.
- Enviar el archivo como multipart en el campo `file`, con filename y content-type correctos.
- Booleanos serializados como `"true"` / `"false"` en minúsculas (strings del form).
- Mandar SIEMPRE: `language`, `filetype`, `detectOrientation`, `isCreateSearchablePdf`,
  `isSearchablePdfHideTextLayer`, `isOverlayRequired`, `OCREngine`, `scale`, `isTable`.

## Requisito 4 — Respuesta JSON normalizada

Modelos Pydantic v2, tipados, con `model_config` y ejemplos para que salgan bien en `/docs`.

```json
{
  "success": true,
  "file": {
    "filename": "pasaporte.jpg",
    "detected_type": "JPG",
    "mime_type": "image/jpeg",
    "original_size_bytes": 3241984,
    "sent_size_bytes": 987432,
    "was_compressed": true,
    "compression": {
      "strategy": "jpeg_quality_search",
      "quality": 78,
      "scale_factor": 0.9,
      "dpi": null,
      "elapsed_ms": 412
    }
  },
  "request": {
    "language": "spa",
    "ocr_engine": 2,
    "detect_orientation": true,
    "searchable_pdf": false
  },
  "ocr": {
    "exit_code": 1,
    "exit_status": "SUCCESS",
    "processing_time_ms": 3000,
    "text_orientation": "0",
    "page_count": 1,
    "text": "texto completo concatenado con \n entre páginas",
    "pages": [
      {
        "page": 1,
        "exit_code": 1,
        "exit_status": "SUCCESS",
        "text": "texto de la página",
        "error_message": null,
        "overlay": null
      }
    ],
    "searchable_pdf_url": null
  },
  "raw": null
}
```

Reglas de mapeo:

- `OCRExitCode`: `1` → SUCCESS, `2` → PARTIAL_SUCCESS, `3` → PARSE_FAILED, `4` → FATAL_ERROR.
  Exponerlo como enum con nombre legible, no como número pelón.
- `FileParseExitCode` por página: `1` SUCCESS, `0` FILE_NOT_FOUND, `-10` OCR_ENGINE_PARSE_ERROR,
  `-20` TIMEOUT, `-30` VALIDATION_ERROR, `-99` UNKNOWN_ERROR.
- `IsErroredOnProcessing == true` o `OCRExitCode in (3, 4)` → responder **502 Bad Gateway** con
  `ErrorMessage` y `ErrorDetails` de OCR.space intactos en el detalle. Un 200 con texto vacío y
  un error escondido adentro es exactamente lo que quiero evitar.
- `OCRExitCode == 2` (parcial) → HTTP 200, `success: true`, pero marcar las páginas fallidas en
  `pages[].error_message`.
- Normalizar `\r\n` → `\n` en todo el texto extraído.
- `text` debe ser la concatenación de todas las páginas exitosas, separadas por `\n\n`.
- `raw` sólo se llena si `include_raw=true`; si no, va `null`.
- El overlay sólo aparece cuando `is_overlay_required=true`.

### Manejo de errores de la propia API

OCR.space a veces devuelve **texto plano o HTML** en lugar de JSON (por ejemplo con keys inválidas
o rate limit excedido). Envolver el `response.json()` en try/except de `JSONDecodeError` y
devolver **502** con los primeros ~500 caracteres del body crudo en el detalle. Si el status HTTP
es 403/401, mapear a **502** con un mensaje claro de que la API key es inválida o se agotó la cuota.

Todos los errores del servicio deben salir con el mismo shape:

```json
{ "success": false, "error": { "code": "FILE_TOO_LARGE", "message": "...", "details": {} } }
```

Usar un `Enum` de códigos de error propios y un exception handler global.

## Estructura y calidad del proyecto

```
app/
  main.py              # app FastAPI, lifespan, exception handlers
  config.py            # pydantic-settings
  api/routes/ocr.py
  models/{requests,responses,errors}.py
  services/
    detector.py        # detección de tipo por magic bytes
    compressor/
      base.py
      image.py
      pdf.py
    ocr_client.py      # cliente OCR.space
  core/{logging,exceptions}.py
tests/
  test_detector.py
  test_image_compressor.py
  test_pdf_compressor.py
  test_ocr_client.py   # con respx para mockear httpx
  test_endpoint.py
Dockerfile
docker-compose.yml
.env.example
README.md
pyproject.toml
```

Requisitos adicionales:

- Configuración con `pydantic-settings`: `OCR_SPACE_API_KEY`, `OCR_SPACE_ENDPOINT`,
  `OCR_MAX_UPLOAD_BYTES`, `OCR_MAX_PDF_PAGES`, `OCR_TIMEOUT_SECONDS`, `OCR_MIN_JPEG_QUALITY`,
  `OCR_MIN_PDF_DPI`, `OCR_DEFAULT_LANGUAGE`, `OCR_DEFAULT_ENGINE`, `LOG_LEVEL`.
- Logging estructurado en JSON, con un `request_id` por petición. Loguear: tipo detectado, tamaño
  antes/después, estrategia de compresión, tiempo de OCR. **Nunca** loguear el contenido del
  archivo ni el texto extraído completo ni la API key.
- Límite de tamaño de subida bruto (`OCR_MAX_INPUT_BYTES`, default 20 MB) para no cargar archivos
  gigantes en memoria; leer por chunks y abortar si se excede.
- Tests con `pytest` + `pytest-asyncio` + `respx`. Incluir fixtures que generen imágenes y PDFs
  sintéticos de más de 1 MB para probar la compresión de verdad. Ningún test debe pegarle a la API
  real.
- `Dockerfile` multi-stage, imagen slim, usuario no-root, `uvicorn` con workers configurables.
- README con: setup, variables de entorno, ejemplo de `curl` real, tabla de códigos de error y
  explicación de la estrategia de compresión.
- Type hints completos, `ruff` + `mypy` limpios.

## Cómo quiero que trabajes

1. Primero muéstrame el plan y la estructura de archivos, sin escribir código.
2. Luego implementa por capas: config y modelos → detector → compresores → cliente OCR → endpoint
   → tests → Docker/README.
3. Corre los tests al terminar cada capa y arregla lo que falle antes de seguir.
4. Si algo de la documentación de OCR.space contradice estas instrucciones, avísame en lugar de
   asumir.
