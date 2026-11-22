"""Per-LLM-call rows: duration, tokens, full provider request/response JSON on disk.

Pi ``llm_trace`` writes the exact ``before_provider_request`` payload under
``bots/<bot>/pi/llm_turns/`` and opens a running card. ``message_end`` stores the
full assistant message JSON beside it. The UI fetches those files on expand.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.paths import bot_pi_dir
from autonomous.services import chat as chat_svc
from autonomous.services.errors import NotFound, ValidationError

_SAFE_REL = re.compile(r"^llm_turns/[A-Za-z0-9._-]+\.json$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _scrub(text: str, *, home: Path | None) -> str:
    if not text:
        return ""
    try:
        from autonomous.services import vault as vault_svc

        return vault_svc.redact_secrets_in_text(text, home=home)
    except Exception:
        return text


def _scrub_json(value: Any, *, home: Path | None) -> Any:
    if isinstance(value, str):
        return _scrub(value, home=home)
    if isinstance(value, list):
        return [_scrub_json(v, home=home) for v in value]
    if isinstance(value, dict):
        return {str(k): _scrub_json(v, home=home) for k, v in value.items()}
    return value


def turns_dir(bot: str, *, home: Path | None = None) -> Path:
    path = bot_pi_dir(bot, home) / "llm_turns"
    path.mkdir(parents=True, exist_ok=True)
    return path


def purge_turn_files(bot: str, *, home: Path | None = None) -> None:
    """Drop stored request/response JSON (chat clear / bot delete)."""
    root = bot_pi_dir(bot, home) / "llm_turns"
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def _resolve_pi_rel(bot: str, rel: str, *, home: Path | None) -> Path:
    raw = str(rel or "").strip().replace("\\", "/")
    if not _SAFE_REL.match(raw):
        raise ValidationError("Invalid llm_turns path", code="bad_llm_turn_path")
    root = bot_pi_dir(bot, home).resolve()
    path = (root / raw).resolve()
    if not str(path).startswith(str(root) + "/") and path != root:
        raise ValidationError("Invalid llm_turns path", code="bad_llm_turn_path")
    if path.parent.name != "llm_turns":
        raise ValidationError("Invalid llm_turns path", code="bad_llm_turn_path")
    return path


def _adopt_request_file(
    bot: str,
    msg_id: str,
    request_file: str,
    *,
    home: Path | None,
) -> str:
    """Move the extension-written payload next to the message id."""
    src = _resolve_pi_rel(bot, request_file, home=home)
    if not src.is_file():
        raise ValidationError("request_file not found", code="llm_turn_file_missing")
    dest = turns_dir(bot, home=home) / f"{msg_id}_request.json"
    if src.resolve() != dest.resolve():
        try:
            src.replace(dest)
        except OSError:
            dest.write_bytes(src.read_bytes())
            try:
                src.unlink()
            except OSError:
                pass
    return f"llm_turns/{dest.name}"


def _write_response_file(
    bot: str,
    msg_id: str,
    payload: Any,
    *,
    home: Path | None,
) -> str:
    dest = turns_dir(bot, home=home) / f"{msg_id}_response.json"
    cleaned = _scrub_json(payload, home=home)
    dest.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return f"llm_turns/{dest.name}"


def summarize_assistant_message(message: dict[str, Any] | None) -> str:
    """Short text hint for the tool row (full JSON lives on disk)."""
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content[:500]
    if not isinstance(content, list):
        return ""
    bits: list[str] = []
    for block in content:
        if isinstance(block, str):
            bits.append(block)
            continue
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "")
        if btype == "text":
            bits.append(str(block.get("text") or ""))
        elif btype in ("toolCall", "tool_use", "functionCall"):
            name = str(block.get("name") or block.get("toolName") or "tool")
            bits.append(f"[tool {name}]")
        elif btype == "thinking":
            bits.append("[thinking]")
    return "\n".join(b for b in bits if b).strip()[:800]


def open_turn(
    bot: str,
    *,
    request: str = "",
    request_kind: str | None = None,
    request_file: str | None = None,
    home: Path | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Insert a running llm_turn card. Prefer ``request_file`` from llm_trace."""
    from autonomous.services import bots as bots_svc

    bots_svc.get_bot(bot, home=home)
    kind = str(request_kind or "").strip() or None
    rel = str(request_file or "").strip() or None
    # Reuse a still-open turn, or one just sealed for tools (usage_pending).
    # A late llm_trace POST must not create a second card after desk/vault.
    existing = find_open_turn(bot, home=home) or find_usage_pending_turn(
        bot, home=home
    )
    if existing:
        meta = dict(existing.get("meta") or {})
        if rel:
            adopted = _adopt_request_file(bot, existing["id"], rel, home=home)
            meta["request_file"] = adopted
            meta["request_kind"] = kind or "provider"
            meta.pop("request", None)
        if model:
            meta["model"] = str(model)
        # Keep usage_pending / done — do not reopen as running after a tool seal.
        return chat_svc.update_message(
            bot,
            existing["id"],
            existing.get("content") or "LLM turn",
            home=home,
            meta=meta,
        )

    started = _now_iso()
    meta: dict[str, Any] = {
        "kind": "llm_turn",
        "status": "running",
        "started_at": started,
        "started_ms": int(time.time() * 1000),
    }
    if model:
        meta["model"] = str(model)

    # create_message generates its own id — adopt file after.
    msg = chat_svc.create_message(
        bot,
        "LLM turn",
        role="system",
        meta=meta,
        home=home,
    )
    meta = dict(msg.get("meta") or {})
    if rel:
        try:
            adopted = _adopt_request_file(bot, msg["id"], rel, home=home)
            meta["request_file"] = adopted
            meta["request_kind"] = kind or "provider"
        except Exception:
            meta["request_kind"] = kind or "provider"
            meta["request_error"] = "request_file missing"
    elif kind == "context" and request:
        # Legacy preview path — kept for older callers/tests.
        meta["request"] = _scrub(str(request)[:24_000], home=home)
        meta["request_kind"] = "context"
    return chat_svc.update_message(
        bot, msg["id"], msg.get("content") or "LLM turn", home=home, meta=meta
    )


