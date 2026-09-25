from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

MIGRATIONS = Path(__file__).resolve().parent.parent / "db" / "migrations"


def connect(url: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(url or os.environ.get("DATABASE_URL", "postgresql://localhost/ctopen"), row_factory=dict_row)
    migrate(conn)
    return conn


def migrate(conn: psycopg.Connection) -> None:
    """db/migrations/NNN_*.sql을 순서대로, 아직 안 한 것만 적용."""
    with conn.transaction():
        conn.execute("create table if not exists schema_migrations (name text primary key, applied_at timestamptz default now())")
        done = {r["name"] for r in conn.execute("select name from schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name not in done:
                conn.execute(f.read_text())
                conn.execute("insert into schema_migrations (name) values (%s)", (f.name,))
