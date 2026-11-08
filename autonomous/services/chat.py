"""Chat / messages service — wires Pi agent for assistant replies."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services import bots as bots_svc
from autonomous.services import settings as settings_svc
from autonomous.services.errors import AutonomousError
from autonomous.services.events import BUS
from autonomous.services.pi_rpc import MANAGER, new_session_id

log = logging.getLogger("autonomous.chat")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "bot": row["bot"],
        "conversation_id": row["conversation_id"],
        "role": row["role"],
        "content": row["content"],
        "attachments": json.loads(row["attachments_json"] or "[]"),
        "meta": json.loads(row["meta_json"] or "{}"),
        "created_at": row["created_at"],
    }


def list_messages(
    bot: str,
    *,
    before: str | None = None,
    limit: int = 50,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    bots_svc.get_bot(bot, home=home)
    limit = max(1, min(limit, 200))
    with get_db(home) as conn:
        if before:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE bot = ? AND conversation_id = 'main' AND created_at < ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (bot, before, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE bot = ? AND conversation_id = 'main'
                ORDER BY created_at DESC LIMIT ?
                """,
                (bot, limit),
            ).fetchall()
    messages = [_decode(r) for r in reversed(rows)]
    try:
        from autonomous.services import botmail as botmail_svc

        botmail_svc.strip_received_preamble(bot, messages, home=home)
        botmail_svc.stamp_outgoing_replies(bot, messages, home=home)
    except Exception:
        log.exception("botmail outgoing stamp failed for %s", bot)
    return messages


def bot_run_blocked(bot: str, *, home: Path | None = None) -> bool:
    """True when a new agent run must wait (busy, waiting for the user, desk creating)."""
    row = bots_svc.get_bot(bot, home=home)
    status = row.get("status") or "idle"
    if status in ("busy", "waiting"):
        return True
    desk = row.get("desk") if isinstance(row.get("desk"), dict) else None
    if desk and desk.get("state") == "creating":
        return True
    return False


