"""SQLite helpers + SQL migrations."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from autonomous.paths import db_path, ensure_home

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(home: Path | None = None) -> sqlite3.Connection:
    ensure_home(home)
    path = db_path(home)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_db(home: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(home)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migration_files() -> list[tuple[int, Path]]:
    files: list[tuple[int, Path]] = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"^(\d+)_", path.name)
        if not m:
            continue
        files.append((int(m.group(1)), path))
    return files


def migrate(home: Path | None = None) -> list[int]:
    """Apply pending SQL migrations. Returns applied versions."""
    ensure_home(home)
    applied: list[int] = []
    with get_db(home) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              applied_at TEXT NOT NULL
            )
            """
        )
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        done = {int(r["version"]) for r in rows}
        for version, path in _migration_files():
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            # Strip the schema_migrations create from migration files (already ensured)
            conn.executescript(sql)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                "VALUES (?, datetime('now'))",
                (version,),
            )
            applied.append(version)
        # Older incremental installs may lack columns; keep them present.
        # (Numbered *.sql migrations can collide with pre-squash version ints.)
        _ensure_column(
            conn,
            "vault_requests",
            "fields_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        _ensure_column(conn, "bots", "api_token_hash", "TEXT")
        # Host shell feature removed — drop leftover column on upgraded DBs.
        _drop_column_if_exists(conn, "bots", "allow_host_shell")
        _drop_column_if_exists(conn, "bots", "allow_vm_shell")
    return applied


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, decl: str
) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _drop_column_if_exists(
    conn: sqlite3.Connection, table: str, column: str
) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column in cols:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}
