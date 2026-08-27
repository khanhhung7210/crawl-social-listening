"""PostgreSQL helpers for galaxy_social_listening / galaxy_sl."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Shell/CI env wins over .env so crawl can target the shared server DB
# without rewriting local .env (PGHOST=10.10.17.18 vs 127.0.0.1).
load_dotenv(PROJECT_ROOT / ".env", override=False)

try:
    import psycopg2
    import psycopg2.extras
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "psycopg2 is required. Install with: python3 -m pip install psycopg2-binary"
    ) from exc


def pg_connect_kwargs() -> dict:
    kwargs: dict = {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": os.getenv("PGDATABASE", "galaxy_social_listening"),
        "user": os.getenv("PGUSER") or os.getenv("USER") or "postgres",
    }
    password = os.getenv("PGPASSWORD", "")
    if password:
        kwargs["password"] = password
    return kwargs


def schema_name() -> str:
    return os.getenv("PGSCHEMA", "galaxy_sl")


@contextmanager
def get_connection() -> Iterator["psycopg2.extensions.connection"]:
    conn = psycopg2.connect(**pg_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema_name()}, public")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_brand_map(cur) -> dict[str, str]:
    cur.execute("SELECT brand_slug::text, brand_id::text FROM brands")
    return {row[0].lower(): row[1] for row in cur.fetchall()}


def fetch_app_id(cur, store: str, store_app_id: str) -> str | None:
    cur.execute(
        """
        SELECT app_id::text FROM mobile_apps
        WHERE store = %s AND store_app_id = %s
        LIMIT 1
        """,
        (store, str(store_app_id)),
    )
    row = cur.fetchone()
    return row[0] if row else None