def count_tools_since_last_user(bot: str, *, home: Path | None = None) -> int:
    """Tool cards since the last user / webhook / cron message (turn anchor).

    Desk/vault resume must NOT reset this — only a new ``role=user`` bubble does
    (composer, webhook, cron).
    """
    bots_svc.get_bot(bot, home=home)
    with get_db(home) as conn:
        anchor = conn.execute(
            """
            SELECT created_at FROM messages
            WHERE bot = ? AND conversation_id = 'main' AND role = 'user'
            ORDER BY created_at DESC LIMIT 1
            """,
            (bot,),
        ).fetchone()
        since = anchor["created_at"] if anchor else "1970-01-01T00:00:00+00:00"
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM messages
            WHERE bot = ? AND conversation_id = 'main' AND role = 'event'
              AND created_at > ?
              AND json_extract(meta_json, '$.kind') = 'tool'
            """,
            (bot, since),
        ).fetchone()
    return int(row["c"] if row else 0)


def send_message(
    bot: str,
    content: str,
    *,
    attachments: list[str] | None = None,
    role: str = "user",
    home: Path | None = None,
    trigger_agent: bool = True,
    prompt: str | None = None,
) -> dict[str, Any]:
    from autonomous.services import chat_attachments as attach_svc
    from autonomous.services.errors import ValidationError

    bots_svc.get_bot(bot, home=home)
    content = (content or "").strip()
    agent_prompt = (prompt or "").strip() or content
    stored: list = []
    if role == "user":
        # Known vault secrets must never reach the LLM — refuse before insert.
        # Check both the visible bubble and the optional agent prompt override.
        for blob in (content, agent_prompt):
            if not blob:
                continue
            try:
                from autonomous.services import vault as vault_svc

                if vault_svc.text_contains_vault_secret(blob, home=home):
                    raise ValidationError(
                        "Message refusé : divulgation d’un secret du coffre.",
                        code="secret_disclosure",
                    )
            except ValidationError:
                raise
            except Exception:
                pass
        stored = attach_svc.normalize_attachments(bot, attachments, home=home)
    elif attachments:
        stored = list(attachments)
    if not content and not stored:
        raise ValidationError("content or attachments required")
    if not content and stored:
        files = attach_svc.file_attachments(stored)
        images = attach_svc.image_attachments(stored)
        if files and not images:
            content = "(fichier)" if len(files) == 1 else f"({len(files)} fichiers)"
        elif images and not files:
            content = "(image)" if len(images) == 1 else f"({len(images)} images)"
        else:
            content = f"({len(stored)} pièces jointes)"

    msg_id = str(uuid.uuid4())
    now = _now()
    meta: dict[str, Any] = {}
    if role == "user" and agent_prompt and agent_prompt != content:
        # Keep a short bubble in the thread; run the longer prompt when drained.
        meta["agent_prompt"] = agent_prompt
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO messages(
              id, bot, conversation_id, role, content,
              attachments_json, meta_json, created_at
            ) VALUES (?, ?, 'main', ?, ?, ?, ?, ?)
            """,
            (msg_id, bot, role, content, json.dumps(stored), json.dumps(meta), now),
        )
    message = {
        "id": msg_id,
        "bot": bot,
        "conversation_id": "main",
        "role": role,
        "content": content,
        "attachments": stored,
        "meta": meta,
        "created_at": now,
    }
    BUS.publish("message.created", {"message": message}, bot=bot)
    try:
        from autonomous.services import search as search_svc

        search_svc.index_message(message, home=home)
    except Exception:
        pass

    if role == "user" and trigger_agent:
        from autonomous.services import botmail as botmail_svc

        routed = botmail_svc.maybe_route_from_composer(
            bot, content, message_id=msg_id, home=home
        )
        if routed is not None:
            if routed.get("skip_agent"):
                return message
            # Dit/Demande : l’agent local rédige le message peer (pas de bypass).
            agent_prompt = str(routed.get("agent_prompt") or agent_prompt)
            # Keep route_intent fields if we later stamp queued=True.
            meta = dict(meta)
            meta.update(
                {
                    "kind": "botmail",
                    "mail_kind": "route_intent",
                    "mode": routed.get("mode"),
                    "to_bot": routed.get("to_bot"),
                    "link_bot": routed.get("to_bot"),
                    "agent_prompt": agent_prompt,
                }
            )
            message["meta"] = meta

        # Agent already working → keep the bubble, run later (FIFO).
        if bot_run_blocked(bot, home=home):
            # Waiting on a vault form: a chat reply cancels the form and guides
            # the agent (e.g. « validate on another device », not an OTP code).
            # Do not park the message in the queue — that loses the intent if the
            # the user later hits « Refuser » on the card.
            row = bots_svc.get_bot(bot, home=home)
            if (row.get("status") or "") == "waiting":
                cancelled: list = []
                try:
                    from autonomous.services import vault as vault_svc

                    cancelled = vault_svc.cancel_pending_for_human_message(
                        bot, agent_prompt, home=home
                    )
                except Exception:
                    cancelled = []
                if not cancelled:
                    try:
                        from autonomous.services import approvals as approval_svc

                        cancelled = approval_svc.cancel_pending_for_human_message(
                            bot, agent_prompt, home=home
                        )
                    except Exception:
                        cancelled = []
                if not cancelled:
                    try:
                        from autonomous.services import clarifies as clarify_svc

                        cancelled = clarify_svc.cancel_pending_for_human_message(
                            bot, agent_prompt, home=home
                        )
                    except Exception:
                        cancelled = []
                if cancelled:
                    return message
            return _mark_queued(bot, msg_id, content, meta, home=home)

        from autonomous.services.agent import run_in_progress

        # Status can still say idle for a moment after a run has claimed the slot.
        # Parking here avoids a second start_run that would drop the message.
        if run_in_progress(bot):
            return _mark_queued(bot, msg_id, content, meta, home=home)

        started = _start_agent_for_user_message(
            bot, agent_prompt, stored, home=home, message_id=msg_id
        )
        if started == "busy":
            return _mark_queued(bot, msg_id, content, meta, home=home)
    return message


