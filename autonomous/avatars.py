"""Companion avatar catalog (mirrors avatar/characters/*/meta.json ready ones)."""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CHARS = _ROOT / "avatar" / "characters"

# Fallback if the avatar tree is missing at runtime.
_DEFAULT_IDS = (
    "axolotl",
    "capybara",
    "champignon",
    "chat",
    "crabe",
    "licorne",
    "ours",
    "pieuvre",
    "pingouin",
    "poussin",
    "raton-laveur",
    "renard",
)


def character_ids() -> list[str]:
    if not _CHARS.is_dir():
        return list(_DEFAULT_IDS)
    ids: list[str] = []
    for d in sorted(_CHARS.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("ready"):
            ids.append(meta.get("id") or d.name)
    return ids or list(_DEFAULT_IDS)


def pick_avatar(used: set[str] | None = None) -> str:
    """Prefer an unused ready character, else round-robin by count."""
    ids = character_ids()
    used = used or set()
    for aid in ids:
        if aid not in used:
            return aid
    n = len(used)
    return ids[n % len(ids)] if ids else "renard"


def is_valid_avatar(aid: str) -> bool:
    return (aid or "") in set(character_ids())
