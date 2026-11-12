"""``browser_navigate`` is only the first open.

Once Chrome is already on an http(s) page, changing the URL is refused.
After that the agent clicks what it sees, types a Google search in the
address bar, or clicks the refresh icon. The first open still only accepts
a URL the user wrote, or that site's homepage — never a guessed path.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from autonomous.services.errors import ValidationError

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_REFUSE_INVENTED = (
    "Refusing an invented URL. The first browser_navigate only accepts a URL "
    "the user wrote, or that site's homepage. Do not invent a path."
)
_REFUSE_ALREADY_OPEN = (
    "browser_navigate is only for the first open. The browser is already on "
    "a page, so this URL change is refused. Take the shortest path: if the "
    "target is visible, click it. For a Google search, click the address bar "
    "and type the query, then Enter. To reload, click the refresh icon. "
    "Do not type a site URL."
)
_LOCATION_JS = "location.href"


def normalize_url(url: str) -> str | None:
    """Canonical http(s) URL without fragment. ``None`` if it is not one."""
    raw = (url or "").strip().rstrip(".,;:)")
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower()
    if parts.scheme.lower() == "http" and host.endswith(":80"):
        host = host[:-3]
    if parts.scheme.lower() == "https" and host.endswith(":443"):
        host = host[:-4]
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def origin_root(url: str) -> str | None:
    norm = normalize_url(url)
    if not norm:
        return None
    parts = urlsplit(norm)
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def urls_in_text(text: str) -> set[str]:
    found: set[str] = set()
    for match in _URL_RE.findall(text or ""):
        norm = normalize_url(match)
        if norm:
            found.add(norm)
    return found


def user_written_urls(bot: str, *, home: Path | None = None) -> set[str]:
    """URLs that appear in user messages (chat, webhook). Not assistant text."""
    from autonomous.services import chat as chat_svc

    found: set[str] = set()
    try:
        messages = chat_svc.list_messages(bot, limit=200, home=home)
    except Exception:
        return found
    for message in messages:
        if (message.get("role") or "") != "user":
            continue
        found |= urls_in_text(str(message.get("content") or ""))
    return found


def current_location(bot: str, *, home: Path | None = None) -> str:
    """Best-effort current tab URL. Empty when Chrome is not answering."""
    from autonomous.services import browser as browser_svc

    try:
        data = browser_svc.evaluate(bot, _LOCATION_JS, home=home)
    except Exception:
        return ""
    value = data.get("value")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        nested = str(value.get("url") or "").strip()
        if nested:
            return nested
    return str(data.get("url") or "").strip()


def browser_already_open(location: str) -> bool:
    """True when the tab is already a real http(s) page."""
    raw = (location or "").strip().lower()
    if not raw:
        return False
    if raw.startswith(("about:", "chrome:", "edge:", "chrome-extension:")):
        return False
    return normalize_url(location) is not None


def first_open_urls(bot: str, *, home: Path | None = None) -> set[str]:
    """User-written URLs plus each of those sites' homepages."""
    allowed = user_written_urls(bot, home=home)
    for url in list(allowed):
        root = origin_root(url)
        if root:
            allowed.add(root)
    return allowed


def assert_seen_url(bot: str, url: str, *, home: Path | None = None) -> str:
    """Allow a first open onto a user URL. Refuse any later URL change."""
    norm = normalize_url(url)
    if not norm:
        raise ValidationError("url must be an absolute http(s) URL", code="invalid_url")
    if browser_already_open(current_location(bot, home=home)):
        raise ValidationError(_REFUSE_ALREADY_OPEN, code="url_change")
    if norm not in first_open_urls(bot, home=home):
        raise ValidationError(_REFUSE_INVENTED, code="invented_url")
    return norm
