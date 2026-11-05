"""Long-running job tracking (desk create/destroy, etc.)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services.errors import NotFound
from autonomous.services.events import BUS
from autonomous.i18n import t


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "bot": row["bot"],
        "kind": row["kind"],
        "state": row["state"],
        "progress": row["progress"],
        "log": json.loads(row["log_json"] or "[]"),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_job(bot: str, kind: str, home: Path | None = None) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = _now()
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO jobs(id, bot, kind, state, progress, log_json, error, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', 0, '[]', NULL, ?, ?)
            """,
            (job_id, bot, kind, now, now),
        )
    job = get_job(job_id, home=home)
    BUS.publish("job.updated", {"job": job}, bot=bot)
    return job


def get_job(job_id: str, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise NotFound(t("job.not_found", id=job_id))
    return _decode(row)


def update_job(
    job_id: str,
    *,
    state: str | None = None,
    progress: int | None = None,
    log_line: str | None = None,
    error: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    job = get_job(job_id, home=home)
    log = list(job["log"])
    if log_line:
        log.append(log_line)
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE jobs SET
              state = COALESCE(?, state),
              progress = COALESCE(?, progress),
              log_json = ?,
              error = COALESCE(?, error),
              updated_at = ?
            WHERE id = ?
            """,
            (
                state,
                progress,
                json.dumps(log),
                error,
                _now(),
                job_id,
            ),
        )
    job = get_job(job_id, home=home)
    BUS.publish("job.updated", {"job": job}, bot=job["bot"])
    return job
