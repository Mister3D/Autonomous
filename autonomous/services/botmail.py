"""Inter-bot messaging — Tell / Ask @bot, queue, reply relaunch."""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import settings as settings_svc
from autonomous.services.errors import AutonomousError, Forbidden, NotFound, ValidationError

log = logging.getLogger("autonomous.botmail")

# Instructions stay English. The mail body and the reply to the user must not.
_LANG_RULE = (
    "LANGUAGE: write the peer message (the tool content) and your reply to "
    "the user entirely in the language of this conversation — the language "
    "the user is writing in. One language only. Do not mix French and English. "
    "Do not switch to English because these instructions are in English. "
    "Tool results may be English; do not paste them. Keep names unchanged."
)
_INBOUND_LANG_RULE = (
    "Answer in the same language as the message below. One language only. "
    "Do not mix languages. Do not switch to English because this note is in English."
)

# English primary; French Dit/Demande kept as composer aliases.
_TELL_RE = re.compile(
    r"^\s*(?:"
    r"tell|"
    r"dis|dit|dites)\s+(?:à\s+)?@([a-zA-Z0-9_-]+)\s*[:\-]?\s*(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ASK_RE = re.compile(
    r"^\s*(?:"
    r"ask|"
    r"demande|demandez)\s+(?:à\s+)?@([a-zA-Z0-9_-]+)\s*[:\-]?\s*(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

# Legacy FR received preamble (UI banner replaced it).
_RECEIVED_PREAMBLE_RE = re.compile(
    r"^@[a-zA-Z0-9_-]+\s+m['\u2019]a envoyé un message\s*:\s*",
    re.IGNORECASE,
)

# Mentions in assistant text (same charset as composer / bots.name).
_MENTION_RE = re.compile(r"@([a-zA-Z0-9_-]+)")

# Assistant claims it will wait for / forward a peer reply → must have been Ask.
_AWAIT_REPLY_RE = re.compile(
    r"(?i)("
    r"d[eè]s\s+que\s+je\s+(re[cç]ois|aurai)|"
    r"je\s+te\s+(?:fais|ferai)\s+suivre|"
    r"je\s+t['\u2019]informe|"
    r"je\s+reviens\s+(vers\s+toi|avec)|"
    r"en\s+attendant\s+(sa|leur|la)\s+r[eé]ponse|"
    r"j['\u2019]attends\s+(sa|leur|la|une)\s+r[eé]ponse|"
    r"waiting\s+for\s+(a\s+)?(reply|answer|response)|"
    r"as\s+soon\s+as\s+i\s+(get|hear|receive)"
    r")"
)

# 3rd-person verb → tutoiement for a self-contained peer message.
_TU_VERB = {
    "fait": "fais",
    "font": "fais",
    "a": "as",
    "ont": "as",
    "est": "es",
    "sont": "es",
    "peut": "peux",
    "peuvent": "peux",
    "veut": "veux",
    "veulent": "veux",
    "doit": "dois",
    "doivent": "dois",
    "va": "vas",
    "vont": "vas",
    "sait": "sais",
    "savent": "sais",
    "aime": "aimes",
    "aiment": "aimes",
    "habite": "habites",
    "habitent": "habites",
    "travaille": "travailles",
    "travaillent": "travailles",
    "pense": "penses",
    "pensent": "penses",
    "prefère": "préfères",
    "préfère": "préfères",
    "preferent": "préfères",
    "préfèrent": "préfères",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock_for(bot: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(bot)
        if lock is None:
            lock = threading.Lock()
            _locks[bot] = lock
        return lock


def list_peers(manager: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    """Other bots visible to a manager for orchestration."""
    me = bots_svc.get_bot(manager, home=home)
    if not me.get("is_manager"):
        raise Forbidden(
            "Only a Manager bot can list other bots.",
            code="manager_required",
        )
    out: list[dict[str, Any]] = []
    for b in bots_svc.list_bots(home=home):
        if b["name"] == me["name"]:
            continue
        out.append(
            {
                "name": b["name"],
                "label": b.get("label") or b["name"],
                "status": b.get("status") or "idle",
                "capability": b.get("capability") or "none",
                "is_manager": bool(b.get("is_manager")),
            }
        )
    return out


def format_delegate_content(
    *,
    manager_slug: str,
    task: str,
    expect_reply: str | None = None,
) -> str:
    """Build a one-way task message that asks the peer to relaunch the manager."""
    body = (task or "").strip()
    if not body:
        raise ValidationError("Empty task", code="botmail_empty")
    me = (manager_slug or "").strip().lstrip("@")
    expect = (expect_reply or "").strip() or (
        "a short summary of the result (success or failure)"
    )
    return (
        f"{body}\n\n"
        f"—\n"
        f"Manager @{me} instructions: I am NOT waiting. "
        f"When you are done (success or failure), relaunch me with "
        f"« Tell @{me} … » containing {expect}. "
        f"Do not wait for further instructions from me on this thread."
    )


def parse_route(text: str) -> dict[str, str] | None:
    """Parse composer text into {mode, target, body} or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = _ASK_RE.match(raw)
    if m:
        return {"mode": "ask", "target": m.group(1), "body": m.group(2).strip()}
    m = _TELL_RE.match(raw)
    if m:
        return {"mode": "tell", "target": m.group(1), "body": m.group(2).strip()}
    return None


def reformulate_peer_message(
    body: str,
    *,
    mode: str = "ask",
    continuation: bool = False,
) -> str:
    """Rewrite a Tell/Ask fragment into a self-contained peer message.

    Composer text after ``@name`` is often a relative clause meant for the human
    ("if she rides horses"). The peer has no that context — address them as
    ``you`` (EN) / ``tu`` (FR alias) unless ``continuation``.
    """
    text = (body or "").strip()
    if not text or continuation:
        return text

    # EN: "if she/he …" / "if you …"
    m = re.match(r"(?i)^if\s+(she|he)\s+(.+)$", text)
    if m:
        return _en_address_peer(m.group(2).strip(), mode=mode)

    m = re.match(r"(?i)^if\s+you\s+(.+)$", text)
    if m:
        rest = m.group(1).strip()
        if mode == "ask":
            return _ensure_question(f"Do you {rest}")
        return _cap_first(f"You {rest}")

    m = re.match(r"(?i)^that\s+(she|he)\s+(.+)$", text)
    if m:
        return _en_address_peer(m.group(2).strip(), mode="tell")

    m = re.match(r"(?i)^(she|he)\s+(.+)$", text)
    if m:
        return _en_address_peer(m.group(2).strip(), mode=mode)

    # FR aliases (composer still accepts Dit/Demande).
    m = re.match(r"(?i)^si\s+(elle|il)\s+(.+)$", text)
    if m:
        rest = _tu_ify_clause(m.group(2).strip())
        if mode == "ask":
            return _ensure_question(f"Est-ce que tu {rest}")
        return _cap_first(f"Tu {rest}")

    m = re.match(r"(?i)^si\s+tu\s+(.+)$", text)
    if m:
        rest = m.group(1).strip()
        if mode == "ask":
            return _ensure_question(f"Est-ce que tu {rest}")
        return _cap_first(f"Tu {rest}")

    # Apostrophe required so "quelle" is not eaten as qu+elle.
    m = re.match(r"(?i)^qu['\u2019](elle|il)\s+(.+)$", text)
    if m:
        rest = _tu_ify_clause(m.group(2).strip())
        return _cap_first(f"Tu {rest}")

    m = re.match(r"(?i)^(elle|il)\s+(.+)$", text)
    if m:
        rest = _tu_ify_clause(m.group(2).strip())
        if mode == "ask":
            return _ensure_question(f"Est-ce que tu {rest}")
        return _cap_first(f"Tu {rest}")

    if mode == "ask" and "?" not in text:
        if re.match(
            r"(?i)^(when|why|how|where|how\s+many|what|which|"
            r"quand|pourquoi|comment|où|combien|quel|quelle|quels|quelles)\b",
            text,
        ):
            return _ensure_question(text)
        if not re.match(
            r"(?i)^(do\s+you|are\s+you|can\s+you|could\s+you|would\s+you|"
            r"est-ce|peux-tu|pouvez-vous|puis-je|tu\b|vous\b|you\b)",
            text,
        ):
            return _ensure_question(f"Can you tell me: {text}")

    return text


def _en_address_peer(clause: str, *, mode: str) -> str:
    """Address a 3rd-person EN clause to the peer as you."""
    parts = (clause or "").strip().split(None, 1)
    if not parts:
        return clause
    first = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    if first in ("is", "are", "was", "were"):
        be = {"is": "are", "are": "are", "was": "were", "were": "were"}[first]
        body = f"{be} {rest}".strip() if rest else be
        if mode == "ask":
            return _ensure_question(f"Are you {rest}" if rest else "Are you")
        return _cap_first(f"You {body}")
    if mode == "ask":
        return _ensure_question(f"Do you {clause}".strip())
    return _cap_first(f"You {clause}".strip())


def _tu_ify_clause(clause: str) -> str:
    """Map the start of a FR 3rd-person clause to tutoiement (fait → fais…)."""
    parts = (clause or "").strip().split(None, 1)
    if not parts:
        return clause
    first = parts[0]
    key = first.lower()
    mapped = _TU_VERB.get(key)
    if not mapped:
        return clause
    rest = parts[1] if len(parts) > 1 else ""
    return f"{mapped} {rest}".strip() if rest else mapped


def _ensure_question(text: str) -> str:
    t = (text or "").strip().rstrip("?.! ")
    if not t:
        return text
    return t + " ?"


def _cap_first(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    return t[0].upper() + t[1:]


def resolve_bot(ref: str, *, home: Path | None = None, exclude: str | None = None) -> str:
    """Resolve @name or label to a bot name (case-insensitive)."""
    needle = (ref or "").strip().lstrip("@")
    if not needle:
        raise ValidationError("Missing recipient", code="botmail_target")
    bots = bots_svc.list_bots(home=home)
    lower = needle.lower()
    for b in bots:
        if b["name"].lower() == lower:
            name = b["name"]
            break
    else:
        for b in bots:
            if (b.get("label") or "").strip().lower() == lower:
                name = b["name"]
                break
        else:
            raise NotFound(f"Bot @{needle} not found", code="botmail_unknown")
    if exclude and name == exclude:
        raise ValidationError(
            "A bot cannot message itself",
            code="botmail_self",
        )
    return name


def maybe_route_from_composer(
    bot: str,
    content: str,
    *,
    message_id: str,
    home: Path | None = None,
) -> dict[str, Any] | None:
    """Annotate Tell/Ask lines; the local agent must author the peer message.

    Returns:
      None — not a Tell/Ask line (caller continues normally).
      ``{"skip_agent": True}`` — unknown target / error (caller must not start_run).
      ``{"skip_agent": False, "agent_prompt": str, "mode", "to_bot"}`` — mark
      route_intent and start the local agent with the enriched prompt (no
      automatic tell/ask; the agent calls the mail tools).
    """
    route = parse_route(content)
    if not route:
        return None
    try:
        target = resolve_bot(route["target"], home=home, exclude=bot)
    except AutonomousError as exc:
        chat_svc.create_message(
            bot,
            f"⚠️ {exc.message}",
            role="system",
            meta={"kind": "botmail", "mail_kind": "error"},
            home=home,
        )
        _patch_message_meta(
            bot,
            message_id,
            {
                "kind": "botmail",
                "mail_kind": "route_error",
                "error": exc.message,
            },
            home=home,
        )
        return {"skip_agent": True}

    raw_body = route["body"]
    mode = route["mode"]
    tool = "bot_ask" if mode == "ask" else "bot_tell"
    mode_label = (
        "a question (Ask)" if mode == "ask" else "a one-way message (Tell)"
    )
    agent_prompt = (
        f"[Inter-bot — explicit instruction]\n"
        f"The user wants you to send {mode_label} to @{target}.\n\n"
        f"User text (do NOT forward it verbatim to the peer):\n"
        f"« {content.strip()} »\n\n"
        f"You MUST:\n"
        f"1. Write a self-contained, coherent message for @{target} "
        f"(they have NOT read this chat): objective, useful facts from this "
        f"thread, constraints, expected result. Address them as « you » / « tu ». "
        f"Never forward a relative clause about a third person "
        f"(structure only — keep the conversation language: "
        f"« if she rides horses » → « Do you ride horses? », "
        f"« si elle fait du poney » → « Est-ce que tu fais du poney ? »).\n"
        f"2. Call {tool}(to=\"{target}\", content=<your authored message>).\n"
        f"3. Briefly confirm transmission to the user "
        f"(this is NOT the end of the task). If they asked you to bring the "
        f"reply back here, prefer bot_ask (or ensure follow-up).\n"
        f"Do not merely cite @{target}.\n"
        f"{_LANG_RULE}"
    )
    _patch_message_meta(
        bot,
        message_id,
        {
            "kind": "botmail",
            "mail_kind": "route_intent",
            "mode": mode,
            "to_bot": target,
            "link_bot": target,
            "body_raw": raw_body,
            "agent_prompt": agent_prompt,
        },
        home=home,
    )
    return {
        "skip_agent": False,
        "agent_prompt": agent_prompt,
        "mode": mode,
        "to_bot": target,
    }


def _patch_message_meta(
    bot: str,
    message_id: str,
    meta: dict[str, Any],
    *,
    home: Path | None = None,
) -> None:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT content, meta_json FROM messages WHERE id = ? AND bot = ?",
            (message_id, bot),
        ).fetchone()
        if not row:
            return
        prev = json.loads(row["meta_json"] or "{}")
        prev.update(meta)
        conn.execute(
            "UPDATE messages SET meta_json = ? WHERE id = ? AND bot = ?",
            (json.dumps(prev), message_id, bot),
        )
    # Refresh UI via update (content unchanged)
    chat_svc.update_message(bot, message_id, row["content"], home=home, meta=prev)


def stamp_outgoing_replies(
    bot: str,
    messages: list[dict[str, Any]],
    *,
    home: Path | None = None,
) -> None:
    """Mark assistant bubbles that were already mailed as an ask reply.

    Older replies have no ``direction`` meta. The inbox row points at them
    via ``link_message_id``.
    """
    pending = [
        m
        for m in messages
        if m.get("role") == "assistant"
        and (m.get("meta") or {}).get("direction") != "sent"
        and (m.get("meta") or {}).get("mail_kind") != "outgoing"
    ]
    if not pending:
        return
    wanted = {m["id"] for m in pending if m.get("id")}
    if not wanted:
        return
    try:
        bot_id = bots_svc.bot_uuid(bot, home=home)
    except AutonomousError:
        return
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT bot, meta_json FROM bot_inbox
            WHERE from_bot = ? AND kind = 'reply'
            """,
            (bot_id,),
        ).fetchall()
    targets: dict[str, str] = {}
    for row in rows:
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except json.JSONDecodeError:
            continue
        mid = meta.get("link_message_id")
        if mid in wanted:
            targets[mid] = _slug_for_id(row["bot"], home=home) or ""
    for msg in pending:
        if msg["id"] not in targets:
            continue
        extra = {
            "kind": "botmail",
            "mail_kind": "outgoing",
            "direction": "sent",
            "to_bot": targets[msg["id"]],
            "link_bot": targets[msg["id"]],
        }
        merged = dict(msg.get("meta") or {})
        merged.update(extra)
        msg["meta"] = merged
        _patch_message_meta(bot, msg["id"], extra, home=home)


def strip_received_preamble(
    bot: str,
    messages: list[dict[str, Any]],
    *,
    home: Path | None = None,
) -> None:
    """Drop legacy « @x m'a envoyé un message : » from received cards.

    The direction line already names the sender. Rewrites stored bubbles once.
    """
    for msg in messages:
        if msg.get("role") != "system":
            continue
        meta = msg.get("meta") or {}
        if meta.get("kind") != "botmail":
            continue
        if meta.get("mail_kind") not in ("tell", "ask", "ask_answered"):
            continue
        content = msg.get("content") or ""
        body = _RECEIVED_PREAMBLE_RE.sub("", content, count=1).strip()
        if not body or body == content:
            continue
        msg["content"] = body
        chat_svc.update_message(bot, msg["id"], body, home=home, meta=dict(meta))


def _resolve_origin_message_id(
    from_bot: str,
    *,
    origin_message_id: str | None,
    home: Path | None,
) -> str | None:
    """Prefer explicit id; else latest composer Dit/Demande route_intent bubble."""
    if origin_message_id:
        return origin_message_id
    for msg in reversed(chat_svc.list_messages(from_bot, limit=30, home=home)):
        if msg.get("role") != "user":
            continue
        meta = dict(msg.get("meta") or {})
        if meta.get("mail_kind") == "route_intent" and msg.get("id"):
            return str(msg["id"])
        # Stop at the first real user turn that is not route_intent.
        if not meta.get("hidden_prompt") and meta.get("kind") != "botmail":
            break
    return None


def _record_outgoing(
    from_bot: str,
    to_bot: str,
    content: str,
    *,
    mode: str,
    home: Path | None,
    ask_id: str | None = None,
    origin_message_id: str | None = None,
) -> str | None:
    """Visible « Sent to @peer » card on the sender (peer-facing body)."""
    body = (content or "").strip()
    if not body:
        return None
    meta: dict[str, Any] = {
        "kind": "botmail",
        "mail_kind": "outgoing",
        "direction": "sent",
        "mode": mode,
        "to_bot": to_bot,
        "link_bot": to_bot,
        "body": body,
    }
    if ask_id:
        meta["ask_id"] = ask_id
    if origin_message_id:
        meta["origin_message_id"] = origin_message_id
    msg = chat_svc.create_message(
        from_bot,
        body,
        role="system",
        meta=meta,
        home=home,
    )
    return str(msg.get("id") or "") or None


def tell(
    from_bot: str,
    to_bot: str,
    content: str,
    *,
    home: Path | None = None,
    origin: str = "api",
    origin_message_id: str | None = None,
) -> dict[str, Any]:
    to_bot = resolve_bot(to_bot, home=home, exclude=from_bot)
    content = (content or "").strip()
    if not content:
        raise ValidationError("Empty message", code="botmail_empty")
    origin_message_id = _resolve_origin_message_id(
        from_bot, origin_message_id=origin_message_id, home=home
    )
    outgoing_id = _record_outgoing(
        from_bot,
        to_bot,
        content,
        mode="tell",
        home=home,
        origin_message_id=origin_message_id,
    )
    meta: dict[str, Any] = {"origin": origin}
    if origin_message_id:
        meta["origin_message_id"] = origin_message_id
    if outgoing_id:
        meta["outgoing_message_id"] = outgoing_id
    return _enqueue(
        to_bot,
        from_bot=from_bot,
        kind="tell",
        content=content,
        correlation_id=None,
        home=home,
        meta=meta,
    )


def ask(
    from_bot: str,
    to_bot: str,
    content: str,
    *,
    home: Path | None = None,
    origin: str = "api",
    origin_message_id: str | None = None,
) -> dict[str, Any]:
    to_bot = resolve_bot(to_bot, home=home, exclude=from_bot)
    content = (content or "").strip()
    if not content:
        raise ValidationError("Empty question", code="botmail_empty")
    ask_id = str(uuid.uuid4())
    now = _now()
    origin_message_id = _resolve_origin_message_id(
        from_bot, origin_message_id=origin_message_id, home=home
    )
    outgoing_id = _record_outgoing(
        from_bot,
        to_bot,
        content,
        mode="ask",
        home=home,
        ask_id=ask_id,
        origin_message_id=origin_message_id,
    )
    meta: dict[str, Any] = {"origin": origin}
    if origin_message_id:
        meta["origin_message_id"] = origin_message_id
    if outgoing_id:
        meta["outgoing_message_id"] = outgoing_id
    inbox = _enqueue(
        to_bot,
        from_bot=from_bot,
        kind="ask",
        content=content,
        correlation_id=ask_id,
        home=home,
        meta=meta,
        defer_deliver=True,
    )
    from_id = bots_svc.bot_uuid(from_bot, home=home)
    to_id = bots_svc.bot_uuid(to_bot, home=home)
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO bot_asks(
              id, from_bot, to_bot, question, state, answer,
              inbox_id, created_at, answered_at
            ) VALUES (?, ?, ?, ?, 'open', NULL, ?, ?, NULL)
            """,
            (ask_id, from_id, to_id, content, inbox["id"], now),
        )
    # Deliver after ask row exists so meta can reference it.
    _try_deliver_inbox_item(inbox["id"], home=home)
    return get_ask(ask_id, home=home)


def get_ask(ask_id: str, *, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM bot_asks WHERE id = ?", (ask_id,)
        ).fetchone()
    if not row:
        raise NotFound(f"Ask {ask_id} not found", code="botmail_ask_missing")
    ask_row = _decode_ask(row, home=home)
    # Pi tool poll: pause asker's runtime while the peer answers.
    try:
        from_bot = ask_row["from_bot"]
        st = (bots_svc.get_bot(from_bot, home=home).get("status") or "idle")
        if ask_row["state"] == "open" and st == "busy":
            bots_svc.patch_bot(from_bot, {"status": "waiting"}, home=home)
        elif ask_row["state"] == "answered" and st == "waiting":
            bots_svc.patch_bot(from_bot, {"status": "busy"}, home=home)
    except Exception:
        log.exception("botmail asker status sync failed for %s", ask_id)
    return ask_row


def list_open_asks_from(from_bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    from_id = bots_svc.bot_uuid(from_bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM bot_asks
            WHERE from_bot = ? AND state = 'open'
            ORDER BY created_at ASC
            """,
            (from_id,),
        ).fetchall()
    return [_decode_ask(r, home=home) for r in rows]


def has_open_ask_from(from_bot: str, *, home: Path | None = None) -> bool:
    from_id = bots_svc.bot_uuid(from_bot, home=home)
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT 1 FROM bot_asks WHERE from_bot = ? AND state = 'open' LIMIT 1",
            (from_id,),
        ).fetchone()
    return bool(row)


def on_run_finished(
    bot: str,
    *,
    assistant_content: str = "",
    mail_sent: list[dict[str, Any]] | None = None,
    home: Path | None = None,
) -> None:
    """Called when a bot's agent run settles to idle — complete ask + drain queue.

    ``mail_sent``: successful ``bot_tell`` / ``bot_ask`` / ``bot_delegate`` calls
    during this run (``{tool, to}``). Used by the invisible post-response net so
    we don't re-mail a peer the agent already contacted.
    """
    reply_inbox_id: str | None = None
    with _lock_for(bot):
        try:
            reply_inbox_id = _complete_ask_if_needed(
                bot, assistant_content or "", home=home
            )
        except Exception:
            log.exception("botmail complete_ask failed for %s", bot)
        try:
            _drain_one(bot, home=home)
        except Exception:
            log.exception("botmail drain failed for %s", bot)
    # Deliver the asker's reply outside this bot's lock (avoid A↔B deadlock).
    if reply_inbox_id:
        try:
            _try_deliver_inbox_item(reply_inbox_id, home=home)
        except Exception:
            log.exception("botmail reply deliver failed for inbox %s", reply_inbox_id)
    # Invisible net: @mention without a mail tool → deterministic Tell/Ask.
    # Skip when this run is answering inbound mail (ask reply / tell answer).
    if reply_inbox_id is None and not _run_looks_mail_triggered(
        bot, home=home
    ):
        try:
            maybe_rescue_mentions(
                bot,
                assistant_content or "",
                mail_sent or [],
                home=home,
            )
        except Exception:
            log.exception("botmail rescue_mentions failed for %s", bot)
    # Tell used but asker promised a reply → mirror our answer back.
    try:
        maybe_relay_orphaned_tell_reply(
            bot, assistant_content or "", home=home
        )
    except Exception:
        log.exception("botmail orphan tell relay failed for %s", bot)


def _decode_ask(row, *, home: Path | None = None) -> dict[str, Any]:
    from_id = row["from_bot"]
    to_id = row["to_bot"]
    return {
        "id": row["id"],
        "from_bot_id": from_id,
        "to_bot_id": to_id,
        "from_bot": _slug_for_id(from_id, home=home) or from_id,
        "to_bot": _slug_for_id(to_id, home=home) or to_id,
        "question": row["question"],
        "state": row["state"],
        "answer": row["answer"],
        "inbox_id": row["inbox_id"],
        "created_at": row["created_at"],
        "answered_at": row["answered_at"],
    }


def _decode_inbox(row, *, home: Path | None = None) -> dict[str, Any]:
    bot_id = row["bot"]
    from_id = row["from_bot"]
    meta_raw = row["meta_json"] if "meta_json" in row.keys() else row.get("meta_json")
    if isinstance(row, dict):
        meta_raw = row.get("meta_json", "{}")
        meta = row.get("meta") if "meta" in row and row.get("meta") is not None else None
        if meta is None:
            meta = json.loads(meta_raw or "{}")
    else:
        meta = json.loads(row["meta_json"] or "{}")
    return {
        "id": row["id"],
        "bot_id": bot_id,
        "from_bot_id": from_id,
        "bot": _slug_for_id(bot_id, home=home) or bot_id,
        "from_bot": _slug_for_id(from_id, home=home) or ("?" if from_id else None),
        "kind": row["kind"],
        "content": row["content"],
        "correlation_id": row["correlation_id"],
        "state": row["state"],
        "meta": meta,
        "created_at": row["created_at"],
        "delivered_at": row["delivered_at"],
    }


def purge_for_bot(name_or_id: str, *, home: Path | None = None) -> dict[str, int]:
    """Drop inbox/asks tied to a bot about to be deleted (queued mail included).

    Rows are keyed by ``bots.id`` (UUID), not the reusable slug.
    """
    bid = _as_bot_id(name_or_id, home=home)
    if not bid:
        return {"inbox": 0, "asks": 0}
    with get_db(home) as conn:
        inbox = conn.execute(
            "DELETE FROM bot_inbox WHERE bot = ? OR from_bot = ?",
            (bid, bid),
        ).rowcount
        asks = conn.execute(
            "DELETE FROM bot_asks WHERE from_bot = ? OR to_bot = ?",
            (bid, bid),
        ).rowcount
    return {"inbox": inbox, "asks": asks}


def _as_bot_id(name_or_id: str | None, *, home: Path | None) -> str | None:
    ref = (name_or_id or "").strip()
    if not ref or ref == "?":
        return None
    try:
        return bots_svc.bot_uuid(ref, home=home)
    except NotFound:
        # Already deleted: accept a raw UUID so purge/delete still cleans rows.
        if bots_svc.looks_like_bot_id(ref):
            return ref
        return None


def _slug_for_id(bot_id: str | None, *, home: Path | None) -> str | None:
    if not bot_id:
        return None
    try:
        return bots_svc.get_bot_by_id(bot_id, home=home)["name"]
    except NotFound:
        return None


def _bot_id_exists(bot_id: str | None, *, home: Path | None) -> bool:
    if not bot_id or bot_id == "?":
        return False
    try:
        bots_svc.get_bot_by_id(bot_id, home=home)
        return True
    except NotFound:
        return False
    except Exception:
        return False


def _enqueue(
    bot: str,
    *,
    from_bot: str | None,
    kind: str,
    content: str,
    correlation_id: str | None,
    home: Path | None,
    meta: dict[str, Any] | None = None,
    defer_deliver: bool = False,
) -> dict[str, Any]:
    """Enqueue mail. ``bot`` / ``from_bot`` may be slug or UUID; stored as UUID."""
    item_id = str(uuid.uuid4())
    now = _now()
    meta = dict(meta or {})
    bot_id = bots_svc.bot_uuid(bot, home=home)
    from_id = bots_svc.bot_uuid(from_bot, home=home) if from_bot else None
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO bot_inbox(
              id, bot, from_bot, kind, content, correlation_id,
              state, meta_json, created_at, delivered_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, NULL)
            """,
            (
                item_id,
                bot_id,
                from_id,
                kind,
                content,
                correlation_id,
                json.dumps(meta),
                now,
            ),
        )
    item = _decode_inbox(
        {
            "id": item_id,
            "bot": bot_id,
            "from_bot": from_id,
            "kind": kind,
            "content": content,
            "correlation_id": correlation_id,
            "state": "queued",
            "meta_json": json.dumps(meta),
            "created_at": now,
            "delivered_at": None,
        },
        home=home,
    )
    if not defer_deliver:
        _try_deliver_inbox_item(item_id, home=home)
    return item


def _try_deliver_inbox_item(item_id: str, *, home: Path | None) -> bool:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM bot_inbox WHERE id = ?", (item_id,)
        ).fetchone()
    if not row or row["state"] != "queued":
        return False
    item = _decode_inbox(row, home=home)
    bot = item["bot"]
    with _lock_for(bot):
        status = (bots_svc.get_bot(bot, home=home).get("status") or "idle")
        if status in ("busy", "waiting"):
            return False
        return _deliver_locked(item, home=home)


def _drain_one(bot: str, *, home: Path | None) -> bool:
    """Deliver the oldest valid queued item. Ghost senders are cancelled and skipped."""
    try:
        status = (bots_svc.get_bot(bot, home=home).get("status") or "idle")
        bot_id = bots_svc.bot_uuid(bot, home=home)
    except NotFound:
        return False
    if status in ("busy", "waiting"):
        return False
    while True:
        with get_db(home) as conn:
            row = conn.execute(
                """
                SELECT * FROM bot_inbox
                WHERE bot = ? AND state = 'queued'
                ORDER BY created_at ASC LIMIT 1
                """,
                (bot_id,),
            ).fetchone()
        if not row:
            return False
        item = _decode_inbox(row, home=home)
        from_id = item.get("from_bot_id")
        if from_id and not _bot_id_exists(from_id, home=home):
            log.warning(
                "botmail drain skip %s: sender id %s no longer exists",
                item["id"],
                from_id,
            )
            with get_db(home) as conn:
                conn.execute(
                    "UPDATE bot_inbox SET state = 'cancelled', delivered_at = ? "
                    "WHERE id = ? AND state = 'queued'",
                    (_now(), item["id"]),
                )
            continue
        return _deliver_locked(item, home=home)


def _deliver_locked(item: dict[str, Any], *, home: Path | None) -> bool:
    """Deliver one inbox item; caller holds bot lock (except via _try_deliver)."""
    bot = item["bot"]
    try:
        status = (bots_svc.get_bot(bot, home=home).get("status") or "idle")
    except NotFound:
        # Recipient deleted while queued — drop the item.
        with get_db(home) as conn:
            conn.execute(
                "UPDATE bot_inbox SET state = 'cancelled', delivered_at = ? "
                "WHERE id = ? AND state = 'queued'",
                (_now(), item["id"]),
            )
        return False
    if status in ("busy", "waiting"):
        return False

    from_bot = item.get("from_bot") or "?"
    from_id = item.get("from_bot_id")
    kind = item["kind"]
    body = item["content"]
    ask_id = item.get("correlation_id")

    # Ghost sender (deleted bot): never inject into a (re)created recipient.
    if from_id and not _bot_id_exists(from_id, home=home):
        log.warning(
            "botmail drop queued %s: sender id %s no longer exists",
            item["id"],
            from_id,
        )
        with get_db(home) as conn:
            conn.execute(
                "UPDATE bot_inbox SET state = 'cancelled', delivered_at = ? "
                "WHERE id = ? AND state = 'queued'",
                (_now(), item["id"]),
            )
        return False

    now = _now()
    with get_db(home) as conn:
        cur = conn.execute(
            """
            UPDATE bot_inbox
            SET state = 'delivered', delivered_at = ?
            WHERE id = ? AND state = 'queued'
            """,
            (now, item["id"]),
        )
        if cur.rowcount != 1:
            return False

    item_meta = dict(item.get("meta") or {})
    origin_message_id = item_meta.get("origin_message_id")
    outgoing_message_id = item_meta.get("outgoing_message_id")
    link_answer_id = item_meta.get("link_message_id")

    def _link_sender_cards(peer_msg_id: str, *, extra: dict[str, Any] | None = None) -> None:
        """Deep-link route_intent + outgoing card back to the received bubble."""
        if not from_bot or not peer_msg_id:
            return
        patch = {
            "peer_message_id": peer_msg_id,
            "link_bot": bot,
            "link_message_id": peer_msg_id,
        }
        if extra:
            patch.update(extra)
        if origin_message_id:
            _patch_message_meta(from_bot, origin_message_id, patch, home=home)
        if outgoing_message_id:
            _patch_message_meta(from_bot, outgoing_message_id, patch, home=home)

    if kind == "ask":
        visible = body
        msg = chat_svc.create_message(
            bot,
            visible,
            role="system",
            meta={
                "kind": "botmail",
                "mail_kind": "ask",
                "direction": "received",
                "from_bot": from_bot,
                "ask_id": ask_id,
                "body": body,
                "link_bot": from_bot,
                "link_message_id": outgoing_message_id or origin_message_id,
            },
            home=home,
        )
        _link_sender_cards(msg["id"], extra={"ask_id": ask_id})
        prompt = (
            f"@{from_bot} is asking you a question (inter-bot message). "
            f"You do NOT have @{from_bot}'s conversation thread — act only on "
            f"what follows, under your own instructions. Answer clearly in your "
            f"next text message (not only via tools) — your reply will be "
            f"forwarded to them.\n"
            f"{_INBOUND_LANG_RULE}\n\n"
            f"Question:\n{body}"
        )
        _start_agent(bot, prompt, home=home)
        return True

    if kind == "reply":
        answer = body
        visible = answer
        chat_svc.create_message(
            bot,
            visible,
            role="system",
            meta={
                "kind": "botmail",
                "mail_kind": "ask_answered",
                "direction": "received",
                "from_bot": from_bot,
                "ask_id": ask_id,
                "answer": answer,
                "link_bot": from_bot,
                "link_message_id": link_answer_id,
            },
            home=home,
        )
        prompt = (
            f"@{from_bot} replied (async Ask return):\n{answer}\n\n"
            "Continue with this information for the user if you promised to "
            "bring the result back here. Do not ask the same thing again. "
            "Tell the user in the language of your conversation with them "
            "(one language only; do not mix French and English)."
        )
        _start_agent(bot, prompt, home=home)
        return True

    # tell
    visible = body
    msg = chat_svc.create_message(
        bot,
        visible,
        role="system",
        meta={
            "kind": "botmail",
            "mail_kind": "tell",
            "direction": "received",
            "from_bot": from_bot,
            "body": body,
            "link_bot": from_bot,
            "link_message_id": outgoing_message_id or origin_message_id,
        },
        home=home,
    )
    _link_sender_cards(msg["id"])
    prompt = (
        f"@{from_bot} wrote to you (inter-bot, one-way). "
        f"You do NOT have @{from_bot}'s conversation thread — act only on "
        f"what follows, under your own instructions "
        f"(standing rules, memory, etc.).\n"
        f"{_INBOUND_LANG_RULE}\n\n"
        f"{body}"
    )
    _start_agent(bot, prompt, home=home)
    return True


def _start_agent(bot: str, prompt: str, *, home: Path | None) -> None:
    from autonomous.services import reactions as reactions_svc

    # Mail is not the user's bubble — don't react on a stale turn.
    reactions_svc.set_turn_message(bot, None)
    backend = str(settings_svc.get("agent_backend", home=home, default="pi") or "pi")
    if backend == "null":
        return
    from autonomous.services.agent import get_agent

    get_agent(backend, home=home).start_run(bot, prompt, home=home)


def maybe_rescue_mentions(
    bot: str,
    assistant_content: str,
    mail_sent: list[dict[str, Any]],
    *,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    """Post-response net — disabled.

    A bare ``@name`` (or an assistant claim without ``bot_tell``/``bot_ask``)
    must NOT invent a peer message from the user text. Only the local agent
    authors inter-bot mail via the tools. Kept as a no-op hook for
    ``on_run_finished`` compatibility.
    """
    del bot, assistant_content, mail_sent, home
    return []


def maybe_relay_orphaned_tell_reply(
    bot: str,
    assistant_content: str,
    *,
    home: Path | None = None,
) -> str | None:
    """If we answered a Tell and the asker promised to wait, mirror the answer.

    Covers the common LLM mix-up: ``bot_tell`` used while the assistant text
    says it will forward the peer's reply (should have been ``bot_ask``).
    Returns the reply inbox id when a relay was queued, else None.
    """
    answer = (assistant_content or "").strip()
    if not answer:
        return None
    delivered = _last_delivered_tell_inbox(bot, home=home)
    if not delivered:
        return None
    asker = (delivered.get("from_bot") or "").strip()
    if not asker or asker == bot:
        return None
    # Don't steal an in-flight real ask for this pair.
    if _has_open_ask_between(asker, bot, home=home):
        return None
    asker_assistant = _last_assistant_text(asker, home=home)
    if not asker_assistant or not _AWAIT_REPLY_RE.search(asker_assistant):
        return None
    # Asker's bubble should name us (slug or label).
    if not _text_mentions_bot(asker_assistant, bot, home=home):
        return None
    after = delivered.get("delivered_at") or delivered.get("created_at")
    if _has_relay_from_since(bot, asker, after, home=home):
        return None

    _, answer_msg_id = _last_assistant_after(bot, after, home=home)
    if answer_msg_id:
        _patch_message_meta(
            bot,
            answer_msg_id,
            {
                "kind": "botmail",
                "mail_kind": "outgoing",
                "direction": "sent",
                "to_bot": asker,
                "link_bot": asker,
                "origin": "orphan_tell_relay",
            },
            home=home,
        )
    item = _enqueue(
        asker,
        from_bot=bot,
        kind="reply",
        content=answer,
        correlation_id=None,
        home=home,
        meta={
            "origin": "orphan_tell_relay",
            "link_message_id": answer_msg_id,
        },
        defer_deliver=True,
    )
    try:
        _try_deliver_inbox_item(item["id"], home=home)
    except Exception:
        log.exception(
            "botmail orphan tell relay deliver failed for inbox %s",
            item["id"],
        )
    log.info(
        "botmail orphan tell relay %s → %s (inbox=%s)",
        bot,
        asker,
        item["id"],
    )
    return item["id"]


def _text_mentions_bot(
    text: str, bot: str, *, home: Path | None
) -> bool:
    needle = (bot or "").strip().lstrip("@").lower()
    if not needle:
        return False
    for match in _MENTION_RE.finditer(text or ""):
        raw = match.group(1)
        try:
            name = resolve_bot(raw, home=home)
        except AutonomousError:
            if raw.lower() == needle:
                return True
            continue
        if name.lower() == needle:
            return True
    # Label without @ still counts if resolve would match — keep strict on @.
    return False


def _last_assistant_text(bot: str, *, home: Path | None) -> str:
    text, _ = _last_assistant_after(bot, None, home=home)
    return text


def _last_delivered_tell_inbox(
    bot: str, *, home: Path | None
) -> dict[str, Any] | None:
    bot_id = bots_svc.bot_uuid(bot, home=home)
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT * FROM bot_inbox
            WHERE bot = ? AND kind = 'tell' AND state = 'delivered'
            ORDER BY COALESCE(delivered_at, created_at) DESC
            LIMIT 1
            """,
            (bot_id,),
        ).fetchone()
    return _decode_inbox(row, home=home) if row else None


