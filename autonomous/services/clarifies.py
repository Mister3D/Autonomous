"""Structured clarify cards (choices and/or short text) — blocking for the agent."""

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

log = logging.getLogger("autonomous.clarifies")

_TITLE_MAX = 120
_PROMPT_MAX = 2000
_CHOICE_MAX = 80
_CHOICES_MAX = 8
_TEXT_MAX = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_choices(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def _clean_choices(choices: list[str] | None) -> list[str]:
    if not choices:
        return []
    if len(choices) > _CHOICES_MAX:
        raise ValidationError(
            f"at most {_CHOICES_MAX} choices", code="clarify_choices"
        )
    out: list[str] = []
    seen: set[str] = set()
    for item in choices:
        label = str(item or "").strip()
        if not label:
            raise ValidationError("empty choice", code="clarify_choices")
        if len(label) > _CHOICE_MAX:
            raise ValidationError(
                f"choice too long (max {_CHOICE_MAX})", code="clarify_choices"
            )
        key = label.casefold()
        if key in seen:
            raise ValidationError("duplicate choice", code="clarify_choices")
        seen.add(key)
        out.append(label)
    if len(out) == 1:
        raise ValidationError("provide at least 2 choices", code="clarify_choices")
    return out


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
        "choices": _load_choices(row["choices_json"]),
        "allow_text": bool(row["allow_text"]),
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
    choices: list[str] | None = None,
    allow_text: bool | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    text = (prompt or "").strip()
    if not text:
        raise ValidationError("prompt required", code="clarify_empty")
    if len(text) > _PROMPT_MAX:
        raise ValidationError(f"prompt too long (max {_PROMPT_MAX})")
    head = (title or "").strip() or "Précision"
    if len(head) > _TITLE_MAX:
        raise ValidationError(f"title too long (max {_TITLE_MAX})")
    labels = _clean_choices(choices)
    if allow_text is None:
        allow_text = not labels
    if not labels and not allow_text:
        raise ValidationError(
            "choices or allow_text required", code="clarify_empty"
        )

    bid = bots_svc.bot_uuid(bot, home=home)
    rid = str(uuid.uuid4())
    now = _now()
    lines = [head, f"Bot: {bot}", text]
    if labels:
        lines.append("Choix : " + " | ".join(labels))
    if allow_text:
        lines.append("Réponse courte possible.")
    content = "\n".join(lines)
    meta = {
        "kind": "clarify_request",
        "request_id": rid,
        "title": head,
        "prompt": text,
        "choices": labels,
        "allow_text": bool(allow_text),
        "state": "pending",
        "answer": "",
    }
    msg = chat_svc.create_message(
        bot,
        content,
        role="event",
        meta=meta,
        home=home,
    )
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO clarify_requests(
              id, bot, title, prompt, choices_json, allow_text, state,
              message_id, result_json, created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, '{}', ?, NULL)
            """,
            (
                rid,
                bid,
                head,
                text,
                json.dumps(labels, ensure_ascii=False),
                1 if allow_text else 0,
                msg["id"],
                now,
            ),
        )
    try:
        bots_svc.patch_bot(bot, {"status": "waiting"}, home=home)
    except Exception:
        log.exception("clarify waiting status for %s", bot)
    out = get_request(rid, home=home)
    BUS.publish("clarify.request", {"request": out}, bot=bot)
    return out


def get_request(request_id: str, *, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM clarify_requests WHERE id = ?", (request_id,)
        ).fetchone()
    if not row:
        raise NotFound(f"Clarify request not found: {request_id}")
    return _decode(row, home=home)


def list_pending_for_bot(bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    bid = bots_svc.bot_uuid(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM clarify_requests
            WHERE bot = ? AND state = 'pending'
            ORDER BY created_at
            """,
            (bid,),
        ).fetchall()
    return [_decode(r, home=home) for r in rows]


def _card_meta(req: dict[str, Any], *, state: str, answer: str = "") -> dict[str, Any]:
    return {
        "kind": "clarify_request",
        "request_id": req["id"],
        "title": req.get("title") or "",
        "prompt": req.get("prompt") or "",
        "choices": req.get("choices") or [],
        "allow_text": bool(req.get("allow_text")),
        "state": state,
        "answer": answer,
    }


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
            UPDATE clarify_requests
            SET state = ?, result_json = ?, resolved_at = ?
            WHERE id = ?
            """,
            (state, json.dumps(result, ensure_ascii=False), now, req["id"]),
        )
    answer = str(result.get("answer") or "")
    if req.get("message_id"):
        if state == "answered":
            label = f"Précision : {answer}"
        elif state == "cancelled" or result.get("human_redirect"):
            label = "Précision : annulée (message chat)."
        else:
            label = "Précision : fermée."
        chat_svc.update_message(
            req["bot"],
            req["message_id"],
            label,
            home=home,
            meta=_card_meta(req, state=state, answer=answer),
        )
    out = get_request(req["id"], home=home)
    BUS.publish("clarify.request", {"request": out}, bot=req["bot"])
    try:
        _resume_or_unstick(req["bot"], home=home)
    except Exception:
        log.exception("clarify resume for %s", req["bot"])
    return out


def resolve_request(
    request_id: str,
    *,
    choice: str = "",
    text: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    req = get_request(request_id, home=home)
    if req["state"] != "pending":
        return req
    picked = (choice or "").strip()
    typed = (text or "").strip()
    if picked and typed:
        raise ValidationError("send a choice or a text, not both", code="clarify_answer")
    if picked:
        if picked not in (req.get("choices") or []):
            raise ValidationError("choice is not one of the options", code="clarify_answer")
        return _finalize(
            req,
            state="answered",
            result={
                "ok": True,
                "answered": True,
                "via": "choice",
                "answer": picked,
                "message": f"User answered: {picked}",
            },
            home=home,
        )
    if typed:
        if not req.get("allow_text"):
            raise ValidationError("text answer is not allowed", code="clarify_answer")
        if len(typed) > _TEXT_MAX:
            raise ValidationError(f"text too long (max {_TEXT_MAX})", code="clarify_answer")
        return _finalize(
            req,
            state="answered",
            result={
                "ok": True,
                "answered": True,
                "via": "text",
                "answer": typed,
                "message": f"User answered: {typed}",
            },
            home=home,
        )
    raise ValidationError("choice or text required", code="clarify_answer")


def cancel_pending_for_human_message(
    bot: str,
    content: str,
    *,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    """Cancel pending clarify cards when the user writes in chat."""
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
            "User skipped the clarify card and wrote in chat. "
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
            "DELETE FROM clarify_requests WHERE bot = ?", (bot_id,)
        ).rowcount
