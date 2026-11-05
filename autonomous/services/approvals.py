"""Generic user approval cards (Accept / Refuse) — blocking for the agent tool."""

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
from autonomous.services.errors import NotFound, ValidationError
from autonomous.services.events import BUS

log = logging.getLogger("autonomous.approvals")

_TITLE_MAX = 120
_PROMPT_MAX = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(row, *, home: Path | None = None) -> dict[str, Any]:
    bot_id = row["bot"]
    try:
        bot_slug = bots_svc.get_bot_by_id(bot_id, home=home)["name"]
    except Exception:
        bot_slug = bot_id
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
        "state": row["state"],
        "message_id": row["message_id"],
        "result": result,
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def create_request(
    bot: str,
    *,
    prompt: str,
    title: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    text = (prompt or "").strip()
    if not text:
        raise ValidationError("prompt required", code="approval_empty")
    if len(text) > _PROMPT_MAX:
        raise ValidationError(f"prompt too long (max {_PROMPT_MAX})")
    head = (title or "").strip() or "Approbation"
    if len(head) > _TITLE_MAX:
        raise ValidationError(f"title too long (max {_TITLE_MAX})")

    bid = bots_svc.bot_uuid(bot, home=home)
    rid = str(uuid.uuid4())
    now = _now()
    lines = [head, f"Bot: {bot}", text, "Accepter ou refuser ci-dessous."]
    content = "\n".join(lines)
    msg = chat_svc.create_message(
        bot,
        content,
        role="event",
        meta={
            "kind": "approval_request",
            "request_id": rid,
            "title": head,
            "prompt": text,
            "state": "pending",
        },
        home=home,
    )
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO approval_requests(
              id, bot, title, prompt, state, message_id, result_json,
              created_at, resolved_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, '{}', ?, NULL)
            """,
            (rid, bid, head, text, msg["id"], now),
        )
    try:
        bots_svc.patch_bot(bot, {"status": "waiting"}, home=home)
    except Exception:
        log.exception("approval waiting status for %s", bot)
    out = get_request(rid, home=home)
    BUS.publish("approval.request", {"request": out}, bot=bot)
    return out


def get_request(request_id: str, *, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM approval_requests WHERE id = ?", (request_id,)
        ).fetchone()
    if not row:
        raise NotFound(f"Approval request not found: {request_id}")
    return _decode(row, home=home)


def list_pending_for_bot(bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    bid = bots_svc.bot_uuid(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM approval_requests
            WHERE bot = ? AND state = 'pending'
            ORDER BY created_at
            """,
            (bid,),
        ).fetchall()
    return [_decode(r, home=home) for r in rows]


def _finalize(
    req: dict[str, Any],
    *,
    state: str,
    result: dict[str, Any],
    home: Path | None = None,
) -> dict[str, Any]:
    now = _now()
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE approval_requests
            SET state = ?, result_json = ?, resolved_at = ?
            WHERE id = ?
            """,
            (state, json.dumps(result), now, req["id"]),
        )
    if req.get("message_id"):
        if state == "approved":
            label = "Approbation : acceptée."
        elif state == "cancelled" or result.get("human_redirect"):
            label = "Approbation : annulée (message chat)."
        else:
            label = "Approbation : refusée."
        chat_svc.update_message(
            req["bot"],
            req["message_id"],
            label,
            home=home,
            meta={
                "kind": "approval_request",
                "request_id": req["id"],
                "title": req.get("title") or "",
                "prompt": req.get("prompt") or "",
                "state": state,
            },
        )
    out = get_request(req["id"], home=home)
    BUS.publish("approval.request", {"request": out}, bot=req["bot"])
    try:
        _resume_or_unstick(req["bot"], home=home)
    except Exception:
        log.exception("approval resume for %s", req["bot"])
    return out


def resolve_request(
    request_id: str,
    *,
    action: str,
    home: Path | None = None,
) -> dict[str, Any]:
    req = get_request(request_id, home=home)
    if req["state"] != "pending":
        return req
    act = (action or "").strip().lower()
    if act not in ("approve", "deny"):
        raise ValidationError("action must be approve|deny")
    if act == "approve":
        return _finalize(
            req,
            state="approved",
            result={"ok": True, "approved": True, "message": "User accepted."},
            home=home,
        )
    return _finalize(
        req,
        state="denied",
        result={"ok": False, "denied": True, "message": "User refused."},
        home=home,
    )


def cancel_pending_for_human_message(
    bot: str,
    content: str,
    *,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    """Cancel pending approvals when the user writes in chat (not a hard deny)."""
    pending = list_pending_for_bot(bot, home=home)
    if not pending:
        return []
    note = (content or "").strip()
    result = {
        "ok": False,
        "cancelled": True,
        "human_redirect": True,
        "message": note,
        "guidance": (
            "User skipped the Accept/Refuse buttons and wrote in chat. "
            f"Follow their message: {note}"
        ),
    }
    out: list[dict[str, Any]] = []
    for req in pending:
        out.append(_finalize(req, state="cancelled", result=result, home=home))
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
            "DELETE FROM approval_requests WHERE bot = ?", (bot_id,)
        ).rowcount
