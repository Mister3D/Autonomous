"""Mono-user authentication: password hash + session cookie + Bearer tokens.

Two Bearer kinds:
- Admin token (``data/token``): full API access (CLI / human).
- Bot token (``abt_…``, hash in ``bots.api_token_hash``): Pi session only —
  scoped to that bot's routes plus a short allowlist of shared agent APIs.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from autonomous.i18n import t
from autonomous.paths import password_path, token_path

BOT_TOKEN_PREFIX = "abt_"

# Shared (non-/bots/<name>/…) endpoints a bot token may call.
_SHARED_BOT_ROUTES: list[tuple[str, re.Pattern[str]]] = [
    ("GET", re.compile(r"^/api/v1/vault/catalog$")),
    ("GET", re.compile(r"^/api/v1/vault/entries$")),
    ("POST", re.compile(r"^/api/v1/vault/requests$")),
    ("GET", re.compile(r"^/api/v1/vault/requests/[^/]+$")),
    ("POST", re.compile(r"^/api/v1/vault/report-user-secret$")),
    ("GET", re.compile(r"^/api/v1/memory/entries$")),
    ("GET", re.compile(r"^/api/v1/memory/entries/[^/]+$")),
    ("GET", re.compile(r"^/api/v1/memory/search$")),
    ("POST", re.compile(r"^/api/v1/memory/proposals$")),
    ("POST", re.compile(r"^/api/v1/approvals/requests$")),
    ("GET", re.compile(r"^/api/v1/approvals/requests/[^/]+$")),
    ("POST", re.compile(r"^/api/v1/clarifies/requests$")),
    ("GET", re.compile(r"^/api/v1/clarifies/requests/[^/]+$")),
    ("GET", re.compile(r"^/api/v1/search/messages$")),
    ("POST", re.compile(r"^/api/v1/search/messages/nl$")),
    ("GET", re.compile(r"^/api/v1/devices/mcp/tools$")),
    ("POST", re.compile(r"^/api/v1/devices/mcp/call$")),
    ("POST", re.compile(r"^/api/v1/devices/notify$")),
]

# Paths where the resource id must belong to the authenticated bot.
_OWNED_REQUEST_PATHS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/api/v1/vault/requests/([^/]+)$"), "vault_requests"),
    (re.compile(r"^/api/v1/approvals/requests/([^/]+)$"), "approval_requests"),
    (re.compile(r"^/api/v1/clarifies/requests/([^/]+)$"), "clarify_requests"),
]

# Shared routes that require an explicit bot= (query or JSON) matching the token.
_REQUIRE_BOT_CLAIM = {
    ("GET", "/api/v1/vault/entries"),
    ("GET", "/api/v1/memory/entries"),
    ("GET", "/api/v1/memory/search"),
    ("GET", "/api/v1/search/messages"),
    ("GET", "/api/v1/devices/mcp/tools"),
}


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def write_token(home: Path, token: str | None = None) -> str:
    token = token or generate_token()
    path = token_path(home)
    path.write_text(token + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return token


def read_token(home: Path) -> str | None:
    path = token_path(home)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def set_password(home: Path, password: str) -> None:
    path = password_path(home)
    path.write_text(generate_password_hash(password), encoding="utf-8")
    os.chmod(path, 0o600)


def password_is_set(home: Path) -> bool:
    return password_path(home).exists()


def verify_password(home: Path, password: str) -> bool:
    path = password_path(home)
    if not path.exists():
        return False
    stored = path.read_text(encoding="utf-8").strip()
    return check_password_hash(stored, password)


def _bearer_raw() -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token or None


def _admin_bearer_ok(home: Path) -> bool:
    token = _bearer_raw()
    if not token or token.startswith(BOT_TOKEN_PREFIX):
        return False
    expected = read_token(home)
    return bool(expected) and secrets.compare_digest(token, expected)


def hash_bot_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_bot_api_token(bot: str, *, home: Path | None = None) -> str:
    """Rotate the bot API token; return plaintext once (for Pi env)."""
    from autonomous.db import get_db
    from autonomous.services import bots as bots_svc

    bots_svc.get_bot(bot, home=home)
    raw = BOT_TOKEN_PREFIX + secrets.token_urlsafe(32)
    digest = hash_bot_token(raw)
    now = datetime.now(timezone.utc).isoformat()
    with get_db(home) as conn:
        conn.execute(
            "UPDATE bots SET api_token_hash = ?, updated_at = ? WHERE name = ?",
            (digest, now, bot),
        )
    return raw


def bot_from_bearer(home: Path) -> str | None:
    """Return bot slug when Authorization is a valid ``abt_`` token."""
    token = _bearer_raw()
    if not token or not token.startswith(BOT_TOKEN_PREFIX):
        return None
    digest = hash_bot_token(token)
    from autonomous.db import get_db

    with get_db(home) as conn:
        row = conn.execute(
            "SELECT name FROM bots WHERE api_token_hash = ?",
            (digest,),
        ).fetchone()
    return str(row["name"]) if row else None


def is_authenticated(home: Path) -> bool:
    """Session cookie or admin Bearer — not a bot-scoped token."""
    if session.get("authenticated"):
        return True
    return _admin_bearer_ok(home)


def require_auth(view):
    """Decorator for plain Flask views (non-smorest)."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        home = g.home
        if not is_authenticated(home):
            return jsonify({"error": t("auth.required"), "code": "auth_required"}), 401
        return view(*args, **kwargs)

    return wrapped


