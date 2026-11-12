"""vm_look is the page observation. It is not gated on a DOM read.

``mark_dom_observe`` / ``note_vm_look`` stay so older callers keep working.
``refuse_vm_look_message`` always allows the look: steering from the DOM
(snapshot coordinates, filled-char counts) is what stalled navigation.
"""

from __future__ import annotations

import threading
from pathlib import Path

_lock = threading.Lock()
# bot → how many successful DOM observes in this process
_observe_seq: dict[str, int] = {}
# bot → observe_seq value at the last accepted vm_look
_look_at_seq: dict[str, int] = {}

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
    """Always allow ``vm_look``. Navigation is visual, not DOM-first."""
    del bot, home
    return None
