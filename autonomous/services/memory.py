"""Global shared memory — core facts (always prompted) + browse-on-demand."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services.errors import NotFound, ValidationError
from autonomous.services.events import BUS

log = logging.getLogger("autonomous.memory")

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TIERS = frozenset({"core", "browse"})
_ACTIONS = frozenset({"set", "delete"})
_VALUE_MAX = 4000
_LABEL_MAX = 120
_REASON_MAX = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_key(key: str) -> str:
    k = (key or "").strip().lower()
    if not _KEY_RE.match(k):
        raise ValidationError(
            "key: a-z then a-z0-9_ (max 64)",
            code="memory_bad_key",
        )
    return k


def _clean_tier(tier: str) -> str:
    t = (tier or "browse").strip().lower()
    if t not in _TIERS:
        raise ValidationError("tier must be core|browse", code="memory_bad_tier")
    return t


def _clean_label(label: str, key: str) -> str:
    text = (label or "").strip() or key.replace("_", " ").title()
    if len(text) > _LABEL_MAX:
        raise ValidationError(f"label too long (max {_LABEL_MAX})")
    return text


def _clean_value(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValidationError("value required", code="memory_empty_value")
    if len(text) > _VALUE_MAX:
        raise ValidationError(f"value too long (max {_VALUE_MAX})")
    return text


def _decode_entry(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "label": row["label"],
        "value": row["value"],
        "tier": row["tier"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _decode_proposal(row, *, home: Path | None = None) -> dict[str, Any]:
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
        "action": row["action"],
        "key": row["key"],
        "label": row["label"] or "",
        "value": row["value"] or "",
        "tier": row["tier"],
        "reason": row["reason"] or "",
        "state": row["state"],
        "message_id": row["message_id"],
        "result": result,
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def bot_has_memory_access(bot: str, *, home: Path | None = None) -> bool:
    row = bots_svc.get_bot(bot, home=home)
    return bool(row.get("memory_access", True))


def require_memory_access(bot: str, *, home: Path | None = None) -> None:
    if not bot_has_memory_access(bot, home=home):
        raise ValidationError(
            "This bot has no access to shared memory",
            code="memory_denied",
        )


def list_entries(
    *,
    tier: str | None = None,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    with get_db(home) as conn:
        if tier:
            t = _clean_tier(tier)
            rows = conn.execute(
                "SELECT * FROM memory_entries WHERE tier = ? ORDER BY key",
                (t,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memory_entries ORDER BY tier, key"
            ).fetchall()
    return [_decode_entry(r) for r in rows]


def get_entry(key: str, *, home: Path | None = None) -> dict[str, Any]:
    k = _clean_key(key)
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM memory_entries WHERE key = ?", (k,)
        ).fetchone()
    if not row:
        raise NotFound(f"Memory key not found: {k}", code="memory_missing")
    return _decode_entry(row)


def search_entries(query: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return list_entries(home=home)
    out = []
    for e in list_entries(home=home):
        blob = f"{e['key']} {e['label']} {e['value']}".lower()
        if q in blob:
            out.append(e)
    return out


def upsert_entry(
    *,
    key: str,
    value: str,
    label: str = "",
    tier: str = "browse",
    home: Path | None = None,
) -> dict[str, Any]:
    k = _clean_key(key)
    v = _clean_value(value)
    t = _clean_tier(tier)
    lab = _clean_label(label, k)
    now = _now()
    eid = str(uuid.uuid4())
    with get_db(home) as conn:
        existing = conn.execute(
            "SELECT id FROM memory_entries WHERE key = ?", (k,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE memory_entries
                SET label = ?, value = ?, tier = ?, updated_at = ?
                WHERE key = ?
                """,
                (lab, v, t, now, k),
            )
            eid = existing["id"]
        else:
            conn.execute(
                """
                INSERT INTO memory_entries(
                  id, key, label, value, tier, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (eid, k, lab, v, t, now, now),
            )
    entry = get_entry(k, home=home)
    BUS.publish("memory.updated", {"entry": entry})
    return entry


def delete_entry(key: str, *, home: Path | None = None) -> None:
    k = _clean_key(key)
    with get_db(home) as conn:
        cur = conn.execute("DELETE FROM memory_entries WHERE key = ?", (k,))
        if cur.rowcount != 1:
            raise NotFound(f"Memory key not found: {k}", code="memory_missing")
    BUS.publish("memory.deleted", {"key": k})


def core_prompt_block(*, home: Path | None = None) -> str:
    """Core facts for the system prompt of a new conversation (not every message)."""
    core = list_entries(tier="core", home=home)
    if not core:
        return ""
    lines = [
        "Shared memory (always true for this household — do not re-ask):",
    ]
    for e in core:
        lines.append(f"- {e['label']} (`{e['key']}`): {e['value']}")
    lines.append(
        "Other facts may exist in shared memory — use memory_list / memory_get / "
        "memory_search when needed. To store a new fact, call memory_propose "
        "(never invent; the user approves via chat card — non-blocking)."
    )
    return "\n".join(lines)


def prompt_prefix_for_bot(bot: str, *, home: Path | None = None) -> str:
    """Core block for a bot with memory access (injected once at conversation start)."""
    if not bot_has_memory_access(bot, home=home):
        return ""
    return core_prompt_block(home=home)


def _first_chat_onboarding(home: Path | None = None) -> bool:
    """Setup conversation: save facts immediately (no Confirm card)."""
    try:
        from autonomous.services import settings as settings_svc

        return bool(
            settings_svc.get("first_chat_onboarding", home=home, default=False)
        )
    except Exception:
        return False


def propose(
    bot: str,
    *,
    action: str,
    key: str,
    value: str = "",
    label: str = "",
    tier: str = "browse",
    reason: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    """Queue a non-blocking memory change for user approval.

    During first-chat onboarding, applies immediately with no chat card so the
    setup clarify flow stays fluid.
    """
    require_memory_access(bot, home=home)
    act = (action or "").strip().lower()
    if act not in _ACTIONS:
        raise ValidationError("action must be set|delete", code="memory_bad_action")
    k = _clean_key(key)
    t = _clean_tier(tier)
    lab = _clean_label(label, k)
    reason = (reason or "").strip()
    if len(reason) > _REASON_MAX:
        raise ValidationError(f"reason too long (max {_REASON_MAX})")
    val = ""
    if act == "set":
        val = _clean_value(value)
    else:
        # delete: ensure key exists (or still propose if missing — the user decides)
        pass

    bid = bots_svc.bot_uuid(bot, home=home)
    pid = str(uuid.uuid4())
    now = _now()

    # First-run setup: write straight to shared memory (no Confirm / Decline card).
    if _first_chat_onboarding(home):
        result: dict[str, Any]
        if act == "delete":
            try:
                delete_entry(k, home=home)
            except NotFound:
                pass
            result = {
                "ok": True,
                "deleted": True,
                "key": k,
                "auto": True,
                "message": f"Removed shared memory key `{k}` (setup auto).",
            }
        else:
            entry = upsert_entry(
                key=k, value=val, label=lab, tier=t, home=home
            )
            result = {
                "ok": True,
                "saved": True,
                "auto": True,
                "entry": entry,
                "message": (
                    f"Saved shared memory `{entry['key']}` "
                    f"({entry['tier']}) during setup — no user card."
                ),
            }
        with get_db(home) as conn:
            conn.execute(
                """
                INSERT INTO memory_proposals(
                  id, bot, action, key, label, value, tier, reason, state,
                  message_id, result_json, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', NULL, ?, ?, ?)
                """,
                (
                    pid,
                    bid,
                    act,
                    k,
                    lab,
                    val,
                    t,
                    reason,
                    json.dumps(result),
                    now,
                    now,
                ),
            )
        prop = get_proposal(pid, home=home)
        BUS.publish("memory.proposal", {"proposal": prop}, bot=bot)
        BUS.publish("memory.updated", {"proposal": prop}, bot=bot)
        return prop

    title = (
        f"Mémoire — enregistrer « {lab} »"
        if act == "set"
        else f"Mémoire — oublier « {lab or k} »"
    )
    lines = [title, f"Bot: {bot}", f"Clé: {k}", f"Niveau: {t}"]
    if act == "set":
        lines.append(f"Valeur: {val}")
    if reason:
        lines.append(f"Motif: {reason}")
    lines.append(
        "Approuver pour écrire dans la mémoire partagée (les autres bots y auront accès). "
        "L’agent continue pendant ce temps — ce n’est pas bloquant."
    )
    content = "\n".join(lines)
    msg = chat_svc.create_message(
        bot,
        content,
        role="event",
        meta={
            "kind": "memory_proposal",
            "proposal_id": pid,
            "action": act,
            "key": k,
            "label": lab,
            "value": val if act == "set" else "",
            "tier": t,
            "reason": reason,
            "state": "pending",
        },
        home=home,
    )
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO memory_proposals(
              id, bot, action, key, label, value, tier, reason, state,
              message_id, result_json, created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, '{}', ?, NULL)
            """,
            (pid, bid, act, k, lab, val, t, reason, msg["id"], now),
        )
    prop = get_proposal(pid, home=home)
    BUS.publish("memory.proposal", {"proposal": prop}, bot=bot)
    # Intentionally do NOT set status=waiting — agent keeps working.
    return prop


def get_proposal(proposal_id: str, *, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM memory_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
    if not row:
        raise NotFound(f"Memory proposal not found: {proposal_id}")
    return _decode_proposal(row, home=home)


def resolve_proposal(
    proposal_id: str,
    *,
    action: str,
    home: Path | None = None,
) -> dict[str, Any]:
    prop = get_proposal(proposal_id, home=home)
    if prop["state"] != "pending":
        return prop
    act = (action or "").strip().lower()
    if act not in ("approve", "deny"):
        raise ValidationError("action must be approve|deny")
    now = _now()
    result: dict[str, Any]
    if act == "deny":
        state = "denied"
        result = {"ok": False, "denied": True, "message": "User denied the memory change."}
    else:
        state = "approved"
        try:
            if prop["action"] == "delete":
                try:
                    delete_entry(prop["key"], home=home)
                except NotFound:
                    pass
                result = {
                    "ok": True,
                    "deleted": True,
                    "key": prop["key"],
                    "message": f"Removed shared memory key `{prop['key']}`.",
                }
            else:
                entry = upsert_entry(
                    key=prop["key"],
                    value=prop["value"],
                    label=prop["label"],
                    tier=prop["tier"],
                    home=home,
                )
                result = {
                    "ok": True,
                    "saved": True,
                    "entry": entry,
                    "message": (
                        f"Saved shared memory `{entry['key']}` "
                        f"({entry['tier']}): {entry['value']}"
                    ),
                }
        except Exception as exc:
            log.exception("memory resolve failed")
            raise ValidationError(str(exc)) from exc

    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE memory_proposals
            SET state = ?, result_json = ?, resolved_at = ?
            WHERE id = ?
            """,
            (state, json.dumps(result), now, proposal_id),
        )
    if prop.get("message_id"):
        label = "Mémoire : modification refusée." if state == "denied" else "Mémoire : modification approuvée."
        if state == "approved" and result.get("message"):
            label = f"Mémoire : {result['message']}"
        chat_svc.update_message(
            prop["bot"],
            prop["message_id"],
            label,
            home=home,
            meta={
                "kind": "memory_proposal",
                "proposal_id": proposal_id,
                "action": prop["action"],
                "key": prop["key"],
                "label": prop["label"],
                "value": prop.get("value") or "",
                "tier": prop["tier"],
                "reason": prop.get("reason") or "",
                "state": state,
            },
        )
    out = get_proposal(proposal_id, home=home)
    BUS.publish("memory.proposal", {"proposal": out}, bot=prop["bot"])
    return out


def purge_for_bot(bot_id: str, *, home: Path | None = None) -> int:
    """Drop pending proposals for a deleted bot (by UUID)."""
    if not bot_id:
        return 0
    with get_db(home) as conn:
        return conn.execute(
            "DELETE FROM memory_proposals WHERE bot = ?", (bot_id,)
        ).rowcount
