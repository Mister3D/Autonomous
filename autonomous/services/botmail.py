"""Inter-bot messaging — Dit / Demande à @bot, queue, reply relaunch."""

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

_TELL_RE = re.compile(
    r"^\s*(?:dis|dit|dites)\s+à\s+@([a-zA-Z0-9_-]+)\s*[:\-]?\s*(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ASK_RE = re.compile(
    r"^\s*(?:demande|demandez)\s+à\s+@([a-zA-Z0-9_-]+)\s*[:\-]?\s*(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

# Ancien préambule de bulle. Le bandeau « Reçu de @… » le remplace.
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

_ROUTE_PREFIX_RE = re.compile(
    r"^\s*(?:demande|demandez|dis|dit|dites)\s+à\s+@[a-zA-Z0-9_-]+\s*[:\-]?\s*",
    re.IGNORECASE,
)


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
            "Seul un bot Manager peut lister les autres bots.",
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
        raise ValidationError("Tâche vide", code="botmail_empty")
    me = (manager_slug or "").strip().lstrip("@")
    expect = (expect_reply or "").strip() or (
        "un résumé court du résultat (succès ou échec)"
    )
    return (
        f"{body}\n\n"
        f"—\n"
        f"Consignes Manager @{me} : je ne reste PAS en attente. "
        f"Quand tu as terminé (succès ou échec), relance-moi avec un message "
        f"« Dit à @{me} … » contenant {expect}. "
        f"N’attends pas d’autres instructions de ma part sur ce fil."
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


def resolve_bot(ref: str, *, home: Path | None = None, exclude: str | None = None) -> str:
    """Resolve @name or label to a bot name (case-insensitive)."""
    needle = (ref or "").strip().lstrip("@")
    if not needle:
        raise ValidationError("Destinataire manquant", code="botmail_target")
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
            raise NotFound(f"Bot @{needle} introuvable", code="botmail_unknown")
    if exclude and name == exclude:
        raise ValidationError(
            "Un bot ne peut pas s’écrire à lui-même",
            code="botmail_self",
        )
    return name


def maybe_route_from_composer(
    bot: str,
    content: str,
    *,
    message_id: str,
    home: Path | None = None,
) -> bool:
    """
    If the user message is Dit/Demande à @x, route it and skip local agent start.
    Returns True when handled (caller must not start_run on this bot).
    """
    route = parse_route(content)
    if not route:
        return False
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
        return True

    body = route["body"]
    mode = route["mode"]
    _patch_message_meta(
        bot,
        message_id,
        {
            "kind": "botmail",
            "mail_kind": mode,
            "to_bot": target,
        },
        home=home,
    )
    # Pas d’accusé « J’ai envoyé… » : seuls les messages reçus côté bots.
    # origin_message_id = bulle user (Dit/Demande) pour le deep-link retour.
    if mode == "ask":
        ask_row = ask(
            bot,
            target,
            body,
            home=home,
            origin="composer",
            origin_message_id=message_id,
        )
        _patch_message_meta(
            bot,
            message_id,
            {
                "ask_id": ask_row["id"],
                "to_bot": target,
                "link_bot": target,
                "body": body,
            },
            home=home,
        )
    else:
        tell(
            bot,
            target,
            body,
            home=home,
            origin="composer",
            origin_message_id=message_id,
        )
        _patch_message_meta(
            bot,
            message_id,
            {
                "to_bot": target,
                "link_bot": target,
                "body": body,
            },
            home=home,
        )
    return True


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
    """Drop « @x m'a envoyé un message : » from received cards.

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
        raise ValidationError("Message vide", code="botmail_empty")
    meta: dict[str, Any] = {"origin": origin}
    if origin_message_id:
        meta["origin_message_id"] = origin_message_id
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
        raise ValidationError("Question vide", code="botmail_empty")
    ask_id = str(uuid.uuid4())
    now = _now()
    meta: dict[str, Any] = {"origin": origin}
    if origin_message_id:
        meta["origin_message_id"] = origin_message_id
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
        raise NotFound(f"Ask {ask_id} introuvable", code="botmail_ask_missing")
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

    origin_message_id = (item.get("meta") or {}).get("origin_message_id")
    link_answer_id = (item.get("meta") or {}).get("link_message_id")

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
                "link_message_id": origin_message_id,
            },
            home=home,
        )
        if origin_message_id and from_bot:
            _patch_message_meta(
                from_bot,
                origin_message_id,
                {
                    "peer_message_id": msg["id"],
                    "link_bot": bot,
                    "link_message_id": msg["id"],
                    "ask_id": ask_id,
                },
                home=home,
            )
        prompt = (
            f"@{from_bot} te pose une question. Réponds clairement dans ton prochain "
            f"message texte (pas seulement via des outils) — ta réponse lui sera renvoyée.\n\n"
            f"Question : {body}"
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
            f"@{from_bot} t’a répondu :\n{answer}\n\n"
            "Continue avec cette information (ne redemande pas la même chose)."
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
            "link_message_id": origin_message_id,
        },
        home=home,
    )
    if origin_message_id and from_bot:
        _patch_message_meta(
            from_bot,
            origin_message_id,
            {
                "peer_message_id": msg["id"],
                "link_bot": bot,
                "link_message_id": msg["id"],
            },
            home=home,
        )
    prompt = f"@{from_bot} t’a écrit :\n{body}"
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
    """Invisible post-response net: @peer in assistant text but no mail tool → send.

    Deterministic (no second LLM turn, nothing appended to the thread about the
    rescue). Mode is Ask when the assistant awaits a reply / user intent is a
    question; otherwise Tell. Returns the list of rescues performed.
    """
    text = (assistant_content or "").strip()
    if not text or "@" not in text:
        return []

    mailed = {
        str(item.get("to") or "").strip().lstrip("@").lower()
        for item in (mail_sent or [])
        if str(item.get("to") or "").strip()
    }
    targets = _mentioned_bots(text, home=home, exclude=bot)
    if not targets:
        return []

    user_text = _last_user_text(bot, home=home)
    mode = _infer_rescue_mode(text, user_text)
    rescued: list[dict[str, Any]] = []
    for target in targets:
        if target.lower() in mailed:
            continue
        body = _rescue_body(target, text, user_text, home=home)
        if not body:
            continue
        try:
            if mode == "ask":
                row = ask(
                    bot, target, body, home=home, origin="rescue"
                )
            else:
                row = tell(
                    bot, target, body, home=home, origin="rescue"
                )
            rescued.append(
                {"to": target, "mode": mode, "id": row.get("id")}
            )
            log.info(
                "botmail rescue %s %s → @%s (origin=rescue)",
                mode,
                bot,
                target,
            )
        except AutonomousError as exc:
            log.warning(
                "botmail rescue skipped %s → @%s: %s",
                bot,
                target,
                exc.message,
            )
        except Exception:
            log.exception("botmail rescue failed %s → @%s", bot, target)
    return rescued


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


def _mentioned_bots(
    text: str, *, home: Path | None, exclude: str | None
) -> list[str]:
    """Unique bot slugs mentioned with @ in text (resolved; exclude self)."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _MENTION_RE.finditer(text or ""):
        raw = match.group(1)
        try:
            name = resolve_bot(raw, home=home, exclude=exclude)
        except AutonomousError:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(name)
    return found


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


def _infer_rescue_mode(assistant: str, user_text: str) -> str:
    if _AWAIT_REPLY_RE.search(assistant or ""):
        return "ask"
    route = parse_route(user_text or "")
    if route and route["mode"] == "ask":
        return "ask"
    if re.search(
        r"(?i)^\s*(?:demande|demandez|ask)\b", user_text or ""
    ):
        return "ask"
    if "?" in (user_text or "") or "?" in (assistant or ""):
        return "ask"
    return "tell"


def _rescue_body(
    target: str,
    assistant: str,
    user_text: str,
    *,
    home: Path | None,
) -> str:
    route = parse_route(user_text or "")
    if route:
        try:
            resolved = resolve_bot(route["target"], home=home)
        except AutonomousError:
            resolved = ""
        if resolved.lower() == target.lower() and route["body"].strip():
            return route["body"].strip()
    cleaned = _ROUTE_PREFIX_RE.sub("", user_text or "").strip()
    if cleaned:
        return cleaned
    body = _MENTION_RE.sub("", assistant or "").strip()
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:2000]


def _last_user_text(bot: str, *, home: Path | None) -> str:
    for msg in reversed(chat_svc.list_messages(bot, limit=40, home=home)):
        if msg.get("role") != "user":
            continue
        meta = dict(msg.get("meta") or {})
        if meta.get("hidden_prompt") or meta.get("kind") == "botmail":
            continue
        text = (msg.get("content") or "").strip()
        if text:
            return text
    return ""


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
