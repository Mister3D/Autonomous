"""In-process cron ticker (daemon thread in `serve`).

Expressions are stored and matched in UTC. Creation input is host-local.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from autonomous.services import bot_events as events_svc

log = logging.getLogger("autonomous.scheduler")

_TICK_SEC = 30.0
_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_home: Path | None = None


def tick_once(*, home: Path | None = None) -> int:
    """Fire due schedules + auto-sleep idle desks. Returns schedules fired."""
    h = home if home is not None else _home
    if h is None:
        return 0
    fired = 0
    try:
        due = events_svc.due_schedules(home=h)
    except Exception:
        log.exception("scheduler: list due failed")
        due = []
    for sched in due:
        try:
            # Re-check: may have been disabled/deleted
            fresh = events_svc.get_schedule(sched["bot"], sched["id"], home=h)
            if not fresh.get("enabled"):
                continue
            events_svc.fire_schedule(fresh, home=h)
            fired += 1
        except Exception:
            log.exception(
                "scheduler: fire failed bot=%s id=%s",
                sched.get("bot"),
                sched.get("id"),
            )
    try:
        from autonomous.services import desk as desk_svc

        desk_svc.tick_auto_sleep(home=h)
    except Exception:
        log.exception("scheduler: auto-sleep tick failed")
    try:
        from autonomous.services import agent as agent_svc

        agent_svc.recover_silent_busy_runs(home=h)
    except Exception:
        log.exception("scheduler: silent-busy recover failed")
    return fired


def _loop() -> None:
    # Immediate catch-up on start
    tick_once()
    while not _stop.wait(timeout=_TICK_SEC):
        tick_once()


def start(home: Path) -> None:
    """Start daemon scheduler if not already running."""
    global _thread, _home
    with _lock:
        _home = home
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(
            target=_loop, name="autonomous-scheduler", daemon=True
        )
        _thread.start()
        log.info("scheduler started (UTC storage, tick=%ss)", int(_TICK_SEC))


def stop() -> None:
    global _thread
    with _lock:
        _stop.set()
        t = _thread
        _thread = None
    if t is not None and t.is_alive():
        t.join(timeout=2.0)
