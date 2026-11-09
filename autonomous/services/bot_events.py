"""Scheduled tasks (cron stored in UTC) + inbound webhooks → chat queue.

Input and the public `cron` field use the timezone from settings
(`timezone`), or the host clock when that setting is empty. `cron_utc` /
`next_run_at` stay UTC. The offset is the zone's at conversion time (DST can
drift until the cron is saved again).
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services.cronutil import (
    format_local,
    format_utc_offset,
    host_clock,
    iso_utc,
    local_cron_to_utc,
    next_run_after,
    parse_cron,
    user_clock,
    user_tz_name,
    utc_cron_to_local,
    utc_now,
    validate_cron,
    zone_offset_minutes,
)
from autonomous.services.errors import NotFound, ValidationError
from autonomous.services.events import BUS

log = logging.getLogger("autonomous.bot_events")

_NAME_MAX = 64
_INSTR_MAX = 8000
# A one-shot whose clock time already passed today rolls ~24h. That is how a
# UTC hour (from `date -u`) becomes "tomorrow" instead of "in a few minutes".
_ONESHOT_FAR = timedelta(hours=20)
# A one-shot with several close slots (every 5 min) used to be deleted after
# the first tick. Keep it while the next slot is still part of that burst.
_ONESHOT_SERIES = timedelta(minutes=15)


def _now() -> str:
    return iso_utc(utc_now())


def _public_cron(stored_utc: str, *, home: Path | None = None) -> tuple[str, str, str]:
    """Return (local cron, timezone name, utc offset) for a stored UTC expression."""
    name = user_tz_name(home)
    try:
        local = utc_cron_to_local(stored_utc, tz_name=name)
    except ValueError:
        log.warning("Cannot display cron %r in %s", stored_utc, name or "host")
        return stored_utc, "UTC", "+00:00"
    if name:
        return local, name, format_utc_offset(zone_offset_minutes(name))
    clock = host_clock()
    return local, clock["timezone"], clock["utc_offset"]


def _store_local_cron(expr: str, *, home: Path | None = None) -> str:
    try:
        local = validate_cron(expr)
        return local_cron_to_utc(local, tz_name=user_tz_name(home))
    except ValueError as exc:
        raise ValidationError(str(exc), code="invalid_cron") from exc


def _parse_utc(value: str) -> datetime:
    text = (value or "").replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _guard_oneshot(
    stored_cron: str,
    next_at: datetime,
    now: datetime,
    *,
    recurring: bool,
    home: Path | None = None,
) -> None:
    """Refuse a one-shot that silently jumped to the next day.

    A pinned day-of-month or weekday is an explicit later date and stays allowed.
    """
    if recurring or next_at - now <= _ONESHOT_FAR:
        return
    _minute, _hour, dom, _month, dow = parse_cron(stored_cron)
    if len(dom) != 31 or len(dow) != 7:
        return
    clock = user_clock(home)
    tz = clock["timezone"]
    local_next = format_local(next_at, user_tz_name(home))
    raise ValidationError(
        f"This one-shot would next run at {local_next} {tz} "
        f"(now {clock['now']} {tz}, UTC{clock['utc_offset']}), "
        "because that clock time already passed today. "
        f"Cron hours are {tz}, not UTC. "
        "`date -u` prints UTC and ignores TZ= — do not add the offset yourself. "
        f"For a few minutes from now, use the hour and minute of {clock['now']}. "
        "To mean a later calendar day, set day-of-month and month.",
        code="oneshot_too_far",
    )


def _decode_schedule(row, *, home: Path | None = None) -> dict[str, Any]:
    bot_id = row["bot"]
    stored = row["cron"]
    local, tz_name, offset = _public_cron(stored, home=home)
    return {
        "id": row["id"],
        "bot_id": bot_id,
        "bot": _bot_slug(bot_id, home=home),
        "name": row["name"],
        "cron": local,
        "cron_utc": stored,
        "recurring": bool(row["recurring"]),
        "instruction": row["instruction"] or "",
        "anchor_message_id": row["anchor_message_id"] or None,
        "enabled": bool(row["enabled"]),
        "next_run_at": row["next_run_at"],
        "next_run_local": format_local(_parse_utc(row["next_run_at"]), user_tz_name(home)),
        "now_local": user_clock(home)["now"],
        "last_run_at": row["last_run_at"] or None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "timezone": tz_name,
        "utc_offset": offset,
    }


def _decode_webhook(row, *, include_token: bool = True, home: Path | None = None) -> dict[str, Any]:
    bot_id = row["bot"]
    out = {
        "id": row["id"],
        "bot_id": bot_id,
        "bot": _bot_slug(bot_id, home=home),
        "name": row["name"],
        "instruction": row["instruction"] or "",
        "anchor_message_id": row["anchor_message_id"] or None,
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        # Fire via POST + Authorization: Bearer <token>.
        "url_path": "/api/v1/hooks",
    }
    if include_token:
        out["token"] = row["token"]
    return out


def _clean_name(name: str) -> str:
    text = (name or "").strip()
    if not text or len(text) > _NAME_MAX:
        raise ValidationError(f"name required (1–{_NAME_MAX} chars)")
    return text


def _clean_instruction(instruction: str) -> str:
    text = (instruction or "").strip()
    if len(text) > _INSTR_MAX:
        raise ValidationError(f"instruction too long (max {_INSTR_MAX})")
    return text


def _clean_anchor(anchor: str | None) -> str | None:
    if anchor is None or str(anchor).strip() == "":
        return None
    return str(anchor).strip()



def _bot_id(bot: str, *, home: Path | None) -> str:
    """Slug or UUID → stable bots.id for storage."""
    return bots_svc.bot_uuid(bot, home=home)


def _bot_slug(bot_id: str, *, home: Path | None) -> str:
    try:
        return bots_svc.get_bot_by_id(bot_id, home=home)["name"]
    except NotFound:
        return bot_id

# --- Schedules -----------------------------------------------------------------


def list_schedules(bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM bot_schedules
            WHERE bot = ?
            ORDER BY created_at ASC
            """,
            (bid,),
        ).fetchall()
    return [_decode_schedule(r, home=home) for r in rows]