def _last_delivered_inbox(
    bot: str, *, home: Path | None
) -> dict[str, Any] | None:
    bot_id = bots_svc.bot_uuid(bot, home=home)
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT * FROM bot_inbox
            WHERE bot = ? AND state = 'delivered'
            ORDER BY COALESCE(delivered_at, created_at) DESC
            LIMIT 1
            """,
            (bot_id,),
        ).fetchone()
    return _decode_inbox(row, home=home) if row else None


def _run_looks_mail_triggered(bot: str, *, home: Path | None) -> bool:
    """True when this settle is answering inbound mail (no newer user bubble)."""
    delivered = _last_delivered_inbox(bot, home=home)
    if not delivered:
        return False
    after = delivered.get("delivered_at") or delivered.get("created_at") or ""
    for msg in reversed(chat_svc.list_messages(bot, limit=40, home=home)):
        created = msg.get("created_at") or ""
        if after and created < after:
            break
        if msg.get("role") != "user":
            continue
        meta = dict(msg.get("meta") or {})
        if meta.get("hidden_prompt") or meta.get("kind") == "botmail":
            continue
        return False
    return True


def _has_open_ask_between(
    from_bot: str, to_bot: str, *, home: Path | None
) -> bool:
    from_id = bots_svc.bot_uuid(from_bot, home=home)
    to_id = bots_svc.bot_uuid(to_bot, home=home)
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT 1 FROM bot_asks
            WHERE from_bot = ? AND to_bot = ? AND state = 'open'
            LIMIT 1
            """,
            (from_id, to_id),
        ).fetchone()
    return bool(row)


