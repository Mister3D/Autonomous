"""Bot CRUD service."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.avatars import is_valid_avatar, pick_avatar
from autonomous.db import get_db, row_to_dict
from autonomous.i18n import t
from autonomous.paths import bot_dir
from autonomous.services.errors import Conflict, NotFound, ValidationError
from autonomous.services.events import BUS

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_DISPLAY_FORBIDDEN_RE = re.compile(r"[\x00-\x1f\x7f/\\]")
_MAX_DISPLAY_LEN = 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    auto_raw = row.get("auto_sleep", 1)
    bot = {
        "id": row.get("id") or "",
        "name": row["name"],
        "label": row["label"],
        "capability": row["capability"],
        "internet": bool(row["internet"]),
        "auto_sleep": True if auto_raw is None else bool(auto_raw),
        "memory_access": bool(row.get("memory_access", 1)),
        "is_manager": bool(row.get("is_manager", 0)),
        "desk_last_active_at": row.get("desk_last_active_at") or None,
        "status": row["status"],
        "model": row.get("model") or "",
        "pi_session_id": row.get("pi_session_id") or "",
        "guard": json.loads(row["guard_json"] or "{}"),
        "desk": json.loads(row["desk_json"]) if row["desk_json"] else None,
        "last_message_at": row.get("last_message_at") or None,
        "tokens_in": int(row.get("tokens_in") or 0),
        "tokens_out": int(row.get("tokens_out") or 0),
        "avatar": (row.get("avatar") or "").strip(),
        "avatar_color": int(row.get("avatar_color") or 0),
        "companion_id": (row.get("companion_id") or "") or None,
        "companion_egress": bool(row.get("companion_egress") or 0),
        "companion_killswitch": bool(row.get("companion_killswitch") or 0),
        "companion_name": "",
        "companion_online": False,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    return bot


def _attach_companions(bots: list[dict[str, Any]], home: Path | None) -> list[dict[str, Any]]:
    ids = [b["companion_id"] for b in bots if b.get("companion_id")]
    names: dict[str, str] = {}
    if ids:
        with get_db(home) as conn:
            marks = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT id, name FROM devices WHERE revoked_at IS NULL AND id IN ({marks})",
                tuple(ids),
            ).fetchall()
        names = {r["id"]: r["name"] for r in rows}
    online: set[str] = set()
    if ids:
        from autonomous.services import companion_link as link_svc

        online = set(link_svc.online_device_ids(home))
    for bot in bots:
        cid = bot.get("companion_id") or ""
        if cid and cid not in names:
            bot["companion_id"] = None
            bot["companion_name"] = ""
            bot["companion_online"] = False
        else:
            bot["companion_name"] = names.get(cid, "")
            bot["companion_online"] = bool(cid) and cid in online
    return bots


def companion_routes(*, home: Path | None = None) -> list[dict[str, Any]]:
    """Bots that send their traffic through a chosen companion."""
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT name, companion_id, companion_egress, companion_killswitch
            FROM bots
            WHERE companion_id IS NOT NULL AND companion_id != ''
              AND companion_egress = 1
            """
        ).fetchall()
    return [
        {
            "name": r["name"],
            "companion_id": r["companion_id"],
            "egress": bool(r["companion_egress"]),
            "killswitch": bool(r["companion_killswitch"]),
        }
        for r in rows
    ]


def new_bot_id() -> str:
    return str(uuid.uuid4())


def looks_like_bot_id(value: str) -> bool:
    return bool(_UUID_RE.match((value or "").strip()))


