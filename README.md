# OCR API Gateway

Microservicio en **Python 3.12 + FastAPI** que actua como proxy hacia la API de OCR de
[OCR.space](https://ocr.space/ocrapi). Recibe una imagen o un PDF, lo comprime automaticamente
para cumplir los limites del plan gratuito (1 MB por archivo, 3 paginas por PDF), lo envia a
OCR.space, y devuelve una respuesta JSON normalizada y facil de consumir.

## Por que existe

OCR.space es gratuito pero exige archivos chicos. Este gateway hace transparente esa restriccion:
comprime lo que haga falta (sin degradar la legibilidad para el OCR mas de lo necesario) y devuelve
siempre el mismo shape de respuesta, sin importar si el archivo original necesito compresion o no.

## Requisitos

- Python 3.12
- [uv](https://docs.astral.sh/uv/) para manejo de dependencias
- Una API key gratuita de OCR.space: https://ocr.space/ocrapi (formulario "Register")

## Setup local

```bash
uv sync --group dev
cp .env.example .env
# editar .env y completar OCR_SPACE_API_KEY
uv run uvicorn app.main:app --reload
```

Abrir http://localhost:8000/docs para probar el endpoint desde Swagger UI.

## Correr con Docker

```bash
cp .env.example .env
# completar OCR_SPACE_API_KEY en .env
docker compose up --build
```

El contenedor corre como usuario no-root, expone el puerto 8000 y tiene un healthcheck sobre
`GET /health`.

## Correr como servicio systemd en Ubuntu (sin Docker)

El unit file esta en `deploy/ocr-api-gateway.service`. Asume que el proyecto vive en
`/opt/ocr-api-gateway` y corre bajo un usuario dedicado `ocrapi` — ajusta ambos si usas otros.

```bash
# 1. uv disponible para todo el sistema (no solo tu usuario)
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# 2. usuario de sistema dedicado. Le damos un $HOME real dentro de su propio
#    directorio (aunque sea un usuario "system"): uv necesita *algun* $HOME
#    donde instalar el interprete de Python que administra, y tiene que ser
#    uno al que este mismo usuario tenga acceso (ver nota de la Nota 1 abajo).
sudo useradd --system --home-dir /opt/ocr-api-gateway --shell /usr/sbin/nologin ocrapi

# 3. copiar el proyecto (clonalo o rsync-ealo desde donde lo tengas)
sudo mkdir -p /opt/ocr-api-gateway
sudo cp -r . /opt/ocr-api-gateway   # corriendo esto desde la raiz del repo
sudo chown -R ocrapi:ocrapi /opt/ocr-api-gateway
cd /opt/ocr-api-gateway

# 4. dependencias de produccion (sin dev), usando el lockfile tal cual.
#    IMPORTANTE: correr esto como ocrapi, NUNCA como root/sudo directo — ver Nota 1.
sudo -H -u ocrapi uv sync --frozen --no-dev

# 5. variables de entorno reales, solo legibles por el dueno
sudo cp .env.example .env
sudo nano .env   # completar OCR_SPACE_API_KEY y lo que quieras ajustar
sudo chown ocrapi:ocrapi .env
sudo chmod 600 .env

# 6. instalar y arrancar el servicio
sudo cp deploy/ocr-api-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ocr-api-gateway
```

Verificar que levanto bien:

```bash
sudo systemctl status ocr-api-gateway
curl http://localhost:8000/health
journalctl -u ocr-api-gateway -f   # logs en vivo (structlog en JSON)
```

Generar la primera API key (la DB vive en `/var/lib/ocr-api-gateway/api_keys.db`, creada por
`StateDirectory=` del unit file):

```bash
sudo -H -u ocrapi API_KEYS_DB_PATH=/var/lib/ocr-api-gateway/api_keys.db \
  /opt/ocr-api-gateway/.venv/bin/python /opt/ocr-api-gateway/scripts/manage_api_keys.py \
  create "primer cliente"
```

**Actualizar a una nueva version:**

```bash
cd /opt/ocr-api-gateway
sudo -H -u ocrapi git pull   # o el mecanismo que uses para traer el codigo nuevo
sudo -H -u ocrapi uv sync --frozen --no-dev
sudo systemctl restart ocr-api-gateway
```

**Notas:**

- **Nota 1 — nunca corras `uv sync` como root para este setup.** `uv` instala y administra su
  propio interprete de Python bajo `$HOME/.local/share/uv/python/...` del usuario que lo ejecuta.
  Si corres `uv sync` como `root`, el venv termina con un `.venv/bin/python` que apunta a un
  interprete dentro de `/root/...` — y como el servicio corre como `ocrapi` (sin acceso a `/root`,
  y ademas bloqueado explicitamente por `ProtectHome=true` en el unit file), systemd falla al
  arrancar con `Failed to execute .../uvicorn: Permission denied` (`status=203/EXEC`), aunque
  correrlo a mano como root funcione perfecto. Por eso el usuario `ocrapi` se crea con
  `--home-dir /opt/ocr-api-gateway` y el `uv sync` se corre con `sudo -H -u ocrapi` — asi el
  interprete que instala uv queda dentro del propio arbol de `ocrapi`, accesible para el mismo.
  Si ya te paso esto: `sudo rm -rf .venv` y repeti el paso 4 corriendolo como `ocrapi`.
- El unit file corre `uvicorn` directo desde `.venv/bin/uvicorn` (no `uv run`), asi que no necesita
  `uv` en el `PATH` de systemd — solo `uv sync` lo necesita al desplegar.
- El servicio queda con el filesystem en solo lectura (`ProtectSystem=strict`) salvo un `/tmp`
  privado y el `StateDirectory=ocr-api-gateway` del unit file (systemd crea y le da permisos de
  escritura a `/var/lib/ocr-api-gateway`, que es donde vive la DB sqlite de API keys). La
  compresion sigue siendo toda en memoria — la unica escritura real a disco es esa DB.
- Por default escucha en `0.0.0.0:8000` sin TLS. Si el servidor esta expuesto a internet, ponelo
  detras de un reverse proxy (nginx/Caddy) que termine TLS y le pegue a `127.0.0.1:8000`, y con
  `ufw` dejar cerrado el 8000 hacia afuera. Eso no esta incluido aca porque depende de tu dominio/
  certificados — avisame si queres que lo arme.

## Variables de entorno

| Variable | Default | Descripcion |
|---|---|---|
| `OCR_SPACE_API_KEY` | *(requerida)* | API key de OCR.space. El servicio no arranca sin ella. |
| `OCR_SPACE_ENDPOINT` | `https://api.ocr.space/parse/image` | Endpoint de OCR.space. |
| `OCR_MAX_UPLOAD_BYTES` | `1048576` (1 MB) | Umbral de compresion: por debajo de esto, el archivo pasa sin tocar. |
| `OCR_MAX_PDF_PAGES` | `3` | Paginas maximas por PDF antes de rechazar con 422. |
| `OCR_TIMEOUT_SECONDS` | `120` | Timeout del cliente HTTP hacia OCR.space. |
| `OCR_MAX_RETRIES` | `2` | Reintentos ante timeout/error de red/5xx (nunca ante 4xx). |
| `OCR_MIN_JPEG_QUALITY` | `40` | Piso de calidad JPEG durante la busqueda binaria de compresion. |
| `OCR_MIN_PDF_DPI` | `150` | Piso de DPI durante la cascada de rasterizado de PDF. |
| `OCR_MIN_IMAGE_LONGEST_SIDE_PX` | `1500` | Piso de resolucion (lado mayor) al reducir escala. |
| `OCR_MIN_IMAGE_SCALE_FACTOR` | `0.5` | Piso de escala relativa al original (ver "Estrategia de compresion"). |
| `OCR_DEFAULT_LANGUAGE` | `spa` | Default del servicio para `language` si el cliente no lo manda. |
| `OCR_DEFAULT_ENGINE` | `2` | Default del servicio para `ocr_engine` si el cliente no lo manda. |
| `OCR_MAX_INPUT_BYTES` | `20971520` (20 MB) | Tope de subida cruda antes de intentar comprimir. |
| `LOG_LEVEL` | `INFO` | Nivel de logging (JSON estructurado a stdout). |
| `UVICORN_WORKERS` | `2` | Solo aplica corriendo con Docker/docker-compose. |
| `API_KEYS_DB_PATH` | `data/api_keys.db` | DB sqlite donde se guardan las API keys. Se crea sola si no existe. |
| `RATE_LIMIT_REQUESTS` | `30` | Peticiones permitidas por API key dentro de la ventana (ver "Rate limiting"). |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Tamano de la ventana deslizante del rate limit, en segundos. |

## Autenticacion (API keys)

Todos los endpoints bajo `/api/v1` (`POST /ocr`, `GET /ocr/limits`) exigen un header
`X-API-Key` valido. `GET /health` queda publico (lo usan los healthchecks de Docker/systemd).

Las API keys **no se generan via HTTP** - solo con el script de consola
`scripts/manage_api_keys.py`, y se guardan en la DB sqlite de `API_KEYS_DB_PATH` (solo se
persiste el hash SHA-256 de cada key, nunca el valor en texto plano).

```bash
# generar una key nueva (el valor solo se muestra una vez, en este momento)
uv run scripts/manage_api_keys.py create "nombre del cliente"

# listar las keys registradas (id, nombre, si esta activa, ultimo uso)
uv run scripts/manage_api_keys.py list

# revocar / reactivar una key por id
uv run scripts/manage_api_keys.py revoke <id>
uv run scripts/manage_api_keys.py activate <id>
```

Corriendo con Docker: `docker compose exec ocr-api-gateway python scripts/manage_api_keys.py create "nombre"`.
Corriendo como servicio systemd: `sudo -u ocrapi API_KEYS_DB_PATH=/var/lib/ocr-api-gateway/api_keys.db /opt/ocr-api-gateway/.venv/bin/python /opt/ocr-api-gateway/scripts/manage_api_keys.py create "nombre"`.

Uso desde el cliente:

```bash
curl -X POST http://localhost:8000/api/v1/ocr \
  -H "X-API-Key: ocrgw_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -F "file=@pasaporte.jpg"
```

Sin el header (o con una key invalida/revocada) el servicio responde 401 con
`MISSING_API_KEY` o `INVALID_API_KEY` respectivamente.

## Rate limiting

Cada API key tiene un limite de `RATE_LIMIT_REQUESTS` peticiones por `RATE_LIMIT_WINDOW_SECONDS`
(ventana deslizante, default 30 peticiones / 60 segundos) sobre `/api/v1/*`. Al superarlo, el
servicio responde **429** con `RATE_LIMIT_EXCEEDED` y un header `Retry-After` con los segundos
a esperar.

**Limitacion conocida:** el contador vive en memoria de cada proceso. Corriendo con varios
`UVICORN_WORKERS` (el default es 2), cada worker lleva su propio conteo — el techo global
efectivo terminan siendo aproximadamente `workers * RATE_LIMIT_REQUESTS` peticiones por ventana,
no un limite exacto compartido. Para un limite global estricto entre procesos habria que sumar
un backend compartido (ej. Redis), pero para el volumen de este gateway no se justifica; si hace
falta ese limite exacto, correr con un solo worker.

## Concurrencia

Las rutas son `async` y el cliente HTTP hacia OCR.space (`httpx.AsyncClient`) es asincrono, asi
que multiples peticiones en vuelo no se bloquean entre si esperando la respuesta de OCR.space.
La compresion (busqueda de calidad JPEG, rasterizado de PDF, etc.) es CPU-bound y puede tardar
de cientos de milisegundos a varios segundos: se corre en el threadpool de Starlette
(`run_in_threadpool`) para no bloquear el event loop mientras corre, permitiendo que otras
peticiones sigan avanzando en paralelo dentro del mismo worker. La verificacion de la API key
(consulta sqlite) tambien corre en el threadpool por el mismo motivo. Para escalar mas alla de
un solo proceso, subir `UVICORN_WORKERS` (o correr varias replicas detras de un load balancer).

## API

### `POST /api/v1/ocr`

`multipart/form-data` con estos campos:

| Campo | Tipo | Default |
|---|---|---|
| `file` | archivo (requerido) | — |
| `language` | string | `spa` |
| `ocr_engine` | int (1, 2 o 3) | `2` |
| `detect_orientation` | bool | `true` |
| `is_create_searchable_pdf` | bool | `false` |
| `is_overlay_required` | bool | `false` |
| `is_table` | bool | `false` |
| `scale` | bool | `false` |
| `include_raw` | bool | `false` |

Los defaults de arriba son los defaults **del servicio** (no los de OCR.space): si no mandas el
campo, se usa ese valor. El cliente puede sobreescribir cualquiera de ellos.

Ejemplo:

```bash
curl -X POST http://localhost:8000/api/v1/ocr \
  -H "X-API-Key: ocrgw_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -F "file=@pasaporte.jpg" \
  -F "language=spa" \
  -F "ocr_engine=2"
```

Respuesta:

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
    "text": "texto completo concatenado con \n entre paginas",
    "pages": [
      {
        "page": 1,
        "exit_code": 1,
        "exit_status": "SUCCESS",
        "text": "texto de la pagina",
        "error_message": null,
        "overlay": null
      }
    ],
    "searchable_pdf_url": null
  },
  "passport": null,
  "raw": null
}
```

### Deteccion automatica de pasaporte (MRZ)

Si el texto extraido contiene una zona MRZ (Machine Readable Zone, TD3, formato ICAO 9303 — las
2 lineas de 44 caracteres al pie de la pagina de datos), el servicio la detecta con expresiones
regulares, extrae los campos estructurados, y valida:

1. **Los digitos de control del propio MRZ** (`checksum_valid`) — el algoritmo de checksum
   estandar ICAO 9303 (pesos 7/3/1), aplicado a numero de pasaporte, fecha de nacimiento, fecha de
   vencimiento, numero personal y el digito compuesto.
2. **Que los datos del MRZ coincidan con el texto visible del documento** (`matches_visible_text`)
   — nombre, apellidos, numero de pasaporte, numero de identificacion y fechas de nacimiento/
   vencimiento. Si algo no coincide, `validation_error` explica exactamente que campo fallo, en vez
   de fallar silenciosamente o asumir que el MRZ es siempre correcto.

Si el documento no es un pasaporte (o el MRZ no se pudo leer), `passport` queda en `null` — no
cambia nada del resto de la respuesta.

```json
{
  "passport": {
    "mrz": {
      "document_code": "P",
      "issuing_country": "ESP",
      "nationality": "ESP",
      "passport_number": "XDF235217",
      "surname": "VINIEGRA PEREZ OLAGARAY",
      "given_names": "ESTEBAN",
      "sex": "M",
      "date_of_birth": "2001-09-01",
      "date_of_expiry": "2029-11-12",
      "personal_number": "RE202407041324",
      "checksum_valid": true,
      "raw_line1": "P<ESPVINIEGRA<PEREZ<OLAGARAY<<ESTEBAN<<<<<<<",
      "raw_line2": "XDF2352177ESP0109017M2911124RE20240704132446"
    },
    "matches_visible_text": true,
    "validation_error": null
  }
}
```

Si hay una discrepancia, `matches_visible_text` pasa a `false` y `validation_error` describe cada
campo que no calzo, por ejemplo:

```json
"validation_error": "Los datos del MRZ no coinciden con el texto visible del documento: numero de pasaporte 'XDF235217' no encontrado en el texto visible"
```

**Limitacion conocida:** la comparacion contra el texto visible es tan buena como el propio OCR de
esa zona — si la compresion o la calidad de la foto degradan la lectura del campo visible (no del
MRZ), se va a reportar un mismatch aunque el MRZ este perfectamente bien. Esto es intencional: el
objetivo es señalar cuando el documento necesita revision manual, no decidir cual de las dos
lecturas es la "correcta".

### `GET /api/v1/ocr/limits`

Devuelve los limites configurados actualmente (utilies para que un cliente sepa de antemano que
va a pasar sin tener que leer las env vars del servidor).

### `GET /health`

Liveness check simple, usado por el `HEALTHCHECK` de Docker.

## Codigos de error

Todos los errores del servicio devuelven el mismo shape:

```json
{ "success": false, "error": { "code": "FILE_TOO_LARGE", "message": "...", "details": {} } }
```

| Codigo | HTTP | Cuando ocurre |
|---|---|---|
| `UNSUPPORTED_FILE_TYPE` | 415 | El archivo no es PDF/GIF/PNG/JPG/TIF/BMP segun sus magic bytes. |
| `FILE_TOO_LARGE` | 413 | La subida cruda supera `OCR_MAX_INPUT_BYTES`. |
| `COMPRESSION_FAILED` | 413 | Se agotaron todas las estrategias de compresion sin llegar al umbral. |
| `PDF_PAGE_LIMIT_EXCEEDED` | 422 | El PDF tiene mas paginas que `OCR_MAX_PDF_PAGES`. |
| `CORRUPT_OR_ENCRYPTED_FILE` | 422 | El PDF esta corrupto o protegido con contrasena. |
| `OCR_SPACE_AUTH_ERROR` | 502 | OCR.space respondio 401/403 (API key invalida o cuota agotada). |
| `OCR_SPACE_INVALID_RESPONSE` | 502 | OCR.space devolvio un body que no es JSON valido. |
| `OCR_SPACE_ERROR` | 502 | `IsErroredOnProcessing=true` o `OCRExitCode` en (3, 4). |
| `VALIDATION_ERROR` | 422 | La peticion no cumple el formato esperado (validacion de FastAPI/Pydantic). |
| `MISSING_API_KEY` | 401 | La peticion no incluye el header `X-API-Key`. |
| `INVALID_API_KEY` | 401 | La API key no existe o fue revocada. |
| `RATE_LIMIT_EXCEEDED` | 429 | Se supero `RATE_LIMIT_REQUESTS` para esa API key en la ventana actual. |
| `INTERNAL_ERROR` | 500 | Cualquier otro error no manejado. |

## Estrategia de compresion

Prioridad: primero sin perdida, despues con perdida, y reduccion de resolucion solo como ultimo
recurso. Nunca se convierte a escala de grises ni se binariza por defecto (degrada el OCR de
sellos, tintas de color y fondos).

**Imagenes:**

1. Se aplica `exif_transpose` para respetar la orientacion antes de cualquier otra cosa, y se
   descarta el EXIF al guardar.
2. Si el formato original es PNG/BMP/GIF/TIFF, se intenta re-guardar como PNG optimizado (sin
   perdida). Si entra bajo el umbral, listo.
3. Si no, se convierte a JPEG y se hace una **busqueda binaria de calidad** entre
   `OCR_MIN_JPEG_QUALITY` (40 por default) y 95, quedandose con la mayor calidad que entre.
4. Si ni con la calidad minima entra, se reduce la escala en pasos del 10% (`LANCZOS`) y se repite
   la busqueda de calidad en cada paso. El piso de calidad se dejo deliberadamente bajo (40, no 60)
   porque en la practica preservar resolucion completa importa mas para el OCR de texto chico/denso
   (ej. el MRZ de un pasaporte) que mantener una calidad JPEG alta: una foto de camara comprimida a
   resolucion completa con calidad 40-56 se lee mejor que la misma foto a 90% de escala con calidad
   66.
5. **Piso duro:** nunca se baja de `OCR_MIN_IMAGE_LONGEST_SIDE_PX` (1500px) **ni** del
   `OCR_MIN_IMAGE_SCALE_FACTOR` (50%) del original — el piso real es el **mayor** de los dos
   (`max(1500px, 50% del original)`), porque ambas condiciones tienen que cumplirse a la vez. Con
   imagenes de hasta 3000px de lado mayor, el piso practico termina siendo siempre 1500px.

**PDF:**

1. `pikepdf` sin perdida (compresion de streams). Nota: si el PDF ya trae imagenes JPEG embebidas
   (el caso tipico de un PDF escaneado), este paso logra poco — pikepdf no recomprime streams ya
   comprimidos — y la cascada normalmente sigue al paso 2.
2. Reescritura estructural con PyMuPDF (dedupe de objetos, deflate) + recompresion de las imagenes
   embebidas que superen 200 KB.
3. Si nada de eso alcanza: rasterizar cada pagina a JPEG y reconstruir el PDF, bajando el DPI en
   la secuencia 300 → 250 → 200 → 150. Nunca se baja de `OCR_MIN_PDF_DPI` (150 por default).

Si ninguna estrategia logra bajar del umbral, el servicio responde **413** con el tamano original,
el tamano final alcanzado, la estrategia usada y el ultimo parametro probado — nunca se manda a
OCR.space un archivo que ya se sabe que va a ser rechazado.

## Limitaciones conocidas

- **TIFF multipagina:** solo se procesa el primer frame. El limite de paginas (`OCR_MAX_PDF_PAGES`)
  aplica unicamente a PDF.
- **`isSearchablePdfHideTextLayer`**: OCR.space lo requiere siempre en la peticion pero el
  endpoint no expone un campo de cliente para el; se manda fijo en `false`.
- **Rate limit por proceso, no global:** ver la nota en "Rate limiting" — con varios workers
  el techo efectivo es aproximadamente `workers * RATE_LIMIT_REQUESTS`, no un limite exacto.
- **DB de API keys en sqlite:** correcto para el volumen de este gateway (se abre con
  `journal_mode=WAL` y `busy_timeout`), pero no esta pensado para un numero grande de
  replicas escribiendo `last_used_at` concurrentemente contra el mismo archivo.

## Testing

```bash
uv run pytest
```

Ningun test pega a la API real de OCR.space (se mockea con `respx`). Los fixtures de imagenes y
PDFs sobredimensionados se generan en memoria con Pillow y PyMuPDF.

## Lint y type-checking

```bash
uv run ruff check .
uv run ruff format .
uv run mypy app
```