def get_schedule(bot: str, schedule_id: str, *, home: Path | None = None) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM bot_schedules WHERE id = ? AND bot = ?",
            (schedule_id, _bot_id(bot, home=home)),
        ).fetchone()
    if not row:
        raise NotFound("Schedule not found", code="schedule_not_found")
    return _decode_schedule(row, home=home)


def create_schedule(
    bot: str,
    *,
    name: str,
    cron: str,
    instruction: str = "",
    recurring: bool = True,
    anchor_message_id: str | None = None,
    enabled: bool = True,
    home: Path | None = None,
) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    name = _clean_name(name)
    cron = _store_local_cron(cron, home=home)
    instruction = _clean_instruction(instruction)
    anchor = _clean_anchor(anchor_message_id)
    sid = str(uuid.uuid4())
    now = utc_now()
    next_at = next_run_after(cron, now)
    _guard_oneshot(cron, next_at, now, recurring=recurring, home=home)
    created = _now()
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO bot_schedules(
              id, bot, name, cron, recurring, instruction, anchor_message_id,
              enabled, next_run_at, last_run_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                sid,
                bid,
                name,
                cron,
                1 if recurring else 0,
                instruction,
                anchor,
                1 if enabled else 0,
                iso_utc(next_at),
                created,
                created,
            ),
        )
    row = get_schedule(bot, sid, home=home)
    BUS.publish("schedule.updated", {"schedule": row}, bot=bot)
    return row


def update_schedule(
    bot: str,
    schedule_id: str,
    fields: dict[str, Any],
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    cur = get_schedule(bot, schedule_id, home=home)
    name = _clean_name(fields["name"]) if "name" in fields else cur["name"]
    if "cron" in fields:
        cron = _store_local_cron(fields["cron"], home=home)
    else:
        cron = cur["cron_utc"]
    instruction = (
        _clean_instruction(fields["instruction"])
        if "instruction" in fields
        else cur["instruction"]
    )
    recurring = (
        bool(fields["recurring"]) if "recurring" in fields else cur["recurring"]
    )
    enabled = bool(fields["enabled"]) if "enabled" in fields else cur["enabled"]
    if "anchor_message_id" in fields:
        anchor = _clean_anchor(fields.get("anchor_message_id"))
    else:
        anchor = cur["anchor_message_id"]

    next_at = cur["next_run_at"]
    if "cron" in fields:
        now = utc_now()
        nxt = next_run_after(cron, now)
        _guard_oneshot(cron, nxt, now, recurring=recurring, home=home)
        next_at = iso_utc(nxt)

    updated = _now()
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE bot_schedules SET
              name = ?, cron = ?, recurring = ?, instruction = ?,
              anchor_message_id = ?, enabled = ?, next_run_at = ?, updated_at = ?
            WHERE id = ? AND bot = ?
            """,
            (
                name,
                cron,
                1 if recurring else 0,
                instruction,
                anchor,
                1 if enabled else 0,
                next_at,
                updated,
                schedule_id,
                _bot_id(bot, home=home),
            ),
        )
    row = get_schedule(bot, schedule_id, home=home)
    BUS.publish("schedule.updated", {"schedule": row}, bot=bot)
    return row


def delete_schedule(bot: str, schedule_id: str, *, home: Path | None = None) -> None:
    get_schedule(bot, schedule_id, home=home)
    with get_db(home) as conn:
        conn.execute(
            "DELETE FROM bot_schedules WHERE id = ? AND bot = ?",
            (schedule_id, _bot_id(bot, home=home)),
        )
    BUS.publish(
        "schedule.deleted",
        {"bot": bot, "id": schedule_id},
        bot=bot,
    )


def due_schedules(*, home: Path | None = None) -> list[dict[str, Any]]:
    now = iso_utc(utc_now())
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM bot_schedules
            WHERE enabled = 1 AND next_run_at <= ?
            ORDER BY next_run_at ASC
            """,
            (now,),
        ).fetchall()
    return [_decode_schedule(r, home=home) for r in rows]