def _iter_recent_system(bot: str, *, home: Path | None, limit: int = 24):
    from autonomous.db import get_db
    from autonomous.services import bots as bots_svc

    bots_svc.get_bot(bot, home=home)
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT id, content, meta_json, created_at FROM messages
            WHERE bot = ? AND conversation_id = 'main' AND role = 'system'
            ORDER BY created_at DESC LIMIT ?
            """,
            (bot, int(limit)),
        ).fetchall()
    for row in rows:
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except Exception:
            meta = {}
        yield {
            "id": row["id"],
            "content": row["content"] or "",
            "meta": meta if isinstance(meta, dict) else {},
            "created_at": row["created_at"],
        }


def find_open_turn(bot: str, *, home: Path | None = None) -> dict[str, Any] | None:
    for msg in _iter_recent_system(bot, home=home, limit=24):
        meta = msg.get("meta") or {}
        if meta.get("kind") == "llm_turn" and meta.get("status") == "running":
            return msg
    return None


def find_usage_pending_turn(
    bot: str, *, home: Path | None = None
) -> dict[str, Any] | None:
    for msg in _iter_recent_system(bot, home=home, limit=24):
        meta = msg.get("meta") or {}
        if meta.get("kind") == "llm_turn" and meta.get("usage_pending"):
            return msg
    return None


def seal_turn_for_tools(
    bot: str,
    *,
    tool_name: str = "",
    home: Path | None = None,
) -> dict[str, Any] | None:
    open_msg = find_open_turn(bot, home=home)
    if not open_msg:
        return None
    now_ms = int(time.time() * 1000)
    meta = dict(open_msg.get("meta") or {})
    started_ms = meta.get("started_ms")
    try:
        started_ms = int(started_ms) if started_ms is not None else None
    except (TypeError, ValueError):
        started_ms = None
    if started_ms is not None:
        meta["duration_ms"] = max(0, now_ms - started_ms)
    name = str(tool_name or "").strip()
    hint = f"[tool {name}]" if name else "[tools]"
    if not (meta.get("response") or "").strip():
        meta["response"] = hint
    meta.update(
        {
            "kind": "llm_turn",
            "status": "done",
            "usage_pending": True,
        }
    )
    return chat_svc.update_message(
        bot,
        open_msg["id"],
        open_msg.get("content") or "LLM turn",
        home=home,
        meta=meta,
    )


def finalize_turn(
    bot: str,
    *,
    response: str = "",
    response_json: Any = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    stop_reason: str | None = None,
    error: str | None = None,
    model: str | None = None,
    request: str | None = None,
    home: Path | None = None,
) -> dict[str, Any] | None:
    """Seal the open card and persist the full assistant message JSON."""
    now_ms = int(time.time() * 1000)
    open_msg = find_open_turn(bot, home=home) or find_usage_pending_turn(
        bot, home=home
    )
    resp_hint = _scrub(str(response or "")[:800], home=home)

    if open_msg:
        meta = dict(open_msg.get("meta") or {})
        started_ms = meta.get("started_ms")
        try:
            started_ms = int(started_ms) if started_ms is not None else None
        except (TypeError, ValueError):
            started_ms = None
        if meta.get("duration_ms") is None and started_ms is not None:
            meta["duration_ms"] = max(0, now_ms - started_ms)
        meta.update(
            {
                "kind": "llm_turn",
                "status": "error" if error else "done",
                "tokens_in": int(tokens_in or 0),
                "tokens_out": int(tokens_out or 0),
            }
        )
        meta.pop("usage_pending", None)
        if response_json is not None:
            try:
                meta["response_file"] = _write_response_file(
                    bot, open_msg["id"], response_json, home=home
                )
            except Exception:
                meta["response_error"] = "response_file write failed"
        if resp_hint:
            meta["response"] = resp_hint
        if stop_reason:
            meta["stop_reason"] = str(stop_reason)
        if error:
            meta["error"] = _scrub(str(error)[:500], home=home)
        if model:
            meta["model"] = str(model)
        if request is not None and not meta.get("request_file"):
            meta["request"] = _scrub(str(request)[:24_000], home=home)
        return chat_svc.update_message(
            bot,
            open_msg["id"],
            open_msg.get("content") or "LLM turn",
            home=home,
            meta=meta,
        )

    meta = {
        "kind": "llm_turn",
        "status": "error" if error else "done",
        "started_at": _now_iso(),
        "started_ms": now_ms,
        "duration_ms": 0,
        "response": resp_hint,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
    }
    if stop_reason:
        meta["stop_reason"] = str(stop_reason)
    if error:
        meta["error"] = _scrub(str(error)[:500], home=home)
    if model:
        meta["model"] = str(model)
    msg = chat_svc.create_message(
        bot, "LLM turn", role="system", meta=meta, home=home
    )
    if response_json is not None:
        try:
            meta["response_file"] = _write_response_file(
                bot, msg["id"], response_json, home=home
            )
            chat_svc.update_message(
                bot, msg["id"], msg.get("content") or "LLM turn", home=home, meta=meta
            )
        except Exception:
            pass
    return msg


def close_running_turns(
    bot: str, *, home: Path | None = None, error: str | None = None
) -> int:
    n = 0
    now_ms = int(time.time() * 1000)
    for msg in _iter_recent_system(bot, home=home, limit=40):
        meta = dict(msg.get("meta") or {})
        if meta.get("kind") != "llm_turn" or meta.get("status") != "running":
            continue
        started_ms = meta.get("started_ms")
        try:
            started_ms = int(started_ms) if started_ms is not None else None
        except (TypeError, ValueError):
            started_ms = None
        if started_ms is not None:
            meta["duration_ms"] = max(0, now_ms - started_ms)
        meta["status"] = "error" if error else "aborted"
        if error:
            meta["error"] = _scrub(str(error)[:500], home=home)
        chat_svc.update_message(
            bot, msg["id"], msg.get("content") or "LLM turn", home=home, meta=meta
        )
        n += 1
    return n


def get_payload(
    bot: str,
    message_id: str,
    *,
    side: str,
    home: Path | None = None,
) -> Any:
    """Load request or response JSON for an llm_turn message (vault-scrubbed)."""
    from autonomous.db import get_db
    from autonomous.services import bots as bots_svc

    bots_svc.get_bot(bot, home=home)
    side_key = "request" if side == "request" else "response"
    if side not in ("request", "response"):
        raise ValidationError("side must be request or response", code="bad_side")
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT meta_json FROM messages WHERE id = ? AND bot = ?",
            (message_id, bot),
        ).fetchone()
    if not row:
        raise NotFound("Message not found", code="not_found")
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except Exception:
        meta = {}
    if meta.get("kind") != "llm_turn":
        raise NotFound("Not an llm_turn message", code="not_llm_turn")
    rel = meta.get(f"{side_key}_file")
    if rel:
        path = _resolve_pi_rel(bot, str(rel), home=home)
        if not path.is_file():
            raise NotFound("Payload file missing", code="llm_turn_file_missing")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValidationError(
                f"Invalid payload JSON: {exc}", code="bad_llm_turn_json"
            ) from exc
        return _scrub_json(data, home=home)
    # Legacy inline text preview.
    inline = meta.get(side_key)
    if inline is None or inline == "":
        raise NotFound("No payload stored", code="llm_turn_empty")
    return {"_legacy_text": True, "text": inline}
