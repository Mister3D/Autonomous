"""Global encrypted vault + bot grants + pending user requests."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.paths import ensure_home
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services.crypto_box import decrypt, encrypt
from autonomous.services.errors import NotFound, ValidationError
from autonomous.services.events import BUS



def _bot_id(bot: str, *, home: Path | None = None) -> str:
    return bots_svc.bot_uuid(bot, home=home)


def _bot_slug(bot_id: str, *, home: Path | None = None) -> str:
    try:
        return bots_svc.get_bot_by_id(bot_id, home=home)["name"]
    except Exception:
        return bot_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def vault_key_path(home: Path | None = None) -> Path:
    return ensure_home(home) / "vault.key"


def ensure_vault_key(home: Path | None = None) -> bytes:
    path = vault_key_path(home)
    if path.exists():
        return path.read_bytes()
    key = os.urandom(32)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


def _enc(home: Path | None, text: str) -> bytes:
    return encrypt(ensure_vault_key(home), text.encode("utf-8"))


def _dec(home: Path | None, blob: bytes) -> str:
    return decrypt(ensure_vault_key(home), blob).decode("utf-8")


def _row_fields(row) -> list[dict[str, Any]]:
    try:
        keys = row.keys()
    except Exception:
        keys = []
    raw = row["fields_json"] if "fields_json" in keys else "[]"
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        data = []
    return data if isinstance(data, list) else []


def _row_public(row) -> dict[str, Any]:
    try:
        keys = row.keys()
    except Exception:
        keys = []
    raw = row["public_json"] if "public_json" in keys else "{}"
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _public_entry(row) -> dict[str, Any]:
    public = _row_public(row)
    return {
        "id": row["id"],
        "label": row["label"],
        "kind": row["kind"],
        "origin": row["origin"] or "",
        "username": row["username"] or "",
        "fields": _row_fields(row),
        "public": public,
        "has_secret": True,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# Field schema for agent-defined credential forms (labels only — never values).
_FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

DEFAULT_LOGIN_FIELDS: list[dict[str, Any]] = [
    {"id": "username", "label": "Identifiant / e-mail", "secret": False, "required": True},
    {"id": "password", "label": "Mot de passe", "secret": True, "required": True},
]
DEFAULT_SECRET_FIELDS: list[dict[str, Any]] = [
    {"id": "secret", "label": "Secret / clé API", "secret": True, "required": True},
]


def normalize_fields(fields: Any, *, kind: str = "credential") -> list[dict[str, Any]]:
    """Validate/normalize agent field defs. Empty → defaults for login|secret."""
    if not fields:
        if kind == "login":
            return [dict(f) for f in DEFAULT_LOGIN_FIELDS]
        if kind == "secret":
            return [dict(f) for f in DEFAULT_SECRET_FIELDS]
        raise ValidationError("fields required for credential requests")
    if not isinstance(fields, list) or not fields:
        raise ValidationError("fields must be a non-empty list")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, raw in enumerate(fields):
        if not isinstance(raw, dict):
            raise ValidationError(f"fields[{i}] must be an object")
        fid = str(raw.get("id") or "").strip()
        label = str(raw.get("label") or "").strip()
        if not fid or not _FIELD_ID_RE.match(fid):
            raise ValidationError(
                f"fields[{i}].id must match [a-z][a-z0-9_]{{0,31}} (got {fid!r})"
            )
        if fid in seen:
            raise ValidationError(f"duplicate field id: {fid}")
        seen.add(fid)
        if not label:
            raise ValidationError(f"fields[{i}].label required")
        secret = bool(raw.get("secret", True))
        required = bool(raw.get("required", True))
        out.append({"id": fid, "label": label, "secret": secret, "required": required})
    if not any(f["secret"] for f in out):
        raise ValidationError("at least one field must be secret=true")
    return out


def _pack_secrets(secrets: dict[str, str]) -> str:
    # Always JSON so field ids survive a round-trip (even for a single key).
    return json.dumps(secrets, ensure_ascii=False)


def _unpack_secrets(raw: str) -> tuple[str, dict[str, str]]:
    """Return (primary_secret_string, secrets_dict)."""
    raw = raw or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw, {"secret": raw} if raw else {}
    if isinstance(data, dict) and data and all(isinstance(v, str) for v in data.values()):
        mapped = {str(k): str(v) for k, v in data.items()}
        primary = next(iter(mapped.values()), "")
        return primary, mapped
    return raw, {"secret": raw} if raw else {}


def list_entries(home: Path | None = None) -> list[dict[str, Any]]:
    ensure_vault_key(home)
    with get_db(home) as conn:
        rows = conn.execute(
            "SELECT * FROM vault_entries ORDER BY label COLLATE NOCASE ASC"
        ).fetchall()
    return [_public_entry(r) for r in rows]


# Scrub vault secrets out of chat/tool text (defense in depth if the model leaks).
_REDACT_MIN_LEN = 4
_secret_needles_cache: dict[str, tuple[float, tuple[str, ...]]] = {}
_SECRET_CACHE_TTL = 15.0


def invalidate_secret_redact_cache(home: Path | None = None) -> None:
    """Drop cached plaintext needles (call after vault create/update/delete)."""
    key = str(ensure_home(home))
    _secret_needles_cache.pop(key, None)


def _secret_needles(home: Path | None = None) -> tuple[str, ...]:
    import time

    root = str(ensure_home(home))
    now = time.monotonic()
    hit = _secret_needles_cache.get(root)
    if hit and now - hit[0] < _SECRET_CACHE_TTL:
        return hit[1]
    needles: list[str] = []
    try:
        ensure_vault_key(home)
        with get_db(home) as conn:
            rows = conn.execute("SELECT secret_blob FROM vault_entries").fetchall()
        for row in rows:
            try:
                primary, secrets = _unpack_secrets(_dec(home, row["secret_blob"]))
            except Exception:
                continue
            for val in {primary, *secrets.values()}:
                text = (val or "").strip()
                if len(text) >= _REDACT_MIN_LEN:
                    needles.append(text)
    except Exception:
        needles = []
    # Longest first so overlapping secrets redact cleanly.
    needles.sort(key=len, reverse=True)
    out = tuple(needles)
    _secret_needles_cache[root] = (now, out)
    return out


def scrub_secrets(
    text: str,
    *,
    home: Path | None = None,
    placeholder: str = "",
) -> tuple[str, bool]:
    """Return ``(scrubbed_text, had_secret)``. Default placeholder is empty (no UI leak)."""
    if not text:
        return text, False
    out = text
    hit = False
    for needle in _secret_needles(home):
        if needle and needle in out:
            out = out.replace(needle, placeholder)
            hit = True
    return out, hit


def redact_secrets_in_text(text: str, *, home: Path | None = None) -> str:
    """Strip vault secret substrings from text (empty replacement)."""
    scrubbed, _ = scrub_secrets(text, home=home, placeholder="")
    return scrubbed


def text_contains_vault_secret(text: str, *, home: Path | None = None) -> bool:
    if not text:
        return False
    return any(n and n in text for n in _secret_needles(home))


def get_entry(entry_id: str, home: Path | None = None, *, reveal: bool = False) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM vault_entries WHERE id = ?", (entry_id,)
        ).fetchone()
    if not row:
        raise NotFound(f"Vault entry not found: {entry_id}")
    out = _public_entry(row)
    if reveal:
        primary, secrets = _unpack_secrets(_dec(home, row["secret_blob"]))
        out["secret"] = primary
        out["secrets"] = secrets
    return out


def create_entry(
    *,
    label: str,
    kind: str,
    secret: str,
    origin: str = "",
    username: str = "",
    fields: list[dict[str, Any]] | None = None,
    public: dict[str, str] | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    label = (label or "").strip()
    kind = (kind or "secret").strip()
    if kind not in ("secret", "login", "credential"):
        raise ValidationError("kind must be secret|login|credential")
    if not label:
        raise ValidationError("label required")
    if not secret:
        raise ValidationError("secret required")
    entry_id = str(uuid.uuid4())
    now = _now()
    fields_json = json.dumps(fields or [], ensure_ascii=False)
    public_json = json.dumps(public or {}, ensure_ascii=False)
    with get_db(home) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(vault_entries)").fetchall()}
        if "fields_json" in cols and "public_json" in cols:
            conn.execute(
                """
                INSERT INTO vault_entries(
                  id, label, kind, origin, username, secret_blob,
                  fields_json, public_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    label,
                    kind,
                    (origin or "").strip(),
                    (username or "").strip(),
                    _enc(home, secret),
                    fields_json,
                    public_json,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO vault_entries(
                  id, label, kind, origin, username, secret_blob, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    label,
                    kind,
                    (origin or "").strip(),
                    (username or "").strip(),
                    _enc(home, secret),
                    now,
                    now,
                ),
            )
    entry = get_entry(entry_id, home=home)
    invalidate_secret_redact_cache(home)
    BUS.publish("vault.updated", {"entry": entry})
    return entry