def fire_schedule(schedule: dict[str, Any], *, home: Path | None = None) -> dict[str, Any] | None:
    """Inject chat message for a due schedule; advance or delete. Returns message or None."""
    bot = schedule["bot"]
    sid = schedule["id"]
    name = schedule["name"]
    instruction = schedule.get("instruction") or ""
    anchor = schedule.get("anchor_message_id")
    lines = [f"La tâche planifiée « {name} » dit ceci :", instruction or "(aucune instruction)"]
    if anchor:
        lines.append(f"\nContexte ancré : message {anchor}")
    content = "\n".join(lines).strip()
    meta = {
        "kind": "schedule",
        "schedule_id": sid,
        "name": name,
        "instruction": instruction,
        "anchor_message_id": anchor,
    }
    msg = inject_trigger_message(bot, content, meta=meta, home=home)

    now = utc_now()
    try:
        nxt = next_run_after(schedule.get("cron_utc") or schedule["cron"], now)
    except ValueError:
        log.exception("Failed to compute next_run for schedule %s", sid)
        nxt = now if schedule.get("recurring") else None
    keep = bool(schedule.get("recurring")) or (
        nxt is not None and nxt - now <= _ONESHOT_SERIES
    )
    if not keep:
        with get_db(home) as conn:
            conn.execute("DELETE FROM bot_schedules WHERE id = ?", (sid,))
        BUS.publish("schedule.deleted", {"bot": bot, "id": sid}, bot=bot)
        return msg

    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE bot_schedules
            SET last_run_at = ?, next_run_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (iso_utc(now), iso_utc(nxt), iso_utc(now), sid),
        )
    row = get_schedule(bot, sid, home=home)
    BUS.publish("schedule.updated", {"schedule": row}, bot=bot)
    return msg


# --- Webhooks ------------------------------------------------------------------


def list_webhooks(bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM bot_webhooks
            WHERE bot = ?
            ORDER BY created_at ASC
            """,
            (bid,),
        ).fetchall()
    return [_decode_webhook(r, home=home) for r in rows]


def get_webhook(bot: str, webhook_id: str, *, home: Path | None = None) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM bot_webhooks WHERE id = ? AND bot = ?",
            (webhook_id, _bot_id(bot, home=home)),
        ).fetchone()
    if not row:
        raise NotFound("Webhook not found", code="webhook_not_found")
    return _decode_webhook(row, home=home)


def get_webhook_by_token(token: str, *, home: Path | None = None) -> dict[str, Any]:
    token = (token or "").strip()
    if not token:
        raise NotFound("Webhook not found", code="webhook_not_found")
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM bot_webhooks WHERE token = ?",
            (token,),
        ).fetchone()
    if not row:
        raise NotFound("Webhook not found", code="webhook_not_found")
    return _decode_webhook(row, home=home)


def create_webhook(
    bot: str,
    *,
    name: str,
    instruction: str = "",
    anchor_message_id: str | None = None,
    enabled: bool = True,
    home: Path | None = None,
) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    name = _clean_name(name)
    instruction = _clean_instruction(instruction)
    anchor = _clean_anchor(anchor_message_id)
    wid = str(uuid.uuid4())
    token = secrets.token_urlsafe(24)
    created = _now()
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO bot_webhooks(
              id, bot, name, token, instruction, anchor_message_id,
              enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                wid,
                bid,
                name,
                token,
                instruction,
                anchor,
                1 if enabled else 0,
                created,
                created,
            ),
        )
    row = get_webhook(bot, wid, home=home)
    BUS.publish("webhook.updated", {"webhook": row}, bot=bot)
    return row


def update_webhook(
    bot: str,
    webhook_id: str,
    fields: dict[str, Any],
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    cur = get_webhook(bot, webhook_id, home=home)
    name = _clean_name(fields["name"]) if "name" in fields else cur["name"]
    instruction = (
        _clean_instruction(fields["instruction"])
        if "instruction" in fields
        else cur["instruction"]
    )
    enabled = bool(fields["enabled"]) if "enabled" in fields else cur["enabled"]
    if "anchor_message_id" in fields:
        anchor = _clean_anchor(fields.get("anchor_message_id"))
    else:
        anchor = cur["anchor_message_id"]
    updated = _now()
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE bot_webhooks SET
              name = ?, instruction = ?, anchor_message_id = ?,
              enabled = ?, updated_at = ?
            WHERE id = ? AND bot = ?
            """,
            (name, instruction, anchor, 1 if enabled else 0, updated, webhook_id, _bot_id(bot, home=home)),
        )
    row = get_webhook(bot, webhook_id, home=home)
    BUS.publish("webhook.updated", {"webhook": row}, bot=bot)
    return row