def get_bot_by_id(bot_id: str, home: Path | None = None) -> dict[str, Any]:
    bid = (bot_id or "").strip()
    if not bid:
        raise NotFound(t("bot.not_found", name=bot_id or "?"))
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT bots.*,
              (
                SELECT MAX(created_at) FROM messages
                WHERE messages.bot = bots.name
              ) AS last_message_at
            FROM bots
            WHERE id = ?
            """,
            (bid,),
        ).fetchone()
    if not row:
        raise NotFound(t("bot.not_found", name=bid))
    return _attach_companions([_decode(dict(row))], home)[0]


def bot_uuid(name_or_id: str, home: Path | None = None) -> str:
    """Resolve slug or UUID to the stable bots.id."""
    ref = (name_or_id or "").strip()
    if not ref:
        raise NotFound(t("bot.not_found", name=ref or "?"))
    if looks_like_bot_id(ref):
        return get_bot_by_id(ref, home=home)["id"]
    return get_bot(ref, home=home)["id"]


def bot_slug(name_or_id: str, home: Path | None = None) -> str:
    """Resolve slug or UUID to the technical slug (`bots.name`)."""
    ref = (name_or_id or "").strip()
    if not ref:
        raise NotFound(t("bot.not_found", name=ref or "?"))
    if looks_like_bot_id(ref):
        return get_bot_by_id(ref, home=home)["name"]
    return get_bot(ref, home=home)["name"]


def validate_name(name: str) -> str:
    """Validate technical slug (`bots.name` / URL / Docker)."""
    if not _NAME_RE.match(name or ""):
        raise ValidationError(t("bot.invalid_name"), code="invalid_name")
    return name


def validate_display_name(display: str) -> str:
    text = (display or "").strip()
    if not text or len(text) > _MAX_DISPLAY_LEN:
        raise ValidationError(t("bot.invalid_display_name"), code="invalid_display_name")
    if _DISPLAY_FORBIDDEN_RE.search(text):
        raise ValidationError(t("bot.invalid_display_name"), code="invalid_display_name")
    return text


def slugify_bot_name(raw: str) -> str:
    """Build a technical slug from a free-form display name."""
    text = unicodedata.normalize("NFD", str(raw or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9_-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    if text and text[0] in "-_":
        text = text.lstrip("-_")
    text = text[:32].rstrip("-_")
    return text


def _slug_exists(name: str, home: Path | None = None) -> bool:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT 1 FROM bots WHERE lower(name) = lower(?)",
            (name,),
        ).fetchone()
    return row is not None


def _name_key(text: str) -> str:
    """Case-insensitive identity for display names (Test == test == TEST)."""
    return unicodedata.normalize("NFKC", str(text or "")).casefold().strip()


def display_name_taken(
    display: str,
    *,
    home: Path | None = None,
    exclude: str | None = None,
) -> str | None:
    """Return the existing bot name if ``display`` collides case-insensitively.

    Compares against both ``label`` and technical ``name``.
    """
    key = _name_key(display)
    if not key:
        return None
    excl = (exclude or "").strip().lower() or None
    for bot in list_bots(home=home):
        if excl and bot["name"].lower() == excl:
            continue
        if _name_key(bot.get("label") or "") == key:
            return bot["name"]
        if _name_key(bot.get("name") or "") == key:
            return bot["name"]
    return None


def allocate_slug(base: str, home: Path | None = None) -> str:
    """Return an unused slug derived from ``base`` (adds -2, -3, … if needed)."""
    root = slugify_bot_name(base)
    if not root or not _NAME_RE.match(root):
        raise ValidationError(t("bot.invalid_name"), code="invalid_name")
    if not _slug_exists(root, home=home):
        return root
    n = 2
    while n < 1000:
        suffix = f"-{n}"
        candidate = f"{root[: 32 - len(suffix)]}{suffix}"
        if _NAME_RE.match(candidate) and not _slug_exists(candidate, home=home):
            return candidate
        n += 1
    raise Conflict(t("bot.exists", name=root))


def list_bots(home: Path | None = None) -> list[dict[str, Any]]:
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT bots.*,
              (
                SELECT MAX(created_at) FROM messages
                WHERE messages.bot = bots.name
              ) AS last_message_at
            FROM bots
            ORDER BY COALESCE(last_message_at, created_at) DESC
            """
        ).fetchall()
    return _attach_companions([_decode(dict(r)) for r in rows], home)


