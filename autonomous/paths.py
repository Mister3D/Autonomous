"""Resolve AUTONOMOUS_HOME and related paths."""

from __future__ import annotations

import os
from pathlib import Path


def default_home() -> Path:
    env = os.environ.get("AUTONOMOUS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    # Prefer ./data when running from a checkout, else ~/.autonomous
    cwd_data = Path.cwd() / "data"
    if (Path.cwd() / "pyproject.toml").exists() or cwd_data.exists():
        return cwd_data.resolve()
    return (Path.home() / ".autonomous").resolve()


def ensure_home(home: Path | None = None) -> Path:
    root = home or default_home()
    root.mkdir(parents=True, exist_ok=True)
    (root / "bots").mkdir(exist_ok=True)
    return root


def db_path(home: Path | None = None) -> Path:
    return ensure_home(home) / "db.sqlite"


def token_path(home: Path | None = None) -> Path:
    return ensure_home(home) / "token"


def secret_path(home: Path | None = None) -> Path:
    """Flask session signing key (distinct from the admin API Bearer in ``token``)."""
    return ensure_home(home) / "secret"


def serve_pid_path(home: Path | None = None) -> Path:
    return ensure_home(home) / "serve.pid"


def vite_watch_pid_path(home: Path | None = None) -> Path:
    return ensure_home(home) / "vite-watch.pid"


def password_path(home: Path | None = None) -> Path:
    return ensure_home(home) / "password.hash"


def bot_dir(name: str, home: Path | None = None) -> Path:
    path = ensure_home(home) / "bots" / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "home").mkdir(exist_ok=True)
    (path / "downloads").mkdir(exist_ok=True)
    return path


def bot_pi_dir(name: str, home: Path | None = None) -> Path:
    """Host-side Pi working directory for a bot (not inside the VM)."""
    path = bot_dir(name, home) / "pi"
    path.mkdir(parents=True, exist_ok=True)
    (path / "sessions").mkdir(exist_ok=True)
    return path