def delete_entry(entry_id: str, home: Path | None = None) -> None:
    get_entry(entry_id, home=home)
    with get_db(home) as conn:
        conn.execute("DELETE FROM vault_grants WHERE entry_id = ?", (entry_id,))
        conn.execute("DELETE FROM vault_entries WHERE id = ?", (entry_id,))
    invalidate_secret_redact_cache(home)
    BUS.publish("vault.deleted", {"id": entry_id})


def list_entries_for_bot(bot: str, home: Path | None = None) -> list[dict[str, Any]]:
    """Metadata for entries this bot is granted (never includes secret values)."""
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT e.* FROM vault_entries e
            INNER JOIN vault_grants g ON g.entry_id = e.id
            WHERE g.bot = ?
            ORDER BY e.label COLLATE NOCASE ASC
            """,
            (bid,),
        ).fetchall()
    return [_public_entry(r) for r in rows]


def catalog_entries(home: Path | None = None) -> list[dict[str, Any]]:
    """All entry labels (for access requests) — never secret values."""
    return [
        {
            "id": e["id"],
            "label": e["label"],
            "kind": e["kind"],
            "origin": e["origin"],
            "username": e["username"],
        }
        for e in list_entries(home=home)
    ]


def list_grants(bot: str | None = None, home: Path | None = None) -> list[dict[str, Any]]:
    with get_db(home) as conn:
        if bot:
            rows = conn.execute(
                "SELECT * FROM vault_grants WHERE bot = ? ORDER BY granted_at",
                (_bot_id(bot, home=home),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vault_grants ORDER BY granted_at"
            ).fetchall()
    return [
        {
            "bot": _bot_slug(r["bot"], home=home),
            "bot_id": r["bot"],
            "entry_id": r["entry_id"],
            "granted_at": r["granted_at"],
        }
        for r in rows
    ]


def bot_has_grant(bot: str, entry_id: str, home: Path | None = None) -> bool:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT 1 FROM vault_grants WHERE bot = ? AND entry_id = ?",
            (_bot_id(bot, home=home), entry_id),
        ).fetchone()
    return row is not None


def grant(bot: str, entry_id: str, home: Path | None = None) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    get_entry(entry_id, home=home)
    bid = _bot_id(bot, home=home)
    now = _now()
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO vault_grants(bot, entry_id, granted_at)
            VALUES (?, ?, ?)
            ON CONFLICT(bot, entry_id) DO UPDATE SET granted_at = excluded.granted_at
            """,
            (bid, entry_id, now),
        )
    item = {"bot": bot, "bot_id": bid, "entry_id": entry_id, "granted_at": now}
    BUS.publish("vault.grant", item, bot=bot)
    return item


