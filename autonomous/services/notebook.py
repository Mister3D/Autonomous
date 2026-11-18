"""Per-bot notebook: standing orders, unfinished work, and notes.

The host appends a short trailer to each Pi prompt. The system prompt stays
frozen. Shared household memory is a different store.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db, row_to_dict
from autonomous.i18n import t
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import settings as settings_svc
from autonomous.services.errors import NotFound, ValidationError

log = logging.getLogger("autonomous.notebook")

_KINDS = ("order", "open", "note")
_CAPS = {"order": 12, "open": 10, "note": 30}
_BODY_MAX = {"order": 240, "open": 240, "note": 4000}
_TITLE_MAX = 80


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _bot_id(bot: str, *, home: Path | None) -> str:
    row = bots_svc.get_bot(bot, home=home)
    bid = str(row.get("id") or "").strip()
    if not bid:
        raise NotFound(f"Bot '{bot}' not found", code="bot_not_found")
    return bid


def _clean_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k not in _KINDS:
        raise ValidationError(
            "kind must be order, open, or note",
            code="notebook_bad_kind",
        )
    return k


def _clean_title(title: str, *, body: str) -> str:
    text = " ".join((title or "").split())
    if not text:
        text = " ".join((body or "").split())
    if len(text) > _TITLE_MAX:
        text = text[:_TITLE_MAX].rstrip()
    if not text:
        raise ValidationError("title required", code="notebook_empty_title")
    return text


def _clean_body(kind: str, body: str) -> str:
    text = (body or "").strip()
    if not text:
        raise ValidationError("body required", code="notebook_empty_body")
    limit = _BODY_MAX[kind]
    if len(text) > limit:
        raise ValidationError(
            f"body too long for {kind} (max {limit})",
            code="notebook_body_too_long",
        )
    return text


def _reject_vault_secret(*parts: str, home: Path | None) -> None:
    blob = "\n".join(p for p in parts if p)
    if not blob:
        return
    try:
        from autonomous.services import vault as vault_svc

        if vault_svc.text_contains_vault_secret(blob, home=home):
            raise ValidationError(
                "Notebook refused: that text contains a vault secret.",
                code="notebook_secret",
            )
    except ValidationError:
        raise
    except Exception:
        return


def _row(row) -> dict[str, Any]:
    data = row_to_dict(row) or {}
    return {
        "id": data.get("id") or "",
        "kind": data.get("kind") or "",
        "title": data.get("title") or "",
        "body": data.get("body") or "",
        "created_at": data.get("created_at") or "",
        "updated_at": data.get("updated_at") or "",
    }


def list_entries(bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT id, kind, title, body, created_at, updated_at
            FROM bot_notebook
            WHERE bot = ?
            ORDER BY
              CASE kind WHEN 'order' THEN 0 WHEN 'open' THEN 1 ELSE 2 END,
              CASE WHEN kind = 'note' THEN updated_at END DESC,
              updated_at ASC
            """,
            (bid,),
        ).fetchall()
    return [_row(r) for r in rows]


def get_entry(bot: str, entry_id: str, *, home: Path | None = None) -> dict[str, Any]:
    bid = _bot_id(bot, home=home)
    eid = (entry_id or "").strip()
    if not eid:
        raise ValidationError("id required", code="notebook_empty_id")
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT id, kind, title, body, created_at, updated_at
            FROM bot_notebook WHERE bot = ? AND id = ?
            """,
            (bid, eid),
        ).fetchone()
    if row is None:
        raise NotFound("Notebook entry not found", code="notebook_not_found")
    return _row(row)


def _find_title(
    conn, bid: str, kind: str, title: str
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, kind, title, body, created_at, updated_at
        FROM bot_notebook
        WHERE bot = ? AND kind = ? AND lower(title) = lower(?)
        """,
        (bid, kind, title),
    ).fetchone()
    return _row(row) if row else None


def _count(conn, bid: str, kind: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM bot_notebook WHERE bot = ? AND kind = ?",
        (bid, kind),
    ).fetchone()
    return int(row["c"] if row else 0)


def _notice(bot: str, entry: dict[str, Any], *, action: str, home: Path | None) -> None:
    lang = str(settings_svc.get("locale", home=home, default="en") or "en")
    tier = entry.get("kind") or "note"
    text = entry.get("body") or entry.get("title") or ""
    if action == "close":
        key = "notebook.removed"
        shown = entry.get("title") if tier == "note" else text
    elif tier == "order":
        key = "notebook.order"
        shown = text
    elif tier == "open":
        key = "notebook.open"
        shown = text
    else:
        key = "notebook.note"
        shown = entry.get("title") or text
    content = t(key, lang, text=shown)
    chat_svc.create_message(
        bot,
        content,
        role="system",
        meta={
            "kind": "notebook",
            "action": action,
            "tier": tier,
            "entry_id": entry.get("id") or "",
            "title": entry.get("title") or "",
            "text": shown,
        },
        home=home,
    )


