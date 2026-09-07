import hashlib
import secrets
import sqlite3
from dataclasses import dataclass

from app.core.database import db_session

_KEY_PREFIX = "ocrgw_"


@dataclass(frozen=True)
class ApiKeyRecord:
    id: int
    name: str
    is_active: bool


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_raw_key() -> str:
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def create_api_key(db_path: str, name: str) -> tuple[int, str]:
    """Genera y guarda una nueva API key. El valor en texto plano devuelto aca
    solo existe en este momento: la base solo guarda su hash SHA-256."""
    raw_key = generate_raw_key()
    key_hash = _hash_key(raw_key)
    with db_session(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO api_keys (key_hash, name) VALUES (?, ?)", (key_hash, name)
        )
        key_id = cursor.lastrowid
    assert key_id is not None
    return key_id, raw_key


def list_api_keys(db_path: str) -> list[sqlite3.Row]:
    with db_session(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT id, name, created_at, last_used_at, is_active FROM api_keys ORDER BY id"
        ).fetchall()


def revoke_api_key(db_path: str, key_id: int) -> bool:
    with db_session(db_path) as conn:
        cursor = conn.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
        return cursor.rowcount > 0


def activate_api_key(db_path: str, key_id: int) -> bool:
    with db_session(db_path) as conn:
        cursor = conn.execute("UPDATE api_keys SET is_active = 1 WHERE id = ?", (key_id,))
        return cursor.rowcount > 0


def verify_api_key(db_path: str, raw_key: str) -> ApiKeyRecord | None:
    """Consulta bloqueante: SIEMPRE se debe invocar via run_in_threadpool desde
    codigo async, para no bloquear el event loop con I/O de disco."""
    key_hash = _hash_key(raw_key)
    with db_session(db_path) as conn:
        row = conn.execute(
            "SELECT id, name, is_active FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        if row is None:
            return None
        record = ApiKeyRecord(id=row[0], name=row[1], is_active=bool(row[2]))
        if record.is_active:
            conn.execute(
                "UPDATE api_keys SET last_used_at = datetime('now') WHERE id = ?", (record.id,)
            )
        return record