def delete_webhook(bot: str, webhook_id: str, *, home: Path | None = None) -> None:
    get_webhook(bot, webhook_id, home=home)
    with get_db(home) as conn:
        conn.execute(
            "DELETE FROM bot_webhooks WHERE id = ? AND bot = ?",
            (webhook_id, _bot_id(bot, home=home)),
        )
    BUS.publish("webhook.deleted", {"bot": bot, "id": webhook_id}, bot=bot)


_WEBHOOK_PAYLOAD_PROMPT_MAX = 24_000


def _format_webhook_payload_for_prompt(payload: Any) -> str:
    """Pretty JSON (or string) for the agent prompt, size-capped."""
    if isinstance(payload, str):
        text = payload
    else:
        try:
            text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(payload)
    text = (text or "").strip()
    if len(text) > _WEBHOOK_PAYLOAD_PROMPT_MAX:
        text = text[:_WEBHOOK_PAYLOAD_PROMPT_MAX] + "\n… (payload tronqué)"
    return text


def fire_webhook(
    token: str,
    *,
    payload: Any = None,
    home: Path | None = None,
) -> dict[str, Any]:
    wh = get_webhook_by_token(token, home=home)
    if not wh.get("enabled"):
        raise NotFound("Webhook not found", code="webhook_disabled")
    bot = wh["bot"]
    name = wh["name"]
    instruction = wh.get("instruction") or ""
    anchor = wh.get("anchor_message_id")
    has_payload = payload is not None and payload != "" and payload != {}
    if has_payload:
        content = "Webhook déclenché avec une charge."
    else:
        content = "Webhook déclenché."
    if instruction:
        content = f"{content}\n{instruction}"
    if anchor:
        content = f"{content}\n\nContexte ancré : message {anchor}"
    meta: dict[str, Any] = {
        "kind": "webhook",
        "webhook_id": wh["id"],
        "name": name,
        "instruction": instruction,
        "anchor_message_id": anchor,
    }
    agent_prompt: str | None = None
    if has_payload:
        meta["payload"] = payload
        meta["has_payload"] = True
        # UI keeps a short bubble + <details> payload; the agent must see the
        # body to apply standing rules (e.g. forward purchase mails to @achat).
        agent_prompt = (
            f"{content}\n\nPayload :\n{_format_webhook_payload_for_prompt(payload)}"
        )
    return inject_trigger_message(
        bot, content, meta=meta, home=home, agent_prompt=agent_prompt
    )


# --- Shared inject -------------------------------------------------------------


def inject_trigger_message(
    bot: str,
    content: str,
    *,
    meta: dict[str, Any],
    home: Path | None = None,
    agent_prompt: str | None = None,
) -> dict[str, Any]:
    """Insert a user-role trigger message; queue or start_run like composer."""
    bots_svc.get_bot(bot, home=home)
    content = (content or "").strip()
    if not content:
        raise ValidationError("content required")
    meta = dict(meta or {})
    prompt = (agent_prompt or "").strip() or content
    if prompt != content:
        meta["agent_prompt"] = prompt
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    blocked = chat_svc.bot_run_blocked(bot, home=home)
    if blocked:
        meta["queued"] = True
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO messages(
              id, bot, conversation_id, role, content,
              attachments_json, meta_json, created_at
            ) VALUES (?, ?, 'main', 'user', ?, '[]', ?, ?)
            """,
            (msg_id, bot, content, json.dumps(meta), now),
        )
    message = {
        "id": msg_id,
        "bot": bot,
        "conversation_id": "main",
        "role": "user",
        "content": content,
        "attachments": [],
        "meta": meta,
        "created_at": now,
    }
    BUS.publish("message.created", {"message": message}, bot=bot)
    if not blocked:
        chat_svc._start_agent_for_user_message(bot, prompt, [], home=home)
    return message
