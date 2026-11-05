"""Authenticate WebSocket upgrades (session cookie or API Bearer)."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from werkzeug.http import parse_cookie

from autonomous import auth as auth_mod


def _bearer_ok(headers: dict[str, str], home: Path) -> bool:
    auth = headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return False
    token = auth[7:].strip()
    expected = auth_mod.read_token(home)
    return bool(expected) and bool(token) and secrets.compare_digest(token, expected)


def _session_ok(headers: dict[str, str], app: Any) -> bool:
    raw = headers.get("cookie") or ""
    if not raw:
        return False
    cookies = parse_cookie(raw)
    name = app.config.get("SESSION_COOKIE_NAME", "session")
    value = cookies.get(name)
    if not value:
        return False
    try:
        from flask.sessions import SecureCookieSessionInterface

        serializer = SecureCookieSessionInterface().get_signing_serializer(app)
        if serializer is None:
            return False
        data = serializer.loads(value)
    except Exception:
        return False
    return bool(isinstance(data, dict) and data.get("authenticated"))


def ws_authenticated(headers: dict[str, str], *, app: Any, home: Path) -> bool:
    """True when the upgrade carries a valid session cookie or API Bearer token."""
    if _bearer_ok(headers, home):
        return True
    return _session_ok(headers, app)
