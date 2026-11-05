"""Emoji reactions on the user's chat bubbles.

The agent calls ``react`` during a turn. The reaction is stored on that turn's
user message and never replaces the assistant reply.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services import bots as bots_svc
from autonomous.services.errors import NotFound, ValidationError

_MAX = 6
_lock = threading.Lock()
_turn_message: dict[str, str] = {}


def set_turn_message(bot: str, message_id: str | None) -> None:
    """Remember which user message the current run is answering."""
    with _lock:
        if message_id:
            _turn_message[bot] = message_id
        else:
            _turn_message.pop(bot, None)


def turn_message(bot: str) -> str | None:
    with _lock:
        return _turn_message.get(bot)


def _is_emoji(text: str) -> bool:
    if not text or len(text) > 16:
        return False
    if any(ch.isspace() or (ch.isascii() and ch.isalnum()) for ch in text):
        return False
    return any(ord(ch) >= 0x2300 for ch in text)


def normalize_emoji(raw: str) -> str:
    text = (raw or "").strip()
    if not _is_emoji(text):
        raise ValidationError("Une réaction doit être un emoji", code="invalid_emoji")
    return text


def add_reaction(
    bot: str,
    emoji: str,
    *,
    message_id: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Append one emoji on a user message. Idempotent if already present."""
    bots_svc.get_bot(bot, home=home)
    emoji = normalize_emoji(emoji)
    mid = (message_id or turn_message(bot) or "").strip()
    if not mid:
        raise ValidationError(
            "Aucun message utilisateur pour cette réaction",
            code="no_message",
        )
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT id, role, content, meta_json FROM messages WHERE id = ? AND bot = ?",
            (mid, bot),
        ).fetchone()
    if not row:
        raise NotFound("Message introuvable")
    if (row["role"] or "") != "user":
        raise ValidationError(
            "Une réaction se pose sur un message de l'utilisateur",
            code="not_user_message",
        )
    meta = json.loads(row["meta_json"] or "{}")
    current = [str(item) for item in (meta.get("reactions") or []) if str(item)]
    if emoji not in current:
        if len(current) >= _MAX:
            raise ValidationError(
                "Trop de réactions sur ce message",
                code="too_many_reactions",
            )
        current.append(emoji)
    meta["reactions"] = current
    from autonomous.services import chat as chat_svc

    return chat_svc.update_message(
        bot,
        mid,
        row["content"] or "",
        home=home,
        meta=meta,
    )
