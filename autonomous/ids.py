"""Opaque Autonomous resource ids (`autonomous-<uuid>`)."""

from __future__ import annotations

import uuid


def new_autonomous_id() -> str:
    """Docker VM name, Pi session id, etc. Mapping to a bot lives in SQLite."""
    return f"autonomous-{uuid.uuid4()}"
