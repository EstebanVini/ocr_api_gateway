#!/usr/bin/env python3
"""Administra las API keys del gateway desde la consola.

Las keys NUNCA se generan via HTTP: este script es la unica forma de crearlas.
Solo se guarda el hash SHA-256 de cada key - el valor en texto plano se muestra
una sola vez, al crearla, y no se puede recuperar despues.

Uso:
    uv run scripts/manage_api_keys.py create "nombre del cliente"
    uv run scripts/manage_api_keys.py list
    uv run scripts/manage_api_keys.py revoke <id>
    uv run scripts/manage_api_keys.py activate <id>
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import resolve_db_path  # noqa: E402
from app.services.api_keys import (  # noqa: E402
    activate_api_key,
    create_api_key,
    list_api_keys,
    revoke_api_key,
)


def cmd_create(args: argparse.Namespace) -> None:
    db_path = resolve_db_path(args.db_path)
    key_id, raw_key = create_api_key(db_path, args.name)
    print(f"API key creada (id={key_id}, name={args.name!r}):\n")
    print(f"  {raw_key}\n")
    print("Guardala ahora - no se puede volver a mostrar (solo se almacena su hash).")


def cmd_list(args: argparse.Namespace) -> None:
    db_path = resolve_db_path(args.db_path)
    rows = list_api_keys(db_path)
    if not rows:
        print("No hay API keys registradas.")
        return
    print(f"{'ID':<5} {'ACTIVA':<8} {'CREADA':<22} {'ULTIMO USO':<22} NOMBRE")
    for row in rows:
        print(
            f"{row['id']:<5} {'si' if row['is_active'] else 'no':<8} "
            f"{row['created_at']:<22} {row['last_used_at'] or '-':<22} {row['name']}"
        )


def cmd_revoke(args: argparse.Namespace) -> None:
    db_path = resolve_db_path(args.db_path)
    ok = revoke_api_key(db_path, args.id)
    print("Revocada." if ok else f"No existe una API key con id={args.id}.")


def cmd_activate(args: argparse.Namespace) -> None:
    db_path = resolve_db_path(args.db_path)
    ok = activate_api_key(db_path, args.id)
    print("Reactivada." if ok else f"No existe una API key con id={args.id}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Administra las API keys del OCR API Gateway.")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Ruta a la DB sqlite (default: API_KEYS_DB_PATH / .env)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_create = subparsers.add_parser("create", help="Genera una nueva API key")
    p_create.add_argument("name", help="Nombre/etiqueta que identifica al consumidor de la key")
    p_create.set_defaults(func=cmd_create)

    p_list = subparsers.add_parser("list", help="Lista las API keys registradas")
    p_list.set_defaults(func=cmd_list)

    p_revoke = subparsers.add_parser("revoke", help="Desactiva una API key")
    p_revoke.add_argument("id", type=int)
    p_revoke.set_defaults(func=cmd_revoke)

    p_activate = subparsers.add_parser("activate", help="Reactiva una API key desactivada")
    p_activate.add_argument("id", type=int)
    p_activate.set_defaults(func=cmd_activate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