def _has_relay_from_since(
    from_bot: str,
    to_bot: str,
    after_iso: str | None,
    *,
    home: Path | None,
) -> bool:
    """Avoid double-relaying the same orphan tell answer."""
    for msg in reversed(chat_svc.list_messages(to_bot, limit=30, home=home)):
        created = msg.get("created_at") or ""
        if after_iso and created < after_iso:
            continue
        meta = dict(msg.get("meta") or {})
        if meta.get("kind") != "botmail":
            continue
        if meta.get("mail_kind") != "ask_answered":
            continue
        if (meta.get("from_bot") or "").lower() != from_bot.lower():
            continue
        return True
    return False


def _complete_ask_if_needed(
    bot: str,
    assistant_content: str,
    *,
    home: Path | None,
) -> str | None:
    """If this run answered a delivered ask, queue reply for asker. Returns inbox id."""
    delivered = _last_delivered_ask_inbox(bot, home=home)
    if not delivered:
        return None
    ask_id = delivered.get("correlation_id")
    if not ask_id:
        return None
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM bot_asks WHERE id = ? AND state = 'open'",
            (ask_id,),
        ).fetchone()
    if not row:
        return None

    after = delivered.get("delivered_at") or delivered.get("created_at")
    answer = (assistant_content or "").strip()
    answer_msg_id = None
    if not answer:
        answer, answer_msg_id = _last_assistant_after(bot, after, home=home)
    else:
        _, answer_msg_id = _last_assistant_after(bot, after, home=home)
    if not answer:
        log.warning("botmail ask %s answered with empty content on %s", ask_id, bot)
        return None

    asker = _slug_for_id(row["from_bot"], home=home) or ""
    if answer_msg_id:
        _patch_message_meta(
            bot,
            answer_msg_id,
            {
                "kind": "botmail",
                "mail_kind": "outgoing",
                "direction": "sent",
                "to_bot": asker,
                "ask_id": ask_id,
                "link_bot": asker,
            },
            home=home,
        )

    now = _now()
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE bot_asks
            SET state = 'answered', answer = ?, answered_at = ?
            WHERE id = ? AND state = 'open'
            """,
            (answer, now, ask_id),
        )
    from_bot = row["from_bot"]
    to_bot = row["to_bot"]
    item = _enqueue(
        from_bot,
        from_bot=to_bot,
        kind="reply",
        content=answer,
        correlation_id=ask_id,
        home=home,
        meta={
            "origin": "ask_reply",
            "link_message_id": answer_msg_id,
        },
        defer_deliver=True,
    )
    return item["id"]


def _last_delivered_ask_inbox(
    bot: str, *, home: Path | None
) -> dict[str, Any] | None:
    """Most recently delivered ask to this bot (this run's trigger)."""
    bot_id = bots_svc.bot_uuid(bot, home=home)
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT * FROM bot_inbox
            WHERE bot = ? AND kind = 'ask' AND state = 'delivered'
            ORDER BY COALESCE(delivered_at, created_at) DESC
            LIMIT 1
            """,
            (bot_id,),
        ).fetchone()
    return _decode_inbox(row, home=home) if row else None


def _last_assistant_after(
    bot: str, after_iso: str | None, *, home: Path | None
) -> tuple[str, str | None]:
    """Last non-empty assistant bubble after after_iso → (text, message_id)."""
    for msg in reversed(chat_svc.list_messages(bot, limit=40, home=home)):
        if msg.get("role") != "assistant":
            continue
        if after_iso and (msg.get("created_at") or "") < after_iso:
            continue
        text = (msg.get("content") or "").strip()
        if text:
            return text, msg.get("id")
    return "", None
