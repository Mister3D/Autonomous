"""Simple JSON-based translations (EN primary, FR secondary)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"
_DEFAULT = "en"


@lru_cache(maxsize=8)
def _load(lang: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = _LOCALES_DIR / f"{_DEFAULT}.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    lang = lang or _DEFAULT
    catalog = _load(lang)
    if key not in catalog and lang != _DEFAULT:
        catalog = _load(_DEFAULT)
    text = catalog.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text
