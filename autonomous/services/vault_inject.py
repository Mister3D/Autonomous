"""Inject a vault secret into the bot desk keyboard / clipboard — never via LLM."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from autonomous.paths import bot_dir
from autonomous.services import bots as bots_svc
from autonomous.services import vault as vault_svc
from autonomous.services.errors import AutonomousError, NotFound, ValidationError

_WORKER = Path(__file__).resolve().parent / "vnc_type_worker.py"
_CONTAINER_WORKER = "/home/autonomous/workspace/.autonomous/_vnc_type_worker.py"


def _chown_bot(path: Path) -> None:
    try:
        os.chown(path, 1000, 1000)
    except OSError:
        pass


def _secret_for_bot(
    bot: str,
    entry_id: str,
    field: str | None,
    *,
    home: Path | None,
) -> tuple[str, str]:
    """Return (field_id, secret_value). Raises if no grant / missing field."""
    bots_svc.get_bot(bot, home=home)
    if not vault_svc.bot_has_grant(bot, entry_id, home=home):
        raise AutonomousError(
            "This bot has no grant for that vault entry. "
            "Use request_vault_access first.",
            code="vault_forbidden",
        )
    # Public metadata first (field ids only), then reveal for the chosen field.
    meta = vault_svc.get_entry(entry_id, home=home, reveal=False)
    known_ids = [
        str(f.get("id"))
        for f in (meta.get("fields") or [])
        if isinstance(f, dict) and f.get("id") and f.get("secret", True)
    ]
    entry = vault_svc.get_entry(entry_id, home=home, reveal=True)
    secrets: dict[str, str] = dict(entry.get("secrets") or {})
    if not secrets and entry.get("secret"):
        secrets = {"secret": str(entry["secret"])}
    if not secrets:
        raise AutonomousError("Vault entry has no secret payload", code="vault_empty")

    field_id = (field or "").strip()
    if field_id and field_id not in secrets and len(secrets) == 1 and field_id.lower() in (
        "password", "pass", "passwd", "pwd", "secret", "mot_de_passe",
    ):
        # Agents guess « password »; a single-secret entry has only one candidate.
        field_id = next(iter(secrets))
    if field_id:
        if field_id not in secrets:
            hint = ", ".join(known_ids) if known_ids else ", ".join(sorted(secrets.keys()))
            raise ValidationError(
                f"Unknown secret field {field_id!r}. Known: {hint}"
            )
        return field_id, secrets[field_id]

    # Prefer common password-like keys, else first secret value.
    for prefer in ("password", "secret", "api_key", "token"):
        if prefer in secrets:
            return prefer, secrets[prefer]
    fid = next(iter(secrets.keys()))
    return fid, secrets[fid]


def _require_editable_focus(bot: str, *, home: Path | None) -> None:
    """Refuse to type a secret into nothing.

    If the browser window has focus and the focused element is not an editable
    field, the keystrokes would be lost (or land on a page shortcut). Terminals,
    cross-origin iframes and an unreachable CDP are not blocked.
    """
    try:
        from autonomous.services import browser as browser_svc

        info = browser_svc._run(bot, ["focus_info"], home=home)
    except Exception:
        return
    if not info.get("has_focus") or info.get("editable") or info.get("tag") == "IFRAME":
        return
    raise ValidationError(
        "No editable field is focused in the browser (focused: "
        f"{info.get('tag') or 'none'}). Nothing was typed. Click the target field "
        "first using its screen=x,y from browser_snapshot / browser_frames_snapshot "
        "(not coordinates guessed from vm_look), then retry."
    )


def inject(
    bot: str,
    *,
    entry_id: str,
    field: str | None = None,
    method: str = "type",
    home: Path | None = None,
) -> dict[str, Any]:
    """Decrypt a granted secret and type/paste it into the focused desk window.

    The cleartext never appears in the return value (only length + metadata).
    """
    method = (method or "type").strip().lower()
    if method not in ("type", "paste"):
        raise ValidationError("method must be type|paste")

    b = bots_svc.get_bot(bot, home=home)
    if b.get("capability") == "none":
        raise AutonomousError(
            "Bot has no desktop capability — create a desk first.",
            code="no_capability",
        )
    desk = b.get("desk") or {}
    if desk.get("state") != "running":
        raise AutonomousError(
            "Desktop is not running — start the bot desk before injecting.",
            code="desk_not_running",
        )
    if not _WORKER.is_file():
        raise AutonomousError("VNC type worker missing on host", code="internal")

    _require_editable_focus(bot, home=home)

    field_id, secret = _secret_for_bot(bot, entry_id, field, home=home)
    if secret is None or secret == "":
        raise ValidationError("Secret field is empty")

    host_autonomous = bot_dir(bot, home) / "home" / ".autonomous"
    host_autonomous.mkdir(parents=True, exist_ok=True)
    _chown_bot(host_autonomous)
    host_worker = host_autonomous / "_vnc_type_worker.py"
    shutil.copyfile(_WORKER, host_worker)
    _chown_bot(host_worker)

    from autonomous.services import desk as desk_svc

    name = desk_svc.container_name(bot, home=home)
    cmd = [
        "docker",
        "exec",
        "-i",
        "-u",
        "autonomous",
        "-e",
        "HOME=/home/autonomous",
        name,
        "python3",
        _CONTAINER_WORKER,
        method,
    ]
    try:
        completed = subprocess.run(
            cmd,
            input=secret.encode("utf-8"),
            capture_output=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AutonomousError("docker CLI not found on host") from exc
    except subprocess.TimeoutExpired as exc:
        raise AutonomousError("Vault inject timed out", code="timeout") from exc
    finally:
        # Best-effort: avoid lingering cleartext in locals via overwrite intent.
        secret = ""  # noqa: F841

    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or b"unknown error").decode(
            "utf-8", errors="replace"
        ).strip()
        # Never echo stderr if it somehow contained payload (worker shouldn't).
        raise AutonomousError(
            f"Vault inject failed: {err[:300]}",
            code="vault_inject_failed",
        )

    # Parse "ok chars=N mode=..." — do not trust blindly
    out = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
    chars = 0
    for part in out.split():
        if part.startswith("chars="):
            try:
                chars = int(part.split("=", 1)[1])
            except ValueError:
                chars = 0
    return {
        "ok": True,
        "bot": bot,
        "entry_id": entry_id,
        "field": field_id,
        "method": method,
        "chars": chars,
        # Explicit: no secret in this payload
        "secret_returned": False,
    }
