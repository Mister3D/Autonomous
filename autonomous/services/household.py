"""Manager household tools: create bots + confirmed multi-bot delete."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import settings as settings_svc
from autonomous.services.errors import Forbidden, NotFound, ValidationError
from autonomous.services.events import BUS

log = logging.getLogger("autonomous.household")

_TITLE_MAX = 120
_PROMPT_MAX = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_manager(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    me = bots_svc.get_bot(bot, home=home)
    if not me.get("is_manager"):
        raise Forbidden(
            "Only a Manager bot can manage the household.",
            code="manager_required",
        )
    return me


def default_model(*, home: Path | None = None) -> str:
    return str(settings_svc.get("bots.default_model", home=home, default="") or "").strip()


def list_available_models(*, home: Path | None = None) -> list[dict[str, Any]]:
    from autonomous.services import pi_status

    return pi_status.list_models()


def create_bots(
    manager: str,
    specs: list[dict[str, Any]],
    *,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    """Create one or more bots. Manager only. Never creates a second manager."""
    require_manager(manager, home=home)
    if not specs:
        raise ValidationError("bots list required", code="bots_required")
    model = default_model(home=home)
    if not model:
        raise ValidationError(
            "No default model.",
            code="model_required",
        )
    created: list[dict[str, Any]] = []
    errors: list[str] = []
    for spec in specs:
        name = str((spec or {}).get("name") or "").strip()
        if not name:
            errors.append("empty name")
            continue
        try:
            bot = bots_svc.create_bot(
                name,
                label=(spec or {}).get("label"),
                slug=(spec or {}).get("slug"),
                internet=bool((spec or {}).get("internet", True)),
                memory_access=bool((spec or {}).get("memory_access", True)),
                is_manager=False,
                model=model,
                avatar=(spec or {}).get("avatar"),
                avatar_color=(spec or {}).get("avatar_color"),
                home=home,
            )
            created.append(
                {
                    "name": bot["name"],
                    "label": bot.get("label") or bot["name"],
                    "model": bot.get("model") or model,
                }
            )
        except ValidationError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", "") or ""
            errors.append(f"{name}: {exc}" + (f" ({code})" if code else ""))
    if not created and errors:
        raise ValidationError("; ".join(errors), code="create_failed")
    return created


def _decode_delete(row, *, home: Path | None = None) -> dict[str, Any]:
    bot_id = row["bot"]
    try:
        bot_slug = bots_svc.get_bot_by_id(bot_id, home=home)["name"]
    except Exception:
        bot_slug = bot_id
    try:
        bots = json.loads(row["bots_json"] or "[]")
    except json.JSONDecodeError:
        bots = []
    try:
        result = json.loads(row["result_json"] or "{}")
    except json.JSONDecodeError:
        result = {}
    return {
        "id": row["id"],
        "bot_id": bot_id,
        "bot": bot_slug,
        "title": row["title"] or "",
        "prompt": row["prompt"] or "",
        "bots": bots if isinstance(bots, list) else [],
        "state": row["state"],
        "message_id": row["message_id"],
        "result": result,
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def create_delete_request(
    manager: str,
    *,
    bots: list[str],
    prompt: str = "",
    title: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    me = require_manager(manager, home=home)
    names = []
    for raw in bots or []:
        n = str(raw or "").strip().lstrip("@")
        if n and n not in names:
            names.append(n)
    if not names:
        raise ValidationError("bots required", code="bots_required")
    if me["name"] in names:
        raise ValidationError(
            "A Manager cannot delete itself via this card.",
            code="cannot_delete_self",
        )

    targets: list[dict[str, Any]] = []
    for n in names:
        try:
            row = bots_svc.get_bot(n, home=home)
        except NotFound:
            raise ValidationError(f"Unknown bot: {n}", code="bot_not_found") from None
        targets.append(
            {
                "name": row["name"],
                "label": row.get("label") or row["name"],
                "avatar": row.get("avatar") or "",
                "avatar_color": int(row.get("avatar_color") or 0),
                "selected": True,
            }
        )

    text = (prompt or "").strip() or "Delete the selected bots?"
    if len(text) > _PROMPT_MAX:
        raise ValidationError(f"prompt too long (max {_PROMPT_MAX})")
    head = (title or "").strip() or "Delete bots"
    if len(head) > _TITLE_MAX:
        raise ValidationError(f"title too long (max {_TITLE_MAX})")

    bid = bots_svc.bot_uuid(manager, home=home)
    rid = str(uuid.uuid4())
    now = _now()
    msg = chat_svc.create_message(
        manager,
        "\n".join([head, text, "Confirm or cancel below."]),
        role="event",
        meta={
            "kind": "bot_delete_request",
            "request_id": rid,
            "title": head,
            "prompt": text,
            "bots": targets,
            "state": "pending",
        },
        home=home,
    )
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO bot_delete_requests(
              id, bot, title, prompt, bots_json, state, message_id, result_json,
              created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, '{}', ?, NULL)
            """,
            (rid, bid, head, text, json.dumps(targets), msg["id"], now),
        )
    try:
        bots_svc.patch_bot(manager, {"status": "waiting"}, home=home)
    except Exception:
        log.exception("household delete waiting status for %s", manager)
    out = get_delete_request(rid, home=home)
    BUS.publish("bot_delete.request", {"request": out}, bot=manager)
    return out


