"""Global settings key/value store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autonomous.db import get_db

DEFAULTS: dict[str, Any] = {
    "guard.review_every": 100,
    "guard.max_actions": 1000,
    # Many OpenAI-compatible vision endpoints reject >2 images/prompt.
    "guard.max_images_per_prompt": 2,
    "grounding.max_loops": 2,
    "agent_backend": "pi",
    "desktop_image": "autonomous-desktop:latest",
    "ack_unwired_agent": False,
    "locale": "en",
    "timezone": "Europe/Paris",
    # First-run CTA on /setup — hidden once the onboarding chat has been started
    # or shared memory already holds preferences.
    "first_chat_done": False,
    # Bot slug awaiting the language clarify before the prefs script is sent.
    "first_chat_prefs_pending": None,
    # While true, memory_propose auto-saves (no Confirm card) for a fluid setup.
    "first_chat_onboarding": False,
    # Self-update git channel / branch (main = stable, dev = pre-release, or custom).
    "update.channel": "main",
    # Optional git remote URL for self-update (forks). Empty → use origin.
    "update.remote_url": "",
    # When false, public companion pairing (/devices/pair + pair-poll) is refused.
    "companions.enabled": True,
}

# Removed product setting (was a Cursor test harness, not a feature).
# Include the bad underscore key some PUTs wrote via Marshmallow attr names.
_OBSOLETE_KEYS = ("guard.max_runtime_sec", "guard_max_runtime_sec")


def ensure_defaults(home: Path | None = None) -> None:
    with get_db(home) as conn:
        for key, value in DEFAULTS.items():
            row = conn.execute(
                "SELECT key FROM settings WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO settings(key, value_json) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
        for key in _OBSOLETE_KEYS:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def get_all(home: Path | None = None) -> dict[str, Any]:
    ensure_defaults(home)
    with get_db(home) as conn:
        rows = conn.execute("SELECT key, value_json FROM settings").fetchall()
    out: dict[str, Any] = {}
    for row in rows:
        out[row["key"]] = json.loads(row["value_json"])
    return out


def get(key: str, home: Path | None = None, default: Any = None) -> Any:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT value_json FROM settings WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return DEFAULTS.get(key, default)
    return json.loads(row["value_json"])


def set_value(key: str, value: Any, home: Path | None = None) -> None:
    """Write one setting key (no cross-field guards)."""
    with get_db(home) as conn:
        conn.execute(
            "INSERT INTO settings(key, value_json) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
            (key, json.dumps(value)),
        )


def set_many(values: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    from autonomous.services.errors import ValidationError

    with get_db(home) as conn:
        for key, value in values.items():
            if key in _OBSOLETE_KEYS:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
                continue
            if key in ("update.channel", "update.remote_url"):
                row = conn.execute(
                    "SELECT value_json FROM settings WHERE key = ?", (key,)
                ).fetchone()
                current = (
                    json.loads(row["value_json"])
                    if row is not None
                    else DEFAULTS.get(key, "" if key.endswith("url") else "main")
                )
                want = str(value or "").strip()
                cur = str(current or "").strip()
                if key == "update.channel":
                    want = want.lower()
                    cur = cur.lower()
                if want != cur:
                    raise ValidationError(
                        "Use PUT /setup/update to change update.channel / update.remote_url",
                        code="use_setup_update",
                    )
                continue
            if key == "timezone":
                from autonomous.services.cronutil import normalize_tz_setting

                value = normalize_tz_setting(value)
            if key == "locale":
                code = str(value or "").strip().lower()
                if code not in ("en", "fr"):
                    raise ValidationError(
                        "locale must be en or fr",
                        code="invalid_locale",
                    )
                value = code
            conn.execute(
                "INSERT INTO settings(key, value_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                (key, json.dumps(value)),
            )
    return get_all(home)
