FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev


FROM python:3.12-slim

RUN useradd --system --create-home --home-dir /home/app app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/app /app/app
COPY --chown=app:app scripts ./scripts
RUN mkdir -p /app/data && chown app:app /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UVICORN_WORKERS=2 \
    API_KEYS_DB_PATH=/app/data/api_keys.db

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
