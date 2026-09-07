import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DB_PATH = "data/api_keys.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);
"""


class _DbPathSettings(BaseSettings):
    """Carga unicamente la ruta de la DB de API keys, sin el resto de Settings
    (que exige OCR_SPACE_API_KEY) - asi scripts/manage_api_keys.py puede usarse
    antes de terminar de configurar el resto del .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    api_keys_db_path: str = Field(DEFAULT_DB_PATH, alias="API_KEYS_DB_PATH")


def resolve_db_path(explicit: str | None = None) -> str:
    return explicit or _DbPathSettings().api_keys_db_path


@contextmanager
def db_session(db_path: str) -> Generator[sqlite3.Connection]:
    """Abre una conexion sqlite nueva (creando el archivo/tabla si hace falta),
    hace commit/rollback automatico al salir del bloque, y siempre la cierra.

    Se abre una conexion por llamada en vez de compartir una sola: el volumen de
    este servicio no lo justifica, y evita problemas de uso concurrente de una
    misma conexion entre threads (las consultas de runtime corren en el
    threadpool, via run_in_threadpool, para no bloquear el event loop).
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute(_SCHEMA)
        with conn:
            yield conn
    finally:
        conn.close()
