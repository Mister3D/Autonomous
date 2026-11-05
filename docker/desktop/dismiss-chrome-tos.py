#!/usr/bin/env python3
"""Dismiss Chrome « Conditions d'utilisation supplémentaires » if it appears.

Native modal — not in the page DOM — so CDP alone cannot click Accepter.
Uses xdotool/wmctrl against the XFCE display. Idempotent / no-op if absent.
"""

from __future__ import annotations

import os
import subprocess
import time

DISPLAY = os.environ.get("DISPLAY", ":1")
TITLES = (
    "Conditions d'utilisation",
    "Additional Terms of Service",
    "Terms of Service",
)


def env() -> dict[str, str]:
    e = os.environ.copy()
    e["DISPLAY"] = DISPLAY
    return e


def run(cmd: list[str], timeout: float = 3.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env(),
        check=False,
    )


def find_window_ids() -> list[str]:
    ids: list[str] = []
    for title in TITLES:
        r = run(["xdotool", "search", "--name", title])
        for line in (r.stdout or "").splitlines():
            wid = line.strip()
            if wid.isdigit() and wid not in ids:
                ids.append(wid)
    return ids


def click_accept(wid: str) -> bool:
    # Focus, then Tab toward the primary (right) Accepter button and activate.
    run(["xdotool", "windowactivate", "--sync", wid])
    time.sleep(0.15)
    # Dialog layout: Annuler (left) · Accepter (right, default). End → Accepter.
    run(["xdotool", "key", "--window", wid, "End"])
    time.sleep(0.05)
    run(["xdotool", "key", "--window", wid, "Return"])
    time.sleep(0.2)
    # Fallback: click lower-right of the dialog (Accepter).
    geo = run(["xdotool", "getwindowgeometry", "--shell", wid])
    vals: dict[str, int] = {}
    for line in (geo.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            try:
                vals[k] = int(v)
            except ValueError:
                pass
    w, h = vals.get("WIDTH", 0), vals.get("HEIGHT", 0)
    if w > 40 and h > 40:
        x = max(10, w - 90)
        y = max(10, h - 28)
        run(["xdotool", "mousemove", "--window", wid, str(x), str(y), "click", "1"])
        return True
    return False


def main() -> int:
    deadline = time.time() + 12.0
    while time.time() < deadline:
        ids = find_window_ids()
        if not ids:
            time.sleep(0.4)
            continue
        for wid in ids:
            try:
                click_accept(wid)
            except Exception:
                pass
        time.sleep(0.5)
        if not find_window_ids():
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
