"""VNC pointer / keyboard injection into a running bot desk (no LLM secrets)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from autonomous.paths import bot_dir
from autonomous.services import bots as bots_svc
from autonomous.services.errors import AutonomousError, ValidationError

_WORKER = Path(__file__).resolve().parent / "vnc_type_worker.py"
_CONTAINER_WORKER = "/home/autonomous/workspace/.autonomous/_vnc_type_worker.py"


def _chown_bot(path: Path) -> None:
    try:
        os.chown(path, 1000, 1000)
    except OSError:
        pass


def _ensure_desk(bot: str, *, home: Path | None) -> None:
    from autonomous.services import desk as desk_svc

    desk_svc.ensure_awake(bot, home=home)
    if not _WORKER.is_file():
        raise AutonomousError("VNC worker missing on host", code="internal")


def _copy_worker(bot: str, *, home: Path | None) -> None:
    host_autonomous = bot_dir(bot, home) / "home" / ".autonomous"
    host_autonomous.mkdir(parents=True, exist_ok=True)
    _chown_bot(host_autonomous)
    host_worker = host_autonomous / "_vnc_type_worker.py"
    shutil.copyfile(_WORKER, host_worker)
    _chown_bot(host_worker)


def _run_worker(
    bot: str,
    args: list[str],
    *,
    stdin: bytes | None = None,
    home: Path | None = None,
) -> str:
    from autonomous.services import desk as desk_svc

    _ensure_desk(bot, home=home)
    _copy_worker(bot, home=home)
    cmd = [
        "docker",
        "exec",
        "-i" if stdin is not None else "",
        "-u",
        "autonomous",
        "-e",
        "HOME=/home/autonomous",
        desk_svc.container_name(bot, home=home),
        "python3",
        _CONTAINER_WORKER,
        *args,
    ]
    cmd = [c for c in cmd if c != ""]
    try:
        completed = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AutonomousError("docker CLI not found on host") from exc
    except subprocess.TimeoutExpired as exc:
        raise AutonomousError("Desk input timed out", code="timeout") from exc
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or b"").decode(
            "utf-8", errors="replace"
        ).strip()
        raise AutonomousError(
            f"Desk input failed: {err[:300]}",
            code="desk_input_failed",
        )
    return (completed.stdout or b"").decode("utf-8", errors="replace").strip()


def click(
    bot: str,
    x: int,
    y: int,
    *,
    button: str = "left",
    home: Path | None = None,
) -> dict[str, Any]:
    x, y = int(x), int(y)
    if x < 0 or y < 0:
        raise ValidationError("x/y must be >= 0")
    button = (button or "left").strip().lower()
    if button not in ("left", "right", "middle", "double", "move"):
        raise ValidationError("button must be left|right|middle|double|move")
    out = _run_worker(
        bot,
        ["click", "--x", str(x), "--y", str(y), "--button", button],
        home=home,
    )
    return {"ok": True, "bot": bot, "x": x, "y": y, "button": button, "detail": out}


def type_text(
    bot: str,
    text: str,
    *,
    method: str = "type",
    home: Path | None = None,
) -> dict[str, Any]:
    text = text if text is not None else ""
    if text == "":
        raise ValidationError("text required")
    method = (method or "type").strip().lower()
    if method not in ("type", "paste"):
        raise ValidationError("method must be type|paste")
    out = _run_worker(bot, [method], stdin=text.encode("utf-8"), home=home)
    chars = len(text)
    for part in out.split():
        if part.startswith("chars="):
            try:
                chars = int(part.split("=", 1)[1])
            except ValueError:
                pass
    return {
        "ok": True,
        "bot": bot,
        "method": method,
        "chars": chars,
        "detail": out,
    }


def scroll(
    bot: str,
    dy: int,
    *,
    x: int = 0,
    y: int = 0,
    home: Path | None = None,
) -> dict[str, Any]:
    """Scroll via VNC wheel. dy>0 scrolls content down (read further); dy<0 up."""
    dy = int(dy)
    if dy == 0:
        raise ValidationError("dy must be non-zero")
    args = ["scroll", "--dy", str(dy)]
    if x > 0:
        args.extend(["--x", str(int(x))])
    if y > 0:
        args.extend(["--y", str(int(y))])
    out = _run_worker(bot, args, home=home)
    return {"ok": True, "bot": bot, "dy": dy, "x": int(x), "y": int(y), "detail": out}


def key(
    bot: str,
    name: str,
    *,
    repeats: int = 1,
    home: Path | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValidationError("key name required")
    repeats = max(1, min(int(repeats), 50))
    out = _run_worker(
        bot,
        ["key", "--key", name, "--repeat", str(repeats)],
        home=home,
    )
    return {"ok": True, "bot": bot, "key": name, "repeats": repeats, "detail": out}


def drag(
    bot: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Drag with left button held from (x1,y1) to (x2,y2) — e.g. slide captchas."""
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    if min(x1, y1, x2, y2) < 0:
        raise ValidationError("coordinates must be >= 0")
    out = _run_worker(
        bot,
        ["drag", "--x", str(x1), "--y", str(y1), "--x2", str(x2), "--y2", str(y2)],
        home=home,
    )
    return {
        "ok": True,
        "bot": bot,
        "x": x1,
        "y": y1,
        "x2": x2,
        "y2": y2,
        "detail": out,
    }


def wander(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    """Brief cursor drift (no click) — see ``vnc_type_worker._wander``."""
    out = _run_worker(bot, ["wander"], home=home)
    return {"ok": True, "bot": bot, "detail": out}