def revoke(bot: str, entry_id: str, home: Path | None = None) -> None:
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        conn.execute(
            "DELETE FROM vault_grants WHERE bot = ? AND entry_id = ?",
            (bid, entry_id),
        )
    BUS.publish("vault.revoke", {"bot": bot, "bot_id": bid, "entry_id": entry_id}, bot=bot)


def find_entry_for_origin(origin: str, home: Path | None = None) -> dict[str, Any] | None:
    origin = (origin or "").strip()
    if not origin:
        return None
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT * FROM vault_entries
            WHERE kind = 'login' AND origin = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (origin,),
        ).fetchone()
    return _public_entry(row) if row else None


def _request_public(row, *, home: Path | None = None) -> dict[str, Any]:
    try:
        keys = row.keys()
    except Exception:
        keys = []
    fields_raw = row["fields_json"] if "fields_json" in keys else "[]"
    try:
        fields = json.loads(fields_raw or "[]")
    except json.JSONDecodeError:
        fields = []
    bot_id = row["bot"]
    return {
        "id": row["id"],
        "bot_id": bot_id,
        "bot": _bot_slug(bot_id, home=home),
        "kind": row["kind"],
        "entry_id": row["entry_id"],
        "label": row["label"] or "",
        "origin": row["origin"] or "",
        "reason": row["reason"] or "",
        "fields": fields if isinstance(fields, list) else [],
        "state": row["state"],
        "message_id": row["message_id"],
        "result": json.loads(row["result_json"] or "{}"),
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def get_request(req_id: str, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM vault_requests WHERE id = ?", (req_id,)
        ).fetchone()
    if not row:
        raise NotFound(f"Vault request not found: {req_id}")
    return _request_public(row, home=home)


def create_request(
    bot: str,
    *,
    kind: str,
    reason: str = "",
    label: str = "",
    origin: str = "",
    entry_id: str | None = None,
    fields: list[dict[str, Any]] | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    bid = _bot_id(bot, home=home)
    kind = (kind or "").strip()
    if kind not in ("access", "login", "secret", "credential"):
        raise ValidationError("kind must be access|login|secret|credential")
    field_defs: list[dict[str, Any]] = []
    if kind == "access":
        if not entry_id:
            raise ValidationError("entry_id required for access")
        get_entry(entry_id, home=home)
        if bot_has_grant(bot, entry_id, home=home):
            # Already granted — synthesize resolved request
            req_id = str(uuid.uuid4())
            now = _now()
            result = {
                "ok": True,
                "already_granted": True,
                "entry_id": entry_id,
                "message": "Bot already has access to this vault entry. Secret value is not returned to the model.",
            }
            with get_db(home) as conn:
                conn.execute(
                    """
                    INSERT INTO vault_requests(
                      id, bot, kind, entry_id, label, origin, reason, state,
                      message_id, result_json, created_at, resolved_at
                    ) VALUES (?, ?, ?, ?, '', '', ?, 'approved', NULL, ?, ?, ?)
                    """,
                    (req_id, bid, kind, entry_id, reason or "", json.dumps(result), now, now),
                )
            return get_request(req_id, home=home)
    else:
        field_defs = normalize_fields(fields, kind=kind)

    req_id = str(uuid.uuid4())
    now = _now()
    fields_json = json.dumps(field_defs, ensure_ascii=False)
    # Chat card (no secrets)
    content = _request_card_text(
        kind, bot=bot, label=label, origin=origin, reason=reason, fields=field_defs
    )
    msg = chat_svc.create_message(
        bot,
        content,
        role="event",
        meta={
            "kind": "vault_request",
            "request_id": req_id,
            "request_kind": kind,
            "entry_id": entry_id,
            "label": label,
            "origin": origin,
            "reason": reason,
            "fields": field_defs,
            "state": "pending",
        },
        home=home,
    )
    with get_db(home) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(vault_requests)").fetchall()}
        if "fields_json" in cols:
            conn.execute(
                """
                INSERT INTO vault_requests(
                  id, bot, kind, entry_id, label, origin, reason, state,
                  message_id, result_json, fields_json, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, '{}', ?, ?, NULL)
                """,
                (
                    req_id,
                    bid,
                    kind,
                    entry_id,
                    label or "",
                    origin or "",
                    reason or "",
                    msg["id"],
                    fields_json,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO vault_requests(
                  id, bot, kind, entry_id, label, origin, reason, state,
                  message_id, result_json, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, '{}', ?, NULL)
                """,
                (
                    req_id,
                    bid,
                    kind,
                    entry_id,
                    label or "",
                    origin or "",
                    reason or "",
                    msg["id"],
                    now,
                ),
            )
    req = get_request(req_id, home=home)
    BUS.publish("vault.request", {"request": req}, bot=bot)
    # Agent tool is polling — show "waiting for the user" instead of "generating".
    try:
        bots_svc.patch_bot(bot, {"status": "waiting"}, home=home)
    except Exception:
        pass
    return req


def _collect_field_values(
    field_defs: list[dict[str, Any]],
    values: dict[str, Any] | None,
    *,
    secret: str | None = None,
    username: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Split submitted values into (secrets, public). Supports legacy username/secret."""
    values = dict(values or {})
    # Legacy shortcuts → map onto default field ids when present
    if username is not None and "username" not in values:
        values["username"] = username
    if secret is not None:
        if "password" in {f["id"] for f in field_defs} and "password" not in values:
            values["password"] = secret
        elif "secret" in {f["id"] for f in field_defs} and "secret" not in values:
            values["secret"] = secret
        elif len([f for f in field_defs if f["secret"]]) == 1:
            only = next(f["id"] for f in field_defs if f["secret"])
            values.setdefault(only, secret)

    secrets: dict[str, str] = {}
    public: dict[str, str] = {}
    for field in field_defs:
        fid = field["id"]
        raw = values.get(fid, "")
        val = "" if raw is None else str(raw)
        if field.get("required") and not val.strip():
            raise ValidationError(f"field required: {fid}")
        if field.get("secret"):
            if val:
                secrets[fid] = val
        else:
            public[fid] = val.strip()
    if not secrets:
        raise ValidationError("at least one secret value required")
    return secrets, public


def list_pending_for_bot(bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    bid = _bot_id(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT * FROM vault_requests
            WHERE bot = ? AND state = 'pending'
            ORDER BY created_at ASC
            """,
            (bid,),
        ).fetchall()
    return [_request_public(r, home=home) for r in rows]


def _human_redirect_result(note: str) -> dict[str, Any]:
    text = (note or "").strip()
    return {
        "ok": False,
        "cancelled": True,
        "human_redirect": True,
        "denied": False,
        "message": (
            "The user did not fill this vault form. They sent a chat message instead:\n"
            f"{text}\n\n"
            "Follow their instructions (for example: wait for a push / approve on another "
            "device, or use a different flow). This is NOT a hard refusal — continue the "
            "task with that guidance. Do not invent credentials or OTP codes."
        ),
    }


def _finalize_request(
    req: dict[str, Any],
    *,
    state: str,
    result: dict[str, Any],
    new_entry_id: str | None,
    home: Path | None,
) -> dict[str, Any]:
    """Persist resolution, update the chat card, resume or unstick the agent."""
    req_id = req["id"]
    now = _now()
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE vault_requests
            SET state = ?, entry_id = ?, result_json = ?, resolved_at = ?
            WHERE id = ?
            """,
            (state, new_entry_id, json.dumps(result), now, req_id),
        )
        row = conn.execute(
            "SELECT message_id FROM vault_requests WHERE id = ?", (req_id,)
        ).fetchone()
    message_id = row["message_id"] if row else None
    if message_id:
        chat_svc.update_message(
            req["bot"],
            message_id,
            _resolved_card_text(state, result),
            home=home,
            meta={
                "kind": "vault_request",
                "request_id": req_id,
                "request_kind": req["kind"],
                "entry_id": new_entry_id,
                "label": result.get("label") or req.get("label") or "",
                "origin": result.get("origin") or req.get("origin") or "",
                "reason": req.get("reason") or "",
                "fields": req.get("fields") or [],
                "state": state,
            },
        )
    out = get_request(req_id, home=home)
    BUS.publish("vault.request", {"request": out}, bot=req["bot"])
    try:
        _resume_or_unstick_after_vault(req["bot"], home=home)
    except Exception:
        pass
    return out


def cancel_pending_for_human_message(
    bot: str,
    content: str,
    *,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    """Cancel pending vault forms when the user writes in chat instead.

    The polling vault tool receives ``human_redirect`` guidance (not a hard deny).
    Returns the cancelled request payloads.
    """
    pending = list_pending_for_bot(bot, home=home)
    if not pending:
        return []
    result = _human_redirect_result(content)
    out: list[dict[str, Any]] = []
    for req in pending:
        out.append(
            _finalize_request(
                req,
                state="cancelled",
                result=result,
                new_entry_id=req.get("entry_id"),
                home=home,
            )
        )
    return out


def resolve_request(
    req_id: str,
    *,
    action: str,
    secret: str | None = None,
    username: str | None = None,
    label: str | None = None,
    origin: str | None = None,
    entry_id: str | None = None,
    values: dict[str, Any] | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    req = get_request(req_id, home=home)
    if req["state"] != "pending":
        return req
    action = (action or "").strip().lower()
    if action not in ("approve", "deny"):
        raise ValidationError("action must be approve|deny")

    result: dict[str, Any]
    new_entry_id = req.get("entry_id")
    bot = req["bot"]

    if action == "deny":
        # A chat message already typed while waiting beats a bare « Refuser »:
        # the user was correcting the flow (e.g. push 2FA), not rejecting help.
        queued = chat_svc.list_queued_user_messages(bot, home=home)
        if queued:
            note = "\n\n".join(
                (m.get("content") or "").strip() for m in queued if (m.get("content") or "").strip()
            )
            chat_svc.clear_queued_flags(
                bot, [m["id"] for m in queued], home=home
            )
            return _finalize_request(
                req,
                state="cancelled",
                result=_human_redirect_result(note),
                new_entry_id=new_entry_id,
                home=home,
            )
        result = {
            "ok": False,
            "denied": True,
            "message": "User denied the vault request. Do not invent credentials.",
        }
        return _finalize_request(
            req,
            state="denied",
            result=result,
            new_entry_id=new_entry_id,
            home=home,
        )

    else:
        kind = req["kind"]
        bot = req["bot"]
        if kind == "access":
            eid = entry_id or req.get("entry_id")
            if not eid:
                raise ValidationError("entry_id required")
            entry = get_entry(eid, home=home)
            grant(bot, eid, home=home)
            new_entry_id = eid
            result = {
                "ok": True,
                "granted": True,
                "entry_id": eid,
                "label": entry["label"],
                "origin": entry["origin"],
                "username": entry["username"],
                "public_keys": list((entry.get("public") or {}).keys()),
                "message": (
                    "Access granted. The secret value is stored in the vault and must never "
                    "be shown to the model. Use automation hooks that read via Autonomous."
                ),
            }
        else:
            field_defs = req.get("fields") or normalize_fields(None, kind=kind)
            secrets, public = _collect_field_values(
                field_defs, values, secret=secret, username=username
            )
            orig = (origin if origin is not None else req.get("origin") or "").strip()
            lab = (label if label is not None else req.get("label") or "").strip()
            if not lab:
                lab = orig or public.get("username") or next(iter(secrets.keys()), "Credential")
            user = public.get("username") or public.get("email") or public.get("user") or ""
            entry_kind = kind if kind in ("login", "secret", "credential") else "credential"
            if entry_kind == "credential":
                # Prefer login/secret when the shape matches defaults
                ids = {f["id"] for f in field_defs}
                if ids == {"username", "password"}:
                    entry_kind = "login"
                elif ids == {"secret"} or (len(secrets) == 1 and not public):
                    entry_kind = "secret"
            entry = create_entry(
                label=lab,
                kind=entry_kind,
                secret=_pack_secrets(secrets),
                origin=orig,
                username=user,
                fields=field_defs,
                public=public,
                home=home,
            )
            grant(bot, entry["id"], home=home)
            new_entry_id = entry["id"]
            result = {
                "ok": True,
                "granted": True,
                "entry_id": entry["id"],
                "label": entry["label"],
                "origin": entry["origin"],
                "username": entry["username"],
                "public_keys": list(public.keys()),
                "secret_keys": list(secrets.keys()),
                "message": (
                    "Credentials saved to the global vault and granted to this bot. "
                    "Secret field values were NOT returned to the model."
                ),
            }
        return _finalize_request(
            req,
            state="approved",
            result=result,
            new_entry_id=new_entry_id,
            home=home,
        )


def _resume_or_unstick_after_vault(bot: str, *, home=None) -> None:
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
    # Dead run: idle + carte Reprendre (session souvent morte pendant l’attente).
    chat_svc.mark_interrupted_after_wait(bot, home=home)


def _request_card_text(
    kind: str,
    *,
    bot: str,
    label: str,
    origin: str,
    reason: str,
    fields: list[dict[str, Any]] | None = None,
) -> str:
    if kind == "login":
        title = f"Demande de connexion — {origin or 'site'}"
    elif kind == "access":
        title = "Demande d’accès au coffre"
    elif kind == "credential":
        title = f"Demande d’identifiants — {label or origin or 'coffre'}"
    else:
        title = f"Demande de secret — {label or 'coffre'}"
    lines = [title, f"Bot: {bot}"]
    if label:
        lines.append(f"Label: {label}")
    if origin:
        lines.append(f"Origine: {origin}")
    if reason:
        lines.append(f"Motif: {reason}")
    if fields:
        names = ", ".join(f["label"] for f in fields)
        lines.append(f"Champs: {names}")
    lines.append("En attente de votre réponse (les secrets ne passeront pas par le LLM).")
    return "\n".join(lines)


def _resolved_card_text(state: str, result: dict[str, Any]) -> str:
    if state == "denied":
        return "Demande coffre refusée."
    if state == "cancelled" or result.get("human_redirect"):
        return (
            "Demande coffre annulée — l’utilisateur a écrit un message à la place "
            "(à suivre par l’agent, ce n’est pas un refus)."
        )
    parts = ["Demande coffre approuvée."]
    if result.get("label"):
        parts.append(f"Entrée: {result['label']}")
    if result.get("username"):
        parts.append(f"Utilisateur: {result['username']}")
    if result.get("origin"):
        parts.append(f"Origine: {result['origin']}")
    if result.get("secret_keys"):
        parts.append(f"Secrets enregistrés: {', '.join(result['secret_keys'])}")
    parts.append("Valeurs secrètes non exposées au modèle.")
    return "\n".join(parts)


_USER_SECRET_SCRUBBED = (
    "Ce message a été supprimé car un secret a été détecté."
)

_USER_SECRET_PROVIDER_ALERT = (
    "Attention : un secret a été transmis à votre fournisseur LLM. "
    "Changez-le dès que possible. Sur Autonomous, il a été effacé du message "
    "et n’est pas inclus dans l’historique de conversation."
)


_ABORT_ASSISTANT_RE = re.compile(
    r"(?is)^\s*(?:⚠️\s*)?(?:This operation was aborted|operation was aborted|"
    r"⏹\s*Stopped\.?)\s*$"
)


def report_user_secret_disclosure(
    bot: str,
    *,
    reason: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    """Agent flagged that the user pasted a secret into chat.

    Scrubs the latest user message (never store the secret), restores the
    original text to the composer via SSE, posts a provider warning card, and
    silently aborts the live Pi run. Do not pass the secret value here.
    """
    bots_svc.get_bot(bot, home=home)
    scrubbed_id = None
    restore_text = ""
    # Newest user bubble that is not already scrubbed.
    for msg in reversed(list(chat_svc.list_messages(bot, limit=40, home=home))):
        if msg.get("role") != "user":
            continue
        meta = dict(msg.get("meta") or {})
        if meta.get("secret_scrubbed"):
            continue
        content = msg.get("content") or ""
        restore_text = content
        # Strip any known vault secrets first, then replace the whole bubble
        # so unknown pasted secrets are not kept either.
        safe, _ = scrub_secrets(content, home=home, placeholder="")
        cleaned = _USER_SECRET_SCRUBBED
        if safe.strip() and safe.strip() != content.strip():
            # Keep non-secret remainder briefly? Prefer full replace for safety.
            cleaned = _USER_SECRET_SCRUBBED
        chat_svc.update_message(
            bot,
            msg["id"],
            cleaned,
            home=home,
            meta={
                **meta,
                "secret_scrubbed": True,
                "secret_scrub_reason": (reason or "").strip()[:200],
                "queued": False,
            },
        )
        scrubbed_id = msg["id"]
        break

    # Hide assistant narration after the scrubbed user msg, and any abort bubble.
    after = False
    for msg in chat_svc.list_messages(bot, limit=40, home=home):
        if scrubbed_id and msg.get("id") == scrubbed_id:
            after = True
            continue
        if msg.get("role") != "assistant":
            continue
        meta = dict(msg.get("meta") or {})
        if meta.get("hidden_prompt"):
            continue
        body = (msg.get("content") or "").strip()
        is_abort = bool(_ABORT_ASSISTANT_RE.match(body))
        if not ((scrubbed_id and after) or is_abort):
            continue
        chat_svc.update_message(
            bot,
            msg["id"],
            "",
            home=home,
            meta={
                **meta,
                "hidden_prompt": True,
                "secret_tool_narration_hidden": True,
                "streaming": False,
            },
        )

    alert = chat_svc.create_message(
        bot,
        _USER_SECRET_PROVIDER_ALERT,
        role="system",
        meta={"kind": "secret_provider_alert"},
        home=home,
    )

    # Stop the agent quietly — no « ⚠️ This operation was aborted » bubble.
    # Then kill the Pi process and scrub session jsonl so RAM + disk lose the secret.
    pi_scrub: dict[str, Any] = {"files": 0, "lines_changed": 0}
    try:
        from autonomous.services import agent as agent_svc

        agent_svc.mark_silent_abort(bot)
    except Exception:
        pass
    try:
        from autonomous.services.pi_rpc import MANAGER, scrub_pi_session_files

        MANAGER.abort(bot)
        MANAGER.stop(bot)
        if restore_text.strip():
            pi_scrub = scrub_pi_session_files(
                bot,
                leaked_text=restore_text,
                placeholder=_USER_SECRET_SCRUBBED,
                home=home,
            )
    except Exception:
        pass
    try:
        bots_svc.patch_bot(bot, {"status": "idle"}, home=home)
    except Exception:
        pass
    try:
        chat_svc.close_running_tools(
            bot,
            error="Run interrompu : secret détecté dans le message utilisateur.",
            home=home,
        )
    except Exception:
        pass

    BUS.publish(
        "vault.user_secret_report",
        {
            "bot": bot,
            "message_id": scrubbed_id,
            "alert_id": alert["id"],
            "restore_text": restore_text,
            "pi_scrub": pi_scrub,
        },
        bot=bot,
    )
    return {
        "ok": True,
        "scrubbed_message_id": scrubbed_id,
        "alert_id": alert["id"],
        "aborted": True,
        "restore_text": restore_text,
        "pi_scrub": pi_scrub,
        "message": (
            "User message scrubbed; provider warning shown; agent aborted; "
            "Pi session transcript scrubbed. Do not repeat the secret. Wait for the user."
        ),
    }