def _mark_queued(
    bot: str,
    msg_id: str,
    content: str,
    meta: dict[str, Any],
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    queued_meta = dict(meta)
    queued_meta["queued"] = True
    return update_message(bot, msg_id, content, home=home, meta=queued_meta)


def _start_agent_for_user_message(
    bot: str,
    content: str,
    stored: list,
    *,
    home: Path | None = None,
    message_id: str | None = None,
) -> str:
    from autonomous.services import chat_attachments as attach_svc
    from autonomous.services import reactions as reactions_svc

    reactions_svc.set_turn_message(bot, message_id)

    backend = str(settings_svc.get("agent_backend", home=home, default="pi") or "pi")
    if backend == "null" and settings_svc.get(
        "ack_unwired_agent", home=home, default=False
    ):
        send_message(
            bot,
            "Agent not wired.",
            role="system",
            home=home,
            trigger_agent=False,
        )
        return ""
    if backend == "null":
        return ""
    from autonomous.services.agent import get_agent

    prompt = attach_svc.prompt_with_files(
        content, stored, bot=bot, home=home
    )
    prompt, images = attach_svc.apply_vision_budget(
        bot, prompt, stored, home=home
    )
    return str(
        get_agent(backend, home=home).start_run(
            bot, prompt, home=home, images=images
        )
        or ""
    )


def list_queued_user_messages(
    bot: str, *, home: Path | None = None
) -> list[dict[str, Any]]:
    """User bubbles still marked ``meta.queued`` (oldest first)."""
    out: list[dict[str, Any]] = []
    for msg in list_messages(bot, limit=200, home=home):
        if msg.get("role") != "user":
            continue
        if (msg.get("meta") or {}).get("queued"):
            out.append(msg)
    out.sort(key=lambda m: m.get("created_at") or "")
    return out


def clear_queued_flags(
    bot: str,
    message_ids: list[str],
    *,
    home: Path | None = None,
) -> int:
    """Drop ``queued`` on the given user messages so they display as normal."""
    n = 0
    wanted = {str(i) for i in message_ids if i}
    if not wanted:
        return 0
    for msg in list_messages(bot, limit=200, home=home):
        if msg["id"] not in wanted:
            continue
        meta = dict(msg.get("meta") or {})
        if not meta.pop("queued", None):
            continue
        update_message(
            bot,
            msg["id"],
            msg.get("content") or "",
            home=home,
            meta=meta,
        )
        n += 1
    return n


def drain_queued_user_messages(bot: str, *, home: Path | None = None) -> bool:
    """Start the oldest queued user message if the bot is idle. Returns True if started."""
    if bot_run_blocked(bot, home=home):
        return False
    queued = list_queued_user_messages(bot, home=home)
    if not queued:
        return False
    target = queued[0]
    meta = dict(target.get("meta") or {})
    meta.pop("queued", None)
    agent_text = (meta.get("agent_prompt") or target.get("content") or "").strip()
    # Stamp as "sent now" so the bubble lands after the previous turn in the UI.
    update_message(
        bot,
        target["id"],
        target["content"],
        home=home,
        meta=meta,
        bump_created_at=True,
    )
    _start_agent_for_user_message(
        bot,
        agent_text or (target.get("content") or ""),
        target.get("attachments") or [],
        home=home,
        message_id=target["id"],
    )
    return True


def _scrub_outbound_content(role: str, content: str, *, home: Path | None = None) -> str:
    """Never let vault secrets appear in assistant/event/system bubbles."""
    if role == "user" or not content:
        return content
    try:
        from autonomous.services import vault as vault_svc

        return vault_svc.redact_secrets_in_text(content, home=home)
    except Exception:
        return content


def create_message(
    bot: str,
    content: str,
    *,
    role: str = "assistant",
    meta: dict[str, Any] | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    msg_id = str(uuid.uuid4())
    now = _now()
    meta = dict(meta or {})
    content = _scrub_outbound_content(role, content, home=home)
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO messages(
              id, bot, conversation_id, role, content,
              attachments_json, meta_json, created_at
            ) VALUES (?, ?, 'main', ?, ?, '[]', ?, ?)
            """,
            (msg_id, bot, role, content, json.dumps(meta), now),
        )
    message = {
        "id": msg_id,
        "bot": bot,
        "conversation_id": "main",
        "role": role,
        "content": content,
        "attachments": [],
        "meta": meta,
        "created_at": now,
    }
    BUS.publish("message.created", {"message": message}, bot=bot)
    try:
        from autonomous.services import search as search_svc

        search_svc.index_message(message, home=home)
    except Exception:
        pass
    return message


def create_assistant_placeholder(bot: str, home: Path | None = None) -> dict[str, Any]:
    return create_message(
        bot, "", role="assistant", meta={"streaming": True}, home=home
    )


def find_streaming_assistant(
    bot: str, *, home: Path | None = None
) -> dict[str, Any] | None:
    """Latest assistant bubble still marked streaming (e.g. opened by files_share_image)."""
    bots_svc.get_bot(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE bot = ? AND conversation_id = 'main' AND role = 'assistant'
            ORDER BY created_at DESC LIMIT 8
            """,
            (bot,),
        ).fetchall()
    for row in rows:
        msg = _decode(row)
        if (msg.get("meta") or {}).get("streaming"):
            return msg
    return None


def append_attachments(
    bot: str,
    msg_id: str,
    attachments: list[Any],
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Append attachment entries to a message and broadcast ``message.updated``."""
    bots_svc.get_bot(bot, home=home)
    extra = [a for a in (attachments or []) if a is not None]
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ? AND bot = ?",
            (msg_id, bot),
        ).fetchone()
        if not row:
            raise AutonomousError("Message not found", code="not_found")
        current = json.loads(row["attachments_json"] or "[]")
        seen_paths = {
            str(a.get("path") or "")
            for a in current
            if isinstance(a, dict) and a.get("path")
        }
        for att in extra:
            if isinstance(att, dict):
                path = str(att.get("path") or "")
                if path and path in seen_paths:
                    continue
                if path:
                    seen_paths.add(path)
            current.append(att)
        conn.execute(
            "UPDATE messages SET attachments_json = ? WHERE id = ? AND bot = ?",
            (json.dumps(current), msg_id, bot),
        )
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ? AND bot = ?",
            (msg_id, bot),
        ).fetchone()
    message = _decode(row)
    BUS.publish("message.updated", {"message": message}, bot=bot)
    return message


def finalize_streaming_assistants(bot: str, *, home: Path | None = None) -> int:
    """Clear streaming flag on any leftover assistant bubbles (end of run)."""
    n = 0
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT id, content, meta_json FROM messages
            WHERE bot = ? AND role = 'assistant'
            ORDER BY created_at DESC LIMIT 12
            """,
            (bot,),
        ).fetchall()
    for row in rows:
        meta = json.loads(row["meta_json"] or "{}")
        if not meta.get("streaming"):
            continue
        update_message(
            bot,
            row["id"],
            row["content"] or "",
            home=home,
            meta={**meta, "streaming": False},
        )
        n += 1
    return n


def update_message(
    bot: str,
    msg_id: str,
    content: str,
    *,
    home: Path | None = None,
    meta: dict[str, Any] | None = None,
    bump_created_at: bool = False,
) -> dict[str, Any]:
    meta = dict(meta or {})
    role = "assistant"
    try:
        with get_db(home) as conn:
            prev = conn.execute(
                "SELECT role FROM messages WHERE id = ? AND bot = ?",
                (msg_id, bot),
            ).fetchone()
        if prev:
            role = prev["role"] or "assistant"
    except Exception:
        pass
    content = _scrub_outbound_content(role, content, home=home)
    now = _now()
    with get_db(home) as conn:
        if bump_created_at:
            conn.execute(
                """
                UPDATE messages
                SET content = ?, meta_json = ?, created_at = ?
                WHERE id = ? AND bot = ?
                """,
                (content, json.dumps(meta), now, msg_id, bot),
            )
        else:
            conn.execute(
                """
                UPDATE messages
                SET content = ?, meta_json = ?
                WHERE id = ? AND bot = ?
                """,
                (content, json.dumps(meta), msg_id, bot),
            )
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ? AND bot = ?", (msg_id, bot)
        ).fetchone()
    if not row:
        return {
            "id": msg_id,
            "bot": bot,
            "conversation_id": "main",
            "role": "assistant",
            "content": content,
            "attachments": [],
            "meta": meta,
            "created_at": now,
        }
    message = _decode(row)
    BUS.publish("message.updated", {"message": message}, bot=bot)
    try:
        from autonomous.services import search as search_svc

        search_svc.index_message(message, home=home)
    except Exception:
        pass
    return message