def login_user() -> None:
    session["authenticated"] = True
    session.permanent = True


def logout_user() -> None:
    session.clear()


def _claim_bot(req) -> str | None:
    q = (req.args.get("bot") or "").strip()
    if q:
        return q
    if req.method in ("POST", "PUT", "PATCH"):
        data = req.get_json(silent=True) or {}
        if isinstance(data, dict):
            b = data.get("bot")
            if b is not None and str(b).strip():
                return str(b).strip()
    return None


def _shared_allowed(method: str, path: str) -> bool:
    for m, pattern in _SHARED_BOT_ROUTES:
        if m == method and pattern.match(path):
            return True
    return False


def _request_owned_by_bot(table: str, request_id: str, bot: str, home: Path) -> bool:
    """``table.bot`` stores the bot UUID; compare via decoded slug when possible."""
    from autonomous.db import get_db
    from autonomous.services import bots as bots_svc

    with get_db(home) as conn:
        row = conn.execute(
            f"SELECT bot FROM {table} WHERE id = ?",
            (request_id,),
        ).fetchone()
    if not row:
        return False
    stored = str(row["bot"] or "")
    if stored == bot:
        return True
    try:
        return bots_svc.bot_uuid(bot, home=home) == stored
    except Exception:
        return False


def bot_token_access_error(bot: str, home: Path):
    """If the current request is forbidden for this bot token, return (body, status)."""
    path = request.path
    method = request.method.upper()
    bot_root = f"/api/v1/bots/{bot}"

    if path == bot_root or path.startswith(bot_root + "/"):
        if method == "DELETE" and path == bot_root:
            return (
                {
                    "error": "Bot token cannot delete its bot",
                    "code": "bot_token_forbidden",
                },
                403,
            )
        return None

    if not _shared_allowed(method, path):
        return (
            {
                "error": "Bot token cannot access this endpoint",
                "code": "bot_token_forbidden",
            },
            403,
        )

    claim = _claim_bot(request)
    if (method, path) in _REQUIRE_BOT_CLAIM or path.startswith(
        "/api/v1/memory/entries/"
    ):
        # Detail GET /memory/entries/<key> also needs ?bot=
        if path.startswith("/api/v1/memory/entries/") and method == "GET":
            if not claim:
                return (
                    {
                        "error": "bot query parameter required",
                        "code": "bot_required",
                    },
                    400,
                )
        elif (method, path) in _REQUIRE_BOT_CLAIM and not claim:
            return (
                {
                    "error": "bot query/body parameter required",
                    "code": "bot_required",
                },
                400,
            )

    if claim and claim != bot:
        return (
            {
                "error": "Bot token cannot act as another bot",
                "code": "bot_token_forbidden",
            },
            403,
        )

    # Create endpoints must target this bot.
    if method == "POST" and path in (
        "/api/v1/vault/requests",
        "/api/v1/vault/report-user-secret",
        "/api/v1/memory/proposals",
        "/api/v1/approvals/requests",
        "/api/v1/clarifies/requests",
        "/api/v1/devices/mcp/call",
        "/api/v1/devices/notify",
        "/api/v1/search/messages/nl",
    ):
        if not claim:
            return (
                {
                    "error": "bot field required",
                    "code": "bot_required",
                },
                400,
            )

    for pattern, table in _OWNED_REQUEST_PATHS:
        m = pattern.match(path)
        if m and method == "GET":
            req_id = m.group(1)
            if not _request_owned_by_bot(table, req_id, bot, home):
                return (
                    {
                        "error": "Bot token cannot access this request",
                        "code": "bot_token_forbidden",
                    },
                    403,
                )
            break

    return None
