"""Mono-user authentication: password hash + session cookie + Bearer token."""

from __future__ import annotations

import functools
import os
import secrets
from pathlib import Path

from flask import g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from autonomous.i18n import t
from autonomous.paths import password_path, token_path


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


def _bearer_ok(home: Path) -> bool:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    token = auth[7:].strip()
    expected = read_token(home)
    return bool(expected) and secrets.compare_digest(token, expected)


def is_authenticated(home: Path) -> bool:
    if session.get("authenticated"):
        return True
    return _bearer_ok(home)


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
