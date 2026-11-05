"""Terminal history + docker exec (server-side; used by CLI, API, and Pi agent)."""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services import bots as bots_svc
from autonomous.services.errors import AutonomousError
from autonomous.services.events import BUS

# Cap stored / returned output so agent context and SQLite stay bounded.
_MAX_OUTPUT_CHARS = 200_000
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_DATE_UTC_CMD = re.compile(
    r"(?:^|[;&|]\s*)date\b[\s\S]*?(?:^|\s)(?:-u|--utc|--universal)\b"
)


def _utc_date_note(command: str, home: Path | None) -> str:
    """`date -u` ignores TZ= and made a reminder land on tomorrow."""
    if not _DATE_UTC_CMD.search(command or ""):
        return ""
    from autonomous.services.cronutil import user_clock

    clock = user_clock(home)
    tz = clock["timezone"]
    return (
        f"\nNOTE: `date -u` is UTC and ignores TZ=. "
        f"User time is {clock['now']} {tz} (UTC{clock['utc_offset']}). "
        f"For a schedule, run `TZ={tz} date` without -u. "
        "The cron hour is that local hour; do not add the offset again."
    )


def _decode(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "bot": row["bot"],
        "command": row["command"],
        "exit_code": row["exit_code"],
        "output": row["output"],
        "created_at": row["created_at"],
    }


def _clip(output: str) -> str:
    if len(output) <= _MAX_OUTPUT_CHARS:
        return output
    omitted = len(output) - _MAX_OUTPUT_CHARS
    return output[:_MAX_OUTPUT_CHARS] + f"\n… [truncated {omitted} chars]"


def list_logs(bot: str, *, limit: int = 50, home: Path | None = None) -> list[dict[str, Any]]:
    bots_svc.get_bot(bot, home=home)
    limit = max(1, min(limit, 200))
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM terminal_logs WHERE bot = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (bot, limit),
        ).fetchall()
    return [_decode(r) for r in reversed(rows)]


def append_log(
    bot: str,
    command: str,
    *,
    exit_code: int | None,
    output: str,
    home: Path | None = None,
) -> dict[str, Any]:
    entry_id = str(uuid.uuid4())
    now = _now()
    output = _clip(output or "")
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO terminal_logs(id, bot, command, exit_code, output, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_id, bot, command, exit_code, output, now),
        )
    entry = {
        "id": entry_id,
        "bot": bot,
        "command": command,
        "exit_code": exit_code,
        "output": output,
        "created_at": now,
    }
    BUS.publish("terminal.created", {"entry": entry}, bot=bot)
    return entry


_DATE_ONLY = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*date(?:\s+.*)?$")


def _clock_only_command(command: str) -> bool:
    if any(ch in command for ch in ";|&`$()<>\n"):
        return False
    return bool(_DATE_ONLY.match(command.strip()))


def _llm_test_clock(bot: str, command: str, *, home: Path | None) -> dict[str, Any] | None:
    """Opt-in host `date` for LLM tests. Production never sets the env var."""
    if os.environ.get("AUTONOMOUS_LLM_TEST_CLOCK") != "1":
        return None
    if not _clock_only_command(command):
        return None
    from autonomous.services.cronutil import user_clock

    clock = user_clock(home)
    env = os.environ.copy()
    env["TZ"] = clock["timezone"]
    try:
        completed = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return append_log(bot, command, exit_code=1, output=str(exc), home=home)
    output = (completed.stdout or "") + (completed.stderr or "")
    output += _utc_date_note(command, home)
    return append_log(
        bot,
        command,
        exit_code=int(completed.returncode),
        output=output,
        home=home,
    )


def exec_command(
    bot: str,
    command: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    home: Path | None = None,
) -> dict[str, Any]:
    """Run a non-interactive command in the bot VM."""
    command = (command or "").strip()
    if not command:
        raise AutonomousError("command required", code="validation_error")

    canned = _llm_test_clock(bot, command, home=home)
    if canned is not None:
        return canned

    from autonomous.services import desk as desk_svc

    desk_svc.ensure_awake(bot, home=home)

    try:
        timeout_s = int(timeout)
    except (TypeError, ValueError):
        timeout_s = _DEFAULT_TIMEOUT
    timeout_s = max(1, min(timeout_s, _MAX_TIMEOUT))

    name = desk_svc.container_name(bot, home=home)
    # subprocess + `docker exec` so timeout is reliably enforced (SDK exec_run has none).
    cmd = [
        "docker",
        "exec",
        "-u",
        "autonomous",
        "-w",
        "/home/autonomous/workspace",
        "-e",
        "TERM=xterm-256color",
        "-e",
        "LANG=C.UTF-8",
        "-e",
        "HOME=/home/autonomous",
        name,
        "bash",
        "-lc",
        command,
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        exit_code = int(completed.returncode)
        output = (completed.stdout or "") + (completed.stderr or "")
    except FileNotFoundError as exc:
        raise AutonomousError("docker CLI not found on host") from exc
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        parts = []
        if exc.stdout:
            parts.append(exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace"))
        if exc.stderr:
            parts.append(exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", "replace"))
        parts.append(f"[timeout after {timeout_s}s]")
        output = "".join(parts)

    output = output + _utc_date_note(command, home)
    return append_log(bot, command, exit_code=exit_code, output=output, home=home)