def get_bot(name: str, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT bots.*,
              (
                SELECT MAX(created_at) FROM messages
                WHERE messages.bot = bots.name
              ) AS last_message_at
            FROM bots
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
    if not row:
        raise NotFound(t("bot.not_found", name=name))
    return _attach_companions([_decode(dict(row))], home)[0]


def get_manager(
    *, home: Path | None = None, exclude: str | None = None
) -> dict[str, Any] | None:
    """Return the current Manager bot, or None.

    At most one Manager is allowed. ``exclude`` skips that technical name
    (used when re-affirming / checking promotion of another bot).
    """
    with get_db(home) as conn:
        if exclude:
            row = conn.execute(
                """
                SELECT * FROM bots
                WHERE is_manager = 1 AND name != ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (exclude,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM bots
                WHERE is_manager = 1
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
    return _decode(dict(row)) if row else None


def ensure_manager_slot(*, home: Path | None = None, exclude: str | None = None) -> None:
    """Raise Conflict if another Manager already exists."""
    other = get_manager(home=home, exclude=exclude)
    if other:
        raise Conflict(
            t("bot.manager_exists", name=other.get("label") or other["name"]),
            code="manager_exists",
        )


def create_bot(
    name: str,
    *,
    label: str | None = None,
    slug: str | None = None,
    internet: bool = True,
    memory_access: bool = True,
    is_manager: bool = False,
    model: str | None = None,
    avatar: str | None = None,
    avatar_color: int | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Create a bot.

    ``name`` is the display name (spaces / capitals allowed). The technical
    id stored in ``bots.name`` is ``slug`` when provided, otherwise derived via
    :func:`slugify_bot_name` (with ``-2``, ``-3``, … on collision).

    ``label`` overrides the display string when set (legacy clients).
    ``is_manager`` marks an orchestrator (peer list + async delegation).
    Only one Manager is allowed across all bots.
    """
    display = validate_display_name(label if label not in (None, "") else name)
    taken = display_name_taken(display, home=home)
    if taken:
        raise Conflict(t("bot.exists", name=display), code="bot_exists")
    if slug not in (None, ""):
        tech = validate_name(str(slug).strip())
        if _slug_exists(tech, home=home):
            raise Conflict(t("bot.exists", name=tech), code="bot_exists")
    else:
        tech = allocate_slug(display, home=home)
    if is_manager:
        ensure_manager_slot(home=home)
    now = _now()
    guard = {"review_every": None, "max_actions": None}
    from autonomous.paths import bot_pi_dir
    from autonomous.services.pi_rpc import new_session_id

    session_id = new_session_id(tech)
    bot_id = new_bot_id()
    # No auto-pick: empty model stays empty (API / UI require a model at create).
    model_ref = (model or "").strip()
    used_avatars = {b.get("avatar") or "" for b in list_bots(home=home)}
    avatar_raw = (avatar or "").strip()
    if avatar_raw:
        if not is_valid_avatar(avatar_raw):
            raise ValidationError(f"avatar inconnu: {avatar_raw}", code="invalid_avatar")
        avatar_id = avatar_raw
    else:
        avatar_id = pick_avatar(used_avatars)
    if avatar_color is None:
        color_idx = 0
    else:
        try:
            color_idx = int(avatar_color)
        except (TypeError, ValueError) as exc:
            raise ValidationError("avatar_color invalide", code="invalid_avatar_color") from exc
        color_idx = max(0, min(17, color_idx))
    try:
        with get_db(home) as conn:
            conn.execute(
                """
                INSERT INTO bots(
                  id, name, label, capability, internet, auto_sleep, status,
                  guard_json, desk_json, model, pi_session_id, memory_access,
                  is_manager, avatar, avatar_color,
                  created_at, updated_at
                ) VALUES (?, ?, ?, 'none', ?, 1, 'idle', ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bot_id,
                    tech,
                    display,
                    1 if internet else 0,
                    json.dumps(guard),
                    model_ref,
                    session_id,
                    1 if memory_access else 0,
                    1 if is_manager else 0,
                    avatar_id,
                    color_idx,
                    now,
                    now,
                ),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper() or "unique" in str(exc).lower():
            raise Conflict(t("bot.exists", name=tech)) from exc
        raise
    bot_dir(tech, home)
    bot_pi_dir(tech, home)
    bot = get_bot(tech, home=home)
    BUS.publish("bot.created", {"bot": bot}, bot=tech)
    BUS.publish("notification", {"kind": "bot.created", "bot": bot}, bot=tech)
    return bot


def patch_bot(name: str, fields: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    get_bot(name, home=home)
    allowed = {
        "label",
        "internet",
        "auto_sleep",
        "memory_access",
        "is_manager",
        "desk_last_active_at",
        "guard",
        "status",
        "capability",
        "desk",
        "model",
        "pi_session_id",
        "avatar",
        "avatar_color",
        "companion_id",
        "companion_egress",
        "companion_killswitch",
    }
    # desk may be explicitly cleared with None (destroy); other fields still skip None
    nullable = {"desk", "desk_last_active_at", "companion_id"}
    updates = {
        k: v
        for k, v in fields.items()
        if k in allowed and (v is not None or k in nullable)
    }
    if not updates:
        return get_bot(name, home=home)
    sets: list[str] = []
    vals: list[Any] = []
    if "label" in updates:
        new_label = validate_display_name(updates["label"])
        taken = display_name_taken(new_label, home=home, exclude=name)
        if taken:
            raise Conflict(t("bot.exists", name=new_label), code="bot_exists")
        updates["label"] = new_label
        sets.append("label = ?")
        vals.append(new_label)
    if "internet" in updates:
        sets.append("internet = ?")
        vals.append(1 if updates["internet"] else 0)
    if "auto_sleep" in updates:
        sets.append("auto_sleep = ?")
        vals.append(1 if updates["auto_sleep"] else 0)
    if "memory_access" in updates:
        sets.append("memory_access = ?")
        vals.append(1 if updates["memory_access"] else 0)
    if "is_manager" in updates:
        if updates["is_manager"]:
            ensure_manager_slot(home=home, exclude=name)
        sets.append("is_manager = ?")
        vals.append(1 if updates["is_manager"] else 0)
    if "desk_last_active_at" in updates:
        sets.append("desk_last_active_at = ?")
        vals.append(updates["desk_last_active_at"])
    if "status" in updates:
        sets.append("status = ?")
        vals.append(updates["status"])
    if "capability" in updates:
        sets.append("capability = ?")
        vals.append(updates["capability"])
    if "model" in updates:
        sets.append("model = ?")
        vals.append(updates["model"] or "")
    if "pi_session_id" in updates:
        sets.append("pi_session_id = ?")
        vals.append(updates["pi_session_id"] or "")
    if "avatar" in updates:
        aid = str(updates["avatar"] or "").strip()
        if aid and not is_valid_avatar(aid):
            raise ValidationError(f"avatar inconnu: {aid}", code="invalid_avatar")
        sets.append("avatar = ?")
        vals.append(aid)
    if "avatar_color" in updates:
        try:
            color = int(updates["avatar_color"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("avatar_color invalide", code="invalid_avatar_color") from exc
        color = max(0, min(17, color))
        sets.append("avatar_color = ?")
        vals.append(color)
    companion_touched = bool(
        {"companion_id", "companion_egress", "companion_killswitch"} & set(updates)
    )
    if companion_touched:
        current = get_bot(name, home=home)
        cid = current.get("companion_id") or None
        egress = bool(current.get("companion_egress"))
        kill = bool(current.get("companion_killswitch"))
        if "companion_id" in updates:
            raw = str(updates.get("companion_id") or "").strip()
            if not raw:
                cid = None
            else:
                with get_db(home) as conn:
                    device = conn.execute(
                        """
                        SELECT id FROM devices
                        WHERE id = ? AND revoked_at IS NULL
                        """,
                        (raw,),
                    ).fetchone()
                if device is None:
                    raise NotFound("Compagnon introuvable.")
                cid = raw
        if "companion_egress" in updates:
            egress = bool(updates["companion_egress"])
        if "companion_killswitch" in updates:
            kill = bool(updates["companion_killswitch"])
        if not cid:
            egress = False
            kill = False
        if not egress:
            kill = False
        sets.append("companion_id = ?")
        vals.append(cid)
        sets.append("companion_egress = ?")
        vals.append(1 if egress else 0)
        sets.append("companion_killswitch = ?")
        vals.append(1 if kill else 0)
    if "guard" in updates:
        sets.append("guard_json = ?")
        vals.append(json.dumps(updates["guard"]))
    if "desk" in updates:
        sets.append("desk_json = ?")
        desk = updates["desk"]
        vals.append(json.dumps(desk) if desk is not None else None)
    sets.append("updated_at = ?")
    vals.append(_now())
    vals.append(name)
    with get_db(home) as conn:
        conn.execute(f"UPDATE bots SET {', '.join(sets)} WHERE name = ?", vals)
    if companion_touched:
        from autonomous.services import companion_egress as egress_svc

        egress_svc.refresh(home)
    if "is_manager" in updates:
        # Restart Pi so manager system prompt / tools guidance refreshes.
        from autonomous.services.pi_rpc import MANAGER

        try:
            MANAGER.stop(name)
        except Exception:
            pass
    bot = get_bot(name, home=home)
    if "model" in updates and updates["model"]:
        from autonomous.services.pi_rpc import MANAGER, PiRpcError

        session = MANAGER.get(name)
        if session and session.alive:
            try:
                session.set_model(str(updates["model"]))
            except PiRpcError:
                pass
    BUS.publish("bot.updated", {"bot": bot}, bot=name)
    if updates.get("status") == "busy":
        BUS.publish("notification", {"kind": "bot.busy", "bot": bot}, bot=name)
    elif updates.get("status") == "waiting":
        BUS.publish("notification", {"kind": "bot.waiting", "bot": bot}, bot=name)
    return bot


def add_token_usage(
    name: str,
    tokens_in: int,
    tokens_out: int,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Accumulate Pi usage.input / usage.output for the bot conversation.

    Also records durable daily history (survives chat clear; purged on bot delete).
    """
    get_bot(name, home=home)
    tin = max(0, int(tokens_in or 0))
    tout = max(0, int(tokens_out or 0))
    if tin == 0 and tout == 0:
        return get_bot(name, home=home)
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE bots
            SET tokens_in = COALESCE(tokens_in, 0) + ?,
                tokens_out = COALESCE(tokens_out, 0) + ?,
                updated_at = ?
            WHERE name = ?
            """,
            (tin, tout, _now(), name),
        )
    from autonomous.services import token_usage_history as usage_hist

    usage_hist.record_usage(name, tin, tout, home=home)
    bot = get_bot(name, home=home)
    BUS.publish("bot.updated", {"bot": bot}, bot=name)
    return bot


def reset_token_usage(name: str, *, home: Path | None = None) -> dict[str, Any]:
    get_bot(name, home=home)
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE bots
            SET tokens_in = 0, tokens_out = 0, updated_at = ?
            WHERE name = ?
            """,
            (_now(), name),
        )
    bot = get_bot(name, home=home)
    BUS.publish("bot.updated", {"bot": bot}, bot=name)
    return bot


def delete_bot(name: str, home: Path | None = None, destroy_desk: bool = True) -> None:
    bot_row = get_bot(name, home=home)
    bid = bot_row.get("id") or ""
    try:
        from autonomous.services.pi_rpc import MANAGER

        MANAGER.stop(name)
    except Exception:
        pass
    if destroy_desk:
        try:
            from autonomous.services import desk as desk_svc

            desk_svc.destroy(name, home=home, wait=True)
        except Exception:
            pass
    # Cross-bot refs key off bots.id (UUID). Purge by id so a recreated slug
    # cannot inherit mail / grants / schedules from a previous life.
    try:
        from autonomous.services import botmail as botmail_svc

        botmail_svc.purge_for_bot(bid or name, home=home)
    except Exception:
        pass
    try:
        from autonomous.services import memory as memory_svc

        if bid:
            memory_svc.purge_for_bot(bid, home=home)
    except Exception:
        pass
    try:
        from autonomous.services import approvals as approval_svc

        if bid:
            approval_svc.purge_for_bot(bid, home=home)
    except Exception:
        pass
    try:
        from autonomous.services import clarifies as clarify_svc

        if bid:
            clarify_svc.purge_for_bot(bid, home=home)
    except Exception:
        pass
    try:
        from autonomous.services import household as household_svc

        if bid:
            household_svc.purge_for_bot(bid, home=home)
    except Exception:
        pass
    with get_db(home) as conn:
        conn.execute("DELETE FROM messages WHERE bot = ?", (name,))
        conn.execute("DELETE FROM terminal_logs WHERE bot = ?", (name,))
        if bid:
            conn.execute("DELETE FROM bot_schedules WHERE bot = ?", (bid,))
            conn.execute("DELETE FROM bot_webhooks WHERE bot = ?", (bid,))
            conn.execute("DELETE FROM vault_grants WHERE bot = ?", (bid,))
            conn.execute("DELETE FROM vault_requests WHERE bot = ?", (bid,))
            conn.execute("DELETE FROM approval_requests WHERE bot = ?", (bid,))
            conn.execute("DELETE FROM clarify_requests WHERE bot = ?", (bid,))
            conn.execute("DELETE FROM bot_delete_requests WHERE bot = ?", (bid,))
        conn.execute("DELETE FROM bots WHERE name = ?", (name,))
    # Drop Pi session jsonl + VM home — otherwise recreate leaves orphans on disk.
    try:
        from autonomous.services.pi_rpc import wipe_bot_files

        wipe_bot_files(name, home=home)
    except Exception:
        pass
    BUS.publish("bot.deleted", {"name": name}, bot=name)
    BUS.publish("notification", {"kind": "bot.deleted", "name": name}, bot=name)


def set_capability(
    name: str,
    level: str,
    home: Path | None = None,
    *,
    wait: bool = False,
) -> dict[str, Any]:
    """``none`` removes the VM. Anything else is one VM (shell + desktop).

    ``terminal`` is accepted as an alias of ``screen`` (old clients).
    A running desk that never published noVNC is recreated so the screen works.
    """
    if level == "terminal":
        level = "screen"
    if level not in ("none", "screen"):
        raise ValidationError(f"Invalid capability: {level}")
    bot = get_bot(name, home=home)
    current = bot["capability"]
    from autonomous.services import desk as desk_svc

    if level == "none":
        if current != "none":
            desk_svc.destroy(name, home=home, wait=True)
        return patch_bot(name, {"capability": "none"}, home=home)

    desk = bot.get("desk") or {}
    state = desk.get("state")
    has_vnc = bool(desk.get("vnc_port"))
    if state == "sleeping" and has_vnc:
        desk_svc.ensure_awake(name, home=home)
    elif state != "running" or not has_vnc:
        desk_svc.create(name, home=home, wait=wait)
    return patch_bot(name, {"capability": "screen"}, home=home)
