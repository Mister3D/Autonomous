"""Capture the bot desktop (X11) server-side — no browser required."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.paths import bot_dir
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services.errors import AutonomousError, NotFound, ValidationError
from autonomous.services.events import BUS

_WORKER = Path(__file__).resolve().parent / "x11_screenshot_worker.py"
_CONTAINER_WORKER = "/home/autonomous/workspace/.autonomous/_x11_screenshot_worker.py"
_SHOTS_REL = Path(".autonomous") / "screenshots"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chown_bot(path: Path) -> None:
    """Match desk bind-mount ownership (uid/gid 1000 inside the image)."""
    try:
        os.chown(path, 1000, 1000)
    except OSError:
        pass


def screenshots_dir(bot: str, home: Path | None = None) -> Path:
    root = bot_dir(bot, home) / "home" / ".autonomous"
    root.mkdir(parents=True, exist_ok=True)
    _chown_bot(root)
    path = root / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    _chown_bot(path)
    return path


def capture(
    bot: str,
    *,
    show_in_chat: bool = True,
    home: Path | None = None,
) -> dict[str, Any]:
    """Grab the VM root window to PNG under the bot shared home."""
    from autonomous.services import desk as desk_svc

    desk_svc.ensure_awake(bot, home=home)
    if not _WORKER.is_file():
        raise AutonomousError("Screenshot worker missing on host", code="internal")

    shot_id = str(uuid.uuid4())
    host_dir = screenshots_dir(bot, home=home)
    host_png = host_dir / f"{shot_id}.png"
    # Ensure worker is visible inside the container via the shared bind mount.
    host_autonomous = bot_dir(bot, home) / "home" / ".autonomous"
    host_autonomous.mkdir(parents=True, exist_ok=True)
    _chown_bot(host_autonomous)
    host_worker = host_autonomous / "_x11_screenshot_worker.py"
    shutil.copyfile(_WORKER, host_worker)
    _chown_bot(host_worker)

    container_png = f"/home/autonomous/workspace/{_SHOTS_REL.as_posix()}/{shot_id}.png"
    name = desk_svc.container_name(bot, home=home)
    cmd = [
        "docker",
        "exec",
        "-u",
        "autonomous",
        "-e",
        "DISPLAY=:1",
        "-e",
        "HOME=/home/autonomous",
        name,
        "python3",
        _CONTAINER_WORKER,
        container_png,
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AutonomousError("docker CLI not found on host") from exc
    except subprocess.TimeoutExpired as exc:
        raise AutonomousError("Screenshot timed out", code="timeout") from exc

    if completed.returncode != 0 or not host_png.is_file():
        err = (completed.stderr or completed.stdout or "unknown error").strip()
        raise AutonomousError(f"Screenshot failed: {err}", code="screenshot_failed")

    geom = (completed.stdout or "").strip().splitlines()
    width, height = 0, 0
    if geom:
        try:
            w_s, h_s = geom[-1].lower().split("x", 1)
            width, height = int(w_s), int(h_s)
        except ValueError:
            pass
    if width <= 0 or height <= 0:
        # Fallback size from file is unknown without decoding; leave 0.
        pass

    rel_path = f"{_SHOTS_REL.as_posix()}/{shot_id}.png"
    url = f"/api/v1/bots/{bot}/screen/screenshots/{shot_id}.png"
    entry = {
        "id": shot_id,
        "bot": bot,
        "path": rel_path,
        "url": url,
        "width": width,
        "height": height,
        "bytes": host_png.stat().st_size,
        "created_at": _now(),
        "show_in_chat": bool(show_in_chat),
    }

    message = None
    if show_in_chat:
        message = chat_svc.create_message(
            bot,
            f"Capture d’écran ({width}×{height})" if width and height else "Capture d’écran",
            role="event",
            meta={
                "kind": "screenshot",
                "screenshot_id": shot_id,
                "url": url,
                "path": rel_path,
                "width": width,
                "height": height,
            },
            home=home,
        )
        entry["message_id"] = message["id"]

    BUS.publish("screenshot.created", {"screenshot": entry}, bot=bot)
    return entry


def resolve_png(bot: str, shot_id: str, home: Path | None = None) -> Path:
    bots_svc.get_bot(bot, home=home)
    # Prevent path traversal — id must be a plain uuid-like filename stem.
    safe = Path(shot_id).name
    if safe != shot_id or "/" in shot_id or "\\" in shot_id or ".." in shot_id:
        raise ValidationError("Invalid screenshot id")
    if not safe.endswith(".png"):
        safe = f"{safe}.png"
    path = screenshots_dir(bot, home=home) / safe
    if not path.is_file():
        raise NotFound("Screenshot not found")
    return path


def read_png_bytes(bot: str, shot_id: str, home: Path | None = None) -> bytes:
    return resolve_png(bot, shot_id, home=home).read_bytes()
