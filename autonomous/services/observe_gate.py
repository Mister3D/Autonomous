"""Keep navigation on the snapshot when it already lists the control.

``vm_look`` and ``vm_ground`` are slow vision calls. A fresh ``browser_snapshot``
already carries ``screen=`` points, so those calls answer from that read.
Vision still runs when the read is empty, or when the control is not in it
(canvas, native dialog, drawn widget).
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

_lock = threading.Lock()
# bot → how many successful DOM observes in this process
_observe_seq: dict[str, int] = {}
# bot → observe_seq value at the last accepted vm_look
_look_at_seq: dict[str, int] = {}
# bot → monotonic time of the last pointer / key gesture
_gesture_at: dict[str, float] = {}
# bot → last snapshot/frames read
_reads: dict[str, dict[str, Any]] = {}

_STOP = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "your",
        "button", "link", "field", "icon", "page", "click", "press", "prefer",
        "action", "left", "right", "single", "double", "next", "then",
        "bouton", "champ", "lien", "icone", "cliquer",
    }
)


def reset_for_tests() -> None:
    with _lock:
        _observe_seq.clear()
        _look_at_seq.clear()
        _gesture_at.clear()
        _reads.clear()


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


def note_gesture(bot: str) -> None:
    """A real pointer or key just landed. The previous read is now stale."""
    key = (bot or "").strip()
    if not key:
        return
    with _lock:
        _gesture_at[key] = time.monotonic()


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", text or "")
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()


def _tokens(text: str) -> list[str]:
    return [tok for tok in _fold(text).split() if len(tok) >= 4 and tok not in _STOP]


def _point(el: dict[str, Any]) -> dict[str, Any] | None:
    screen = el.get("screen") or el.get("center_screen") or {}
    if not isinstance(screen, dict):
        return None
    x, y = screen.get("x"), screen.get("y")
    if x is None or y is None:
        return None
    if el.get("in_viewport") is False:
        return None
    if el.get("occluded_by"):
        return None
    return {
        "tag": str(el.get("tag") or ""),
        "type": str(el.get("type") or "").lower(),
        "role": str(el.get("role") or ""),
        "name": str(el.get("name") or "")[:80],
        "text": str(el.get("text") or "")[:80],
        "x": int(x),
        "y": int(y),
    }


def remember_browser_read(bot: str, payload: dict[str, Any]) -> None:
    """Store the controls a snapshot or frames_snapshot just returned."""
    key = (bot or "").strip()
    if not key or not isinstance(payload, dict):
        return
    elements: list[dict[str, Any]] = []
    overlays: list[dict[str, Any]] = []
    for el in payload.get("elements") or []:
        if isinstance(el, dict):
            point = _point(el)
            if point:
                elements.append(point)
    for frame in payload.get("frames") or []:
        if not isinstance(frame, dict):
            continue
        for el in frame.get("elements") or []:
            if isinstance(el, dict):
                point = _point(el)
                if point:
                    elements.append(point)
    for overlay in payload.get("overlays") or []:
        if not isinstance(overlay, dict):
            continue
        for el in overlay.get("controls") or []:
            if isinstance(el, dict):
                point = _point(el)
                if point:
                    overlays.append(point)
    with _lock:
        _reads[key] = {
            "at": time.monotonic(),
            "elements": elements,
            "overlays": overlays,
        }


def _read(bot: str) -> dict[str, Any] | None:
    with _lock:
        snap = _reads.get((bot or "").strip())
        if not snap:
            return None
        gestured = _gesture_at.get((bot or "").strip(), 0.0)
        return {
            "stale": gestured > float(snap["at"]),
            "elements": list(snap["elements"]),
            "overlays": list(snap["overlays"]),
        }


def _lines(controls: list[dict[str, Any]], limit: int = 12) -> str:
    rows = []
    for el in controls[:limit]:
        label = el["text"] or el["name"] or el["tag"] or "control"
        rows.append(f'- {el["tag"] or "control"} "{label}" screen={el["x"]},{el["y"]}')
    return "\n".join(rows)


def _token_match(instruction: str, controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    want = _tokens(instruction)
    folded = _fold(instruction)
    if not want and not folded:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for el in controls:
        blob = _fold(" ".join((el["text"], el["name"], el["role"], el["type"])))
        if len(blob) < 3:
            continue
        have = _tokens(blob)
        overlap = 0
        for tok in have:
            if tok in want or tok in folded:
                overlap += len(tok)
                continue
            for other in want:
                if len(tok) >= 5 and len(other) >= 5 and (
                    tok.startswith(other) or other.startswith(tok)
                ):
                    overlap += min(len(tok), len(other))
                    break
        if overlap:
            scored.append((overlap, el))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return []
    best = scored[0][0]
    return [el for score, el in scored if best - score < 3]


def _unique_field(controls: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    if kind == "password":
        found = [
            el for el in controls
            if el["tag"] == "input" and el["type"] == "password"
        ]
    else:
        found = []
        for el in controls:
            if el["tag"] not in ("input", "textarea"):
                continue
            if el["type"] in ("password", "submit", "button", "checkbox", "radio", "hidden"):
                continue
            blob = _fold(" ".join((el["text"], el["name"], el["type"])))
            if any(k in blob for k in ("mail", "user", "login", "identifiant", "email")):
                found.append(el)
            elif el["type"] in ("email", "text", "") and el["tag"] == "input":
                found.append(el)
        # Prefer a named identity field over every text input on the page.
        named = [
            el for el in found
            if any(
                k in _fold(" ".join((el["text"], el["name"], el["type"])))
                for k in ("mail", "user", "login", "identifiant", "email")
            )
        ]
        if named:
            found = named
    if len(found) == 1:
        return found[0]
    return None


def _click_result(el: dict[str, Any], instruction: str) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "ok",
        "action": "click",
        "x": el["x"],
        "y": el["y"],
        "source": "snapshot",
        "instruction": instruction,
        "loops": [],
    }


def _list_result(status: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": status,
        "source": "snapshot",
        "error": error,
        "loops": [],
    }


def shortcut_ground(
    bot: str,
    instruction: str,
    *,
    action_hint: str | None = None,
) -> dict[str, Any] | None:
    """Answer ``vm_ground`` from the last read, or None to run vision.

    A drag hint is never shortcut: a slider needs a track, which vision or
    the snapshot's own slider line provides.
    """
    hint = (action_hint or "").strip().lower()
    if hint in ("drag",):
        return None
    snap = _read(bot)
    if snap is None:
        return _list_result(
            "no_snapshot",
            "Call browser_snapshot first. vm_ground only when that read does "
            "not list the control. If browser_snapshot fails, use vm_look.",
        )
    if snap["stale"]:
        return _list_result(
            "stale",
            "The last snapshot is older than the last click or key. "
            "Call browser_snapshot, then vm_click its screen= point. "
            "Do not vm_ground a control that read will list.",
        )
    overlays = snap["overlays"]
    if overlays:
        matched = _token_match(instruction, overlays)
        if len(matched) == 1:
            return _click_result(matched[0], instruction)
        listed = matched or overlays
        return _list_result(
            "overlay",
            "BLOCKING OVERLAY. vm_click one of these screen points, "
            "then browser_snapshot again:\n" + _lines(listed),
        )
    controls = snap["elements"]
    if not controls:
        return None
    folded = _fold(instruction)
    if any(k in folded for k in ("password", "mot de passe", "passwd")):
        field = _unique_field(controls, "password")
        if field:
            return _click_result(field, instruction)
    if any(k in folded for k in ("username", "user name", "email", "e mail", "identifiant")):
        field = _unique_field(controls, "username")
        if field:
            return _click_result(field, instruction)
    matched = _token_match(instruction, controls)
    if len(matched) == 1:
        return _click_result(matched[0], instruction)
    if len(matched) > 1:
        return _list_result(
            "ambiguous",
            "Several controls match. vm_click the right screen= point:\n" + _lines(matched),
        )
    return None


def refuse_vm_look_message(bot: str, *, home: Path | None = None) -> str | None:
    """Skip vision when a snapshot already lists what to click."""
    del home
    snap = _read(bot)
    if snap is None:
        return None
    if snap["stale"]:
        return (
            "The page changed since the snapshot. Call browser_snapshot "
            "to read the new controls. vm_look only if that snapshot is empty."
        )
    if snap["overlays"]:
        return (
            "browser_snapshot already lists a blocking overlay. "
            "vm_click one of these screen points:\n" + _lines(snap["overlays"])
        )
    if snap["elements"]:
        return (
            "browser_snapshot already lists the controls. "
            "vm_click the matching screen= point. Do not vm_look.\n"
            + _lines(snap["elements"])
        )
    return None
