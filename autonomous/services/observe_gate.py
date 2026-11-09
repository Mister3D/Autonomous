"""DOM-before-eyes gate for ``vm_look`` / screen describe.

Keeps browser observation (snapshot / frames / text) ahead of expensive
multimodal ``vm_look`` calls, and blocks back-to-back looks without a fresh
DOM read in between.
"""

from __future__ import annotations

import threading
from pathlib import Path

_lock = threading.Lock()
# bot → how many successful DOM observes in this process
_observe_seq: dict[str, int] = {}
# bot → observe_seq value at the last accepted vm_look
_look_at_seq: dict[str, int] = {}

_REFUSE_NO_DOM = (
    "Call browser_snapshot first (no query) to read the DOM, then vm_look "
    "only if that was empty or inconclusive. "
    "browser_frames_snapshot / browser_text also count as a DOM observe."
)
_REFUSE_BACK_TO_BACK = (
    "Call browser_snapshot (or frames_snapshot / browser_text) again before "
    "another vm_look — no back-to-back looks without a fresh DOM read."
)


def reset_for_tests() -> None:
    with _lock:
        _observe_seq.clear()
        _look_at_seq.clear()


def mark_dom_observe(bot: str) -> None:
    """Record a successful browser_snapshot / frames_snapshot / browser_text."""
    key = (bot or "").strip()
    if not key:
        return
    with _lock:
        _observe_seq[key] = _observe_seq.get(key, 0) + 1


def note_vm_look(bot: str) -> None:
    """Remember that a look was accepted at the current observe generation."""
    key = (bot or "").strip()
    if not key:
        return
    with _lock:
        _look_at_seq[key] = _observe_seq.get(key, 0)


def refuse_vm_look_message(bot: str, *, home: Path | None = None) -> str | None:
    """Return a soft-refuse message, or ``None`` if ``vm_look`` may run."""
    key = (bot or "").strip()
    if not key:
        return None
    with _lock:
        obs = _observe_seq.get(key, 0)
        looked = _look_at_seq.get(key, 0)
    if obs > 0:
        if looked >= obs:
            return _REFUSE_BACK_TO_BACK
        return None
    # No DOM observe yet — require one when a screen desk is up (browser expected).
    # Do not rely on CDP tabs alone: VNC can show Chrome while CDP briefly fails,
    # which incorrectly skipped the gate.
    if not _screen_desk_up(key, home=home):
        return None
    return _REFUSE_NO_DOM


def _screen_desk_up(bot: str, *, home: Path | None) -> bool:
    try:
        from autonomous.services import bots as bots_svc

        row = bots_svc.get_bot(bot, home=home)
        desk = row.get("desk") or {}
        mode = str(desk.get("mode") or "").strip().lower()
        state = str(desk.get("state") or "").strip().lower()
        if mode == "screen" and state in ("running", "starting", "busy"):
            return True
    except Exception:
        pass
    return _chrome_reachable(bot, home=home)


def _chrome_reachable(bot: str, *, home: Path | None) -> bool:
    try:
        from autonomous.services import browser as browser_svc

        browser_svc.tabs(bot, home=home)
        return True
    except Exception:
        return False