def get_delete_request(request_id: str, *, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM bot_delete_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
    if not row:
        raise NotFound(f"Bot delete request not found: {request_id}")
    return _decode_delete(row, home=home)


def list_pending_delete_for_bot(bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    bid = bots_svc.bot_uuid(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM bot_delete_requests
            WHERE bot = ? AND state = 'pending'
            ORDER BY created_at
            """,
            (bid,),
        ).fetchall()
    return [_decode_delete(r, home=home) for r in rows]


def _finalize_delete(
    req: dict[str, Any],
    *,
    state: str,
    result: dict[str, Any],
    bots: list[dict[str, Any]] | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    now = _now()
    targets = bots if bots is not None else req.get("bots") or []
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE bot_delete_requests
            SET state = ?, result_json = ?, bots_json = ?, resolved_at = ?
            WHERE id = ?
            """,
            (state, json.dumps(result), json.dumps(targets), now, req["id"]),
        )
    if req.get("message_id"):
        if state == "confirmed":
            deleted = result.get("deleted") or []
            label = (
                f"Delete bots: removed {', '.join('@' + n for n in deleted)}."
                if deleted
                else "Delete bots: nothing selected."
            )
        elif state == "cancelled" or result.get("human_redirect"):
            label = "Delete bots: cancelled (chat message)."
        else:
            label = "Delete bots: cancelled."
        chat_svc.update_message(
            req["bot"],
            req["message_id"],
            label,
            home=home,
            meta={
                "kind": "bot_delete_request",
                "request_id": req["id"],
                "title": req.get("title") or "",
                "prompt": req.get("prompt") or "",
                "bots": targets,
                "state": state,
                "result": result,
            },
        )
    out = get_delete_request(req["id"], home=home)
    BUS.publish("bot_delete.request", {"request": out}, bot=req["bot"])
    try:
        _resume_or_unstick(req["bot"], home=home)
    except Exception:
        log.exception("household delete resume for %s", req["bot"])
    return out


def resolve_delete_request(
    request_id: str,
    *,
    action: str,
    selected: list[str] | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    req = get_delete_request(request_id, home=home)
    if req["state"] != "pending":
        return req
    act = (action or "").strip().lower()
    if act not in ("confirm", "deny", "approve", "cancel"):
        raise ValidationError("action must be confirm|deny")

    if act in ("deny", "cancel"):
        return _finalize_delete(
            req,
            state="denied",
            result={"ok": False, "denied": True, "deleted": [], "message": "User cancelled."},
            home=home,
        )

    allowed = {str(b.get("name") or "") for b in (req.get("bots") or [])}
    if req.get("bot"):
        allowed.discard(req["bot"])
    picks = []
    for raw in selected or []:
        n = str(raw or "").strip().lstrip("@")
        if n in allowed and n not in picks:
            picks.append(n)

    # Mark selection on the card payload.
    updated_bots = []
    for b in req.get("bots") or []:
        name = str(b.get("name") or "")
        updated_bots.append({**b, "selected": name in picks})

    deleted: list[str] = []
    errors: list[str] = []
    for name in picks:
        try:
            bots_svc.delete_bot(name, home=home, destroy_desk=True)
            deleted.append(name)
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    return _finalize_delete(
        req,
        state="confirmed",
        result={
            "ok": True,
            "confirmed": True,
            "deleted": deleted,
            "errors": errors,
            "message": (
                f"Deleted: {', '.join(deleted)}" if deleted else "No bots deleted."
            ),
        },
        bots=updated_bots,
        home=home,
    )


def cancel_pending_for_human_message(
    bot: str,
    content: str,
    *,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    pending = list_pending_delete_for_bot(bot, home=home)
    if not pending:
        return []
    note = (content or "").strip()
    result = {
        "ok": False,
        "cancelled": True,
        "human_redirect": True,
        "deleted": [],
        "message": note,
        "guidance": (
            "User skipped the delete card and wrote in chat. "
            f"Follow their message: {note}"
        ),
    }
    out: list[dict[str, Any]] = []
    for req in pending:
        out.append(_finalize_delete(req, state="cancelled", result=result, home=home))
    return out


def _resume_or_unstick(bot: str, *, home: Path | None = None) -> None:
    bot_row = bots_svc.get_bot(bot, home=home)
    if bot_row.get("status") not in ("waiting", "busy"):
        return
    alive = False
    try:
        from autonomous.services.pi_rpc import MANAGER

        sess = MANAGER.get(bot)
        alive = bool(sess and getattr(sess, "alive", False))
    except Exception:
        alive = False
    if alive:
        if bot_row.get("status") == "waiting":
            bots_svc.patch_bot(bot, {"status": "busy"}, home=home)
        return
    chat_svc.mark_interrupted_after_wait(bot, home=home)


def purge_for_bot(bot_id: str, *, home: Path | None = None) -> int:
    if not bot_id:
        return 0
    with get_db(home) as conn:
        return conn.execute(
            "DELETE FROM bot_delete_requests WHERE bot = ?", (bot_id,)
        ).rowcount
