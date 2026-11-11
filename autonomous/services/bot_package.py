"""Estimate how much disk a bot package occupies (VM + files + chat + agent)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.paths import bot_dir, bot_pi_dir
from autonomous.services import bots as bots_svc
from autonomous.services.errors import AutonomousError

# Chrome profile under ~/files (often the heaviest folder after a few days).
_CHROME_REL = Path(".autonomous-chrome")
_SHOTS_REL = Path(".autonomous") / "screenshots"


def _dir_bytes(path: Path) -> int:
    """Sum regular-file sizes under ``path`` (no symlink follow). Missing → 0."""
    if not path.exists():
        return 0
    total = 0
    if path.is_file():
        try:
            return int(path.stat().st_size)
        except OSError:
            return 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += int((Path(root) / name).stat().st_size)
            except OSError:
                continue
    return total


def _chat_bytes(bot: str, home: Path | None) -> tuple[int, int]:
    """UTF-8 byte length of stored messages + count (attachments live under ~/files)."""
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS n,
              COALESCE(SUM(
                length(COALESCE(content, ''))
                + length(COALESCE(attachments_json, ''))
                + length(COALESCE(meta_json, ''))
              ), 0) AS bytes
            FROM messages
            WHERE bot = ?
            """,
            (bot,),
        ).fetchone()
    return int(row["bytes"] or 0), int(row["n"] or 0)


def _docker_client():
    try:
        import docker
    except ImportError as exc:
        raise AutonomousError("docker SDK not installed") from exc
    return docker.from_env()


def _container_names_match(entry_names: Any, want: str) -> bool:
    """Docker df Names look like ``['/autonomous-…']``."""
    want = (want or "").strip()
    if not want:
        return False
    for raw in entry_names or []:
        n = str(raw).lstrip("/")
        if n == want or str(raw) == want or str(raw).endswith("/" + want):
            return True
    return False


def _vm_layer_bytes(bot: str, home: Path | None) -> tuple[int | None, str]:
    """Docker writable layer (SizeRw). Base image is shared — not counted per bot.

    Returns ``(bytes_or_None, state)`` where state is absent|creating|running|
    sleeping|error|unknown.

    Note: current docker-py ``inspect_container`` has no ``size=`` kwarg; sizes
    come from ``client.df()`` (same source as ``docker system df -v``).
    """
    from autonomous.services import desk as desk_svc

    desk = desk_svc.status(bot, home=home) or {}
    state = str(desk.get("state") or "absent")
    if state in ("", "absent", "none"):
        return None, "absent"
    name = (desk.get("container_name") or "").strip() or desk_svc.container_name(
        bot, home=home
    )
    if not name:
        return None, state
    try:
        client = _docker_client()
        for entry in client.df().get("Containers") or []:
            if not _container_names_match(entry.get("Names"), name):
                continue
            raw = entry.get("SizeRw")
            if raw is None:
                return None, state
            return max(0, int(raw)), state
        # Container known to desk but missing from df → still report state.
        client.containers.get(name)
        return None, state
    except Exception:
        return None, state


def package_usage(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    """Full package footprint for Details.

    Media (uploads, shared images, screenshots, Chrome profile) lives under
    ``bots/<bot>/home`` (= ~/files). Conversation size is SQLite text only —
    file bytes are not double-counted there.
    """
    bots_svc.get_bot(bot, home=home)
    root = bot_dir(bot, home)
    shared_root = (root / "home").resolve()
    shared_root.mkdir(parents=True, exist_ok=True)

    screenshots = _dir_bytes(shared_root / _SHOTS_REL)
    browser = _dir_bytes(shared_root / _CHROME_REL)
    shared_total = _dir_bytes(shared_root)
    # Remaining workspace files (uploads, SVG, mail staging, …) after known heavy dirs.
    files = max(0, shared_total - screenshots - browser)

    chat, messages = _chat_bytes(bot, home)
    agent = _dir_bytes(bot_pi_dir(bot, home))
    downloads = _dir_bytes(root / "downloads")

    vm, vm_state = _vm_layer_bytes(bot, home)
    vm_bytes = int(vm or 0)

    host = shared_total + agent + downloads + chat
    total = host + vm_bytes

    return {
        "bot": bot,
        "total_bytes": total,
        "host_bytes": host,
        "files_bytes": files,
        "screenshots_bytes": screenshots,
        "browser_bytes": browser,
        "shared_bytes": shared_total,
        "chat_bytes": chat,
        "messages": messages,
        "agent_bytes": agent,
        "downloads_bytes": downloads,
        "vm_bytes": vm,
        "vm_state": vm_state,
    }
