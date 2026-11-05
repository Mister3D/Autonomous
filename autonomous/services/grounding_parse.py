"""Parse UI-TARS structured action strings into geometry."""

from __future__ import annotations

import re
from typing import Any

# Matches the structured_outputs.regex used by the working curl example.
_BOX = (
    r"(?:<\|box_start\|>)?"
    r"\(([0-9]{1,4}),([0-9]{1,4})\)"
    r"(?:<\|box_end\|>)?"
)

_CLICK_RE = re.compile(
    rf"^(?:click|left_double|right_single)\(start_box='{_BOX}'\)$"
)
_DRAG_RE = re.compile(
    rf"^drag\(start_box='{_BOX}',\s*end_box='{_BOX}'\)$"
)
_SCROLL_RE = re.compile(
    rf"^scroll\(start_box='{_BOX}',\s*direction='(up|down|left|right)'\)$"
)
_FINISHED_RE = re.compile(r"^finished\((?:content='(?:[^'\\]|\\.)*')?\)$")
_WAIT_RE = re.compile(r"^wait\(\)$")


def parse_action(text: str) -> dict[str, Any]:
    """Return a structured action dict from model text (first line preferred)."""
    raw = (text or "").strip()
    # Take first non-empty line / strip markdown fences
    for line in raw.splitlines():
        line = line.strip().strip("`")
        if line:
            raw = line
            break
    raw = raw.strip()

    m = _CLICK_RE.match(raw)
    if m:
        kind = raw.split("(", 1)[0]
        return {
            "action": kind,
            "x": int(m.group(1)),
            "y": int(m.group(2)),
        }

    m = _DRAG_RE.match(raw)
    if m:
        return {
            "action": "drag",
            "x": int(m.group(1)),
            "y": int(m.group(2)),
            "x2": int(m.group(3)),
            "y2": int(m.group(4)),
        }

    m = _SCROLL_RE.match(raw)
    if m:
        return {
            "action": "scroll",
            "x": int(m.group(1)),
            "y": int(m.group(2)),
            "direction": m.group(3),
        }

    if _FINISHED_RE.match(raw) or raw.startswith("finished("):
        return {"action": "finished", "raw": raw}

    if _WAIT_RE.match(raw):
        return {"action": "wait"}

    return {"action": "unknown", "raw": raw}


# Same regex string as the working Hermes curl (for the API body).
STRUCTURED_REGEX = (
    r"(?:(?:click|left_double|right_single)\(start_box='(?:<\|box_start\|>)?"
    r"\([0-9]{1,4},[0-9]{1,4}\)(?:<\|box_end\|>)?'\)|"
    r"drag\(start_box='(?:<\|box_start\|>)?\([0-9]{1,4},[0-9]{1,4}\)(?:<\|box_end\|>)?',"
    r" end_box='(?:<\|box_start\|>)?\([0-9]{1,4},[0-9]{1,4}\)(?:<\|box_end\|>)?'\)|"
    r"scroll\(start_box='(?:<\|box_start\|>)?\([0-9]{1,4},[0-9]{1,4}\)(?:<\|box_end\|>)?',"
    r" direction='(?:up|down|left|right)'\)|"
    r"hotkey\(key='[^']*'\)|"
    r"type\(content='(?:[^'\\]|\\.)*'\)|"
    r"wait\(\)|"
    r"finished\((?:content='(?:[^'\\]|\\.)*')?\)|"
    r"call_user\(\))"
)

GROUNDER_SYSTEM = (
    "You are a GUI agent. Look at the screenshot and output exactly one action "
    "for the user instruction. Allowed actions: click, left_double, right_single, "
    "drag, scroll. Coordinates are pixels of the screenshot. "
    "Captcha / bot-check: classify the visible control first. "
    "If it is a slide / swipe / 'slide to verify' / drag handle on a track, "
    "you MUST output drag(start_box=handle, end_box=far end of the track in the "
    "slide direction) — never click. start_box = CENTER of the round handle on "
    "the track (not the instruction text above). end_box = CENTER of the target "
    "at the far end of the SAME track (same vertical row as the handle). "
    "Make the drag span the track only (~200–320px), not the whole screen. "
    "If it is a checkbox or single button (verify / Retry / Reload), "
    "output click. If the target is not visible, output finished()."
)