def finalize_assistant(
    bot: str,
    msg_id: str,
    content: str,
    *,
    home: Path | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = dict(meta or {})
    meta["streaming"] = False
    return update_message(bot, msg_id, content, home=home, meta=meta)


def stop_run(bot: str, home: Path | None = None) -> None:
    bots_svc.get_bot(bot, home=home)
    from autonomous.services.agent import get_agent

    backend = str(settings_svc.get("agent_backend", home=home, default="pi") or "pi")
    get_agent(backend, home=home).stop_run(bot, home=home)
    # Finalize any dangling streaming assistant bubbles.
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT id, content, meta_json FROM messages
            WHERE bot = ? AND role = 'assistant'
            ORDER BY created_at DESC LIMIT 5
            """,
            (bot,),
        ).fetchall()
    for row in rows:
        meta = json.loads(row["meta_json"] or "{}")
        if meta.get("streaming"):
            finalize_assistant(
                bot,
                row["id"],
                row["content"] or "⏹ Stopped.",
                home=home,
                meta={**meta, "aborted": True},
            )
            break


_INTERRUPT_TOOL_ERROR = "Session agent interrompue pendant l’attente d’approbation."
_INTERRUPT_CARD = (
    "The agent session was interrupted while waiting for approval. "
    "Click Resume to relaunch the agent."
)
_RESUME_PROMPT = (
    "Continue from where you left off. User approvals already granted "
    "(vault / desk) remain valid — do not ask again unnecessarily."
)


def close_running_tools(
    bot: str,
    *,
    error: str = _INTERRUPT_TOOL_ERROR,
    home: Path | None = None,
    hint_resume: bool | None = None,
) -> int:
    """Mark open tool cards as error (dead Pi mid-tool / run settled without end)."""
    if hint_resume is None:
        hint_resume = error == _INTERRUPT_TOOL_ERROR
    n = 0
    # Long runs emit many grounding notes between a tool start and its end: scan deep.
    for msg in list_messages(bot, limit=400, home=home):
        meta = dict(msg.get("meta") or {})
        if meta.get("kind") != "tool" or meta.get("status") != "running":
            continue
        meta["status"] = "error"
        meta["error"] = error
        content = msg.get("content") or ""
        lines = [
            "status: error" if line.startswith("status:") else line
            for line in content.split("\n")
        ]
        if error not in content:
            lines.append("---")
            lines.append(error)
            if hint_resume:
                lines.append("Utilise le bouton Reprendre dans le chat.")
        update_message(bot, msg["id"], "\n".join(lines), home=home, meta=meta)
        n += 1
    return n


def post_agent_interrupted(
    bot: str,
    *,
    reason: str = "",
    home: Path | None = None,
) -> dict[str, Any] | None:
    """Chat card with a Reprendre button. Dedupes while one is still pending."""
    for msg in reversed(list_messages(bot, limit=40, home=home)):
        meta = msg.get("meta") or {}
        if (
            msg.get("role") == "event"
            and meta.get("kind") == "agent_interrupted"
            and meta.get("state") == "pending"
        ):
            return msg
    content = (reason or "").strip() or _INTERRUPT_CARD
    return create_message(
        bot,
        content,
        role="event",
        meta={
            "kind": "agent_interrupted",
            "state": "pending",
            "can_resume": True,
        },
        home=home,
    )


def mark_interrupted_after_wait(bot: str, *, home: Path | None = None) -> None:
    """User resolved vault/desk but Pi session is dead → idle + Reprendre card."""
    bots_svc.patch_bot(bot, {"status": "idle"}, home=home)
    close_running_tools(bot, home=home)
    post_agent_interrupted(bot, home=home)
    try:
        drain_queued_user_messages(bot, home=home)
    except Exception:
        pass


def _mark_resume_cards(bot: str, *, state: str, home: Path | None = None) -> int:
    n = 0
    label = (
        "Reprise lancée."
        if state == "resumed"
        else "Carte reprise ignorée."
    )
    for msg in list_messages(bot, limit=80, home=home):
        meta = dict(msg.get("meta") or {})
        if (
            msg.get("role") == "event"
            and meta.get("kind") == "agent_interrupted"
            and meta.get("state") == "pending"
        ):
            meta["state"] = state
            meta["can_resume"] = False
            update_message(bot, msg["id"], label, home=home, meta=meta)
            n += 1
    return n


def resume_run(bot: str, home: Path | None = None) -> dict[str, Any]:
    """Restart the agent after an interrupted wait (no new user bubble)."""
    from autonomous.services.agent import get_agent
    from autonomous.services.errors import Conflict

    row = bots_svc.get_bot(bot, home=home)
    status = row.get("status") or "idle"
    if status in ("busy", "waiting"):
        raise Conflict("Agent déjà en cours ou en attente")

    _mark_resume_cards(bot, state="resumed", home=home)

    last_user = ""
    last_user_id = ""
    for msg in reversed(list_messages(bot, limit=80, home=home)):
        if msg.get("role") == "user":
            last_user = (msg.get("content") or "").strip()
            last_user_id = msg.get("id") or ""
            break
    from autonomous.services import reactions as reactions_svc

    reactions_svc.set_turn_message(bot, last_user_id or None)

    prompt = _RESUME_PROMPT
    if last_user:
        prompt = f"{_RESUME_PROMPT}\n\nOriginal task:\n{last_user}"

    backend = str(settings_svc.get("agent_backend", home=home, default="pi") or "pi")
    get_agent(backend, home=home).start_run(bot, prompt, home=home)
    return {"ok": True}


def clear_messages(bot: str, home: Path | None = None) -> int:
    bots_svc.get_bot(bot, home=home)
    # Drop live Pi process, wipe transcripts, rotate id — UI + Pi context stay aligned.
    from autonomous.services.pi_rpc import purge_pi_sessions

    MANAGER.stop(bot)
    purge_pi_sessions(bot, home=home)
    new_id = new_session_id(bot)
    bots_svc.patch_bot(bot, {"pi_session_id": new_id, "status": "idle"}, home=home)
    with get_db(home) as conn:
        cur = conn.execute("DELETE FROM messages WHERE bot = ?", (bot,))
        deleted = cur.rowcount
    try:
        bots_svc.reset_token_usage(bot, home=home)
    except Exception:
        pass
    try:
        from autonomous.services import search as search_svc

        search_svc.clear_bot_index(bot, home=home)
    except Exception:
        pass
    BUS.publish("message.cleared", {"bot": bot, "deleted": deleted}, bot=bot)
    return deleted
