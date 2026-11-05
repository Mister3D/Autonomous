"""Client IP for rate limits — only trust X-Forwarded-For behind a known proxy."""

from __future__ import annotations

import os

from flask import Request


def trust_proxy() -> bool:
    return os.environ.get("AUTONOMOUS_TRUST_PROXY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def client_ip(req: Request) -> str:
    """Return the client address used for throttling.

    By default uses ``remote_addr`` only. When ``AUTONOMOUS_TRUST_PROXY=1``,
    takes the first hop of ``X-Forwarded-For`` (set this only if a reverse
    proxy overwrites XFF and clients cannot reach the app directly).
    """
    remote = (req.remote_addr or "?").strip() or "?"
    if not trust_proxy():
        return remote
    xff = (req.headers.get("X-Forwarded-For") or "").strip()
    if not xff:
        return remote
    return xff.split(",")[0].strip() or remote