def remember(
    bot: str,
    *,
    kind: str,
    body: str,
    title: str = "",
    entry_id: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    """Save or update one notebook row. Same title in the same kind updates."""
    bid = _bot_id(bot, home=home)
    kind = _clean_kind(kind)
    body = _clean_body(kind, body)
    title = _clean_title(title, body=body)
    _reject_vault_secret(title, body, home=home)
    eid = (entry_id or "").strip()
    now = _now()
    changed = True
    with get_db(home) as conn:
        current = None
        if eid:
            row = conn.execute(
                """
                SELECT id, kind, title, body, created_at, updated_at
                FROM bot_notebook WHERE bot = ? AND id = ?
                """,
                (bid, eid),
            ).fetchone()
            if row is None:
                raise NotFound("Notebook entry not found", code="notebook_not_found")
            current = _row(row)
            kind = current["kind"]
            body = _clean_body(kind, body)
            title = _clean_title(title, body=body)
        else:
            current = _find_title(conn, bid, kind, title)
        clash = _find_title(conn, bid, kind, title)
        if clash and (not current or clash["id"] != current["id"]):
            raise ValidationError(
                "That title is already used in this notebook.",
                code="notebook_title_taken",
            )
        if current and current["title"] == title and current["body"] == body:
            changed = False
            saved = current
        elif current:
            conn.execute(
                """
                UPDATE bot_notebook
                SET title = ?, body = ?, updated_at = ?
                WHERE bot = ? AND id = ?
                """,
                (title, body, now, bid, current["id"]),
            )
            saved = {**current, "title": title, "body": body, "updated_at": now}
        else:
            if _count(conn, bid, kind) >= _CAPS[kind]:
                raise ValidationError(
                    f"This bot already has {_CAPS[kind]} {kind} entries. "
                    "Close one with notebook_close before adding another.",
                    code="notebook_full",
                )
            new_id = _new_id()
            conn.execute(
                """
                INSERT INTO bot_notebook(id, bot, kind, title, body, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id, bid, kind, title, body, now, now),
            )
            saved = {
                "id": new_id,
                "kind": kind,
                "title": title,
                "body": body,
                "created_at": now,
                "updated_at": now,
            }
    if changed:
        try:
            _notice(bot, saved, action="set", home=home)
        except Exception:
            log.exception("notebook notice failed for %s", bot)
    return saved


def close_entry(bot: str, entry_id: str, *, home: Path | None = None) -> dict[str, Any]:
    entry = get_entry(bot, entry_id, home=home)
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        conn.execute(
            "DELETE FROM bot_notebook WHERE bot = ? AND id = ?",
            (bid, entry["id"]),
        )
    try:
        _notice(bot, entry, action="close", home=home)
    except Exception:
        log.exception("notebook notice failed for %s", bot)
    return entry


def prompt_trailer(bot: str, *, home: Path | None = None) -> str:
    """Short block appended to a Pi prompt. Empty when the notebook is empty."""
    try:
        rows = list_entries(bot, home=home)
    except NotFound:
        return ""
    if not rows:
        return ""
    orders = [r for r in rows if r["kind"] == "order"]
    opens = [r for r in rows if r["kind"] == "open"]
    notes = [r for r in rows if r["kind"] == "note"]
    lines = [
        "[Bot notebook]",
        "Private to this bot. Obey every standing order. "
        "If the user asks what was left to do, answer from the open lines. "
        "Call notebook_get for a note whose title matches the subject.",
    ]
    if orders:
        lines.append("Standing orders (notebook_close to drop):")
        lines.extend(f"- {r['id']} — {r['body']}" for r in orders)
    if opens:
        lines.append("Still to do (notebook_close when done):")
        lines.extend(f"- {r['id']} — {r['body']}" for r in opens)
    if notes:
        lines.append("Notes (notebook_get):")
        lines.extend(f"- {r['id']} — {r['title']}" for r in notes)
    return "\n".join(lines)


def attach_prompt(message: str, bot: str, *, home: Path | None = None) -> str:
    """Append the notebook to the text Pi receives. The chat bubble stays as written."""
    trailer = prompt_trailer(bot, home=home)
    if not trailer:
        return message
    base = message or ""
    if base.rstrip().endswith(trailer):
        return base
    if not base.strip():
        return trailer
    return f"{base.rstrip()}\n\n{trailer}"
