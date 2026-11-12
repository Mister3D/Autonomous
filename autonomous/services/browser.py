"""Generic Chrome CDP browser tools for a bot desk (no site-specific logic)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from autonomous.paths import bot_dir
from autonomous.services import bots as bots_svc
from autonomous.services.errors import AutonomousError, ValidationError

_CDP = Path(__file__).resolve().parent / "cdp_client.py"
_WORKER = Path(__file__).resolve().parent / "chrome_cdp_worker.py"
_CONT_DIR = "/home/autonomous/workspace/.autonomous"
_CONT_WORKER = f"{_CONT_DIR}/_chrome_cdp_worker.py"
_CONT_CDP = f"{_CONT_DIR}/cdp_client.py"


def _chown_bot(path: Path) -> None:
    try:
        os.chown(path, 1000, 1000)
    except OSError:
        pass


def _ensure_desk(bot: str, *, home: Path | None) -> None:
    from autonomous.services import desk as desk_svc

    desk_svc.ensure_awake(bot, home=home)


def _copy_workers(bot: str, *, home: Path | None) -> None:
    host = bot_dir(bot, home) / "home" / ".autonomous"
    host.mkdir(parents=True, exist_ok=True)
    _chown_bot(host)
    for src, name in ((_WORKER, "_chrome_cdp_worker.py"), (_CDP, "cdp_client.py")):
        if not src.is_file():
            raise AutonomousError(f"Missing {src.name} on host", code="internal")
        dst = host / name
        shutil.copyfile(src, dst)
        _chown_bot(dst)


def _run(bot: str, args: list[str], *, home: Path | None = None) -> dict[str, Any]:
    from autonomous.services import desk as desk_svc

    _ensure_desk(bot, home=home)
    _copy_workers(bot, home=home)
    cmd = [
        "docker",
        "exec",
        "-u",
        "autonomous",
        "-e",
        "HOME=/home/autonomous",
        "-e",
        "DISPLAY=:1",
        desk_svc.container_name(bot, home=home),
        "python3",
        _CONT_WORKER,
        *args,
    ]
    try:
        completed = subprocess.run(
            cmd, capture_output=True, timeout=45, check=False
        )
    except FileNotFoundError as exc:
        raise AutonomousError("docker CLI not found on host") from exc
    except subprocess.TimeoutExpired as exc:
        raise AutonomousError("Browser CDP timed out", code="timeout") from exc
    raw = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
    if not raw:
        raise AutonomousError(
            f"Browser CDP failed: {err[:300] or 'empty output'}",
            code="browser_cdp_failed",
        )
    # Worker prints one JSON object on stdout
    line = raw.splitlines()[-1]
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise AutonomousError(
            f"Browser CDP bad JSON: {line[:200]}",
            code="browser_cdp_failed",
        ) from exc
    if not isinstance(data, dict):
        raise AutonomousError("Browser CDP unexpected payload", code="browser_cdp_failed")
    if completed.returncode != 0 or data.get("ok") is False:
        raise AutonomousError(
            str(data.get("error") or err or "CDP error"),
            code="browser_cdp_failed",
        )
    data.setdefault("ok", True)
    data["bot"] = bot
    return data


def tabs(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    return _run(bot, ["tabs"], home=home)


def navigate(bot: str, url: str, *, home: Path | None = None) -> dict[str, Any]:
    url = (url or "").strip()
    if not url:
        raise ValidationError("url required")
    from autonomous.services.url_policy import assert_seen_url

    url = assert_seen_url(bot, url, home=home)
    result = _run(bot, ["navigate", "--url", url], home=home)
    _wander_async(bot, home=home)
    return result


def wait_load(
    bot: str, *, timeout: float = 15.0, home: Path | None = None
) -> dict[str, Any]:
    """Wait (bounded) for the active page to finish loading — replaces ``sleep N``."""
    timeout = max(1.0, min(float(timeout), 30.0))
    return _run(bot, ["wait_load", "--timeout", f"{timeout:g}"], home=home)


def switch_tab(
    bot: str, *, index: int = 0, match: str = "", home: Path | None = None
) -> dict[str, Any]:
    """Bring a tab to the front (1-based index from ``tabs`` or URL/title substring)."""
    if not index and not (match or "").strip():
        raise ValidationError("index or match required")
    return _run(
        bot, ["switch_tab", "--index", str(int(index)), "--match", (match or "").strip()],
        home=home,
    )


def close_tab(
    bot: str, *, index: int = 0, match: str = "", home: Path | None = None
) -> dict[str, Any]:
    """Close a tab (default: the active one). The last tab is never closed."""
    return _run(
        bot, ["close_tab", "--index", str(int(index)), "--match", (match or "").strip()],
        home=home,
    )


def reset_session(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    """Forget cookies / cache / site storage (like opening a fresh private window)."""
    return _run(bot, ["reset_session"], home=home)


def _wander_async(bot: str, *, home: Path | None = None) -> None:
    """After a page load, drift the cursor a little (anti-bot: frozen mouse is a tell)."""
    import threading

    def _go() -> None:
        try:
            from autonomous.services import desk_input

            desk_input.wander(bot, home=home)
        except Exception:
            pass  # purely cosmetic; never break navigation

    threading.Thread(target=_go, name=f"wander-{bot}", daemon=True).start()


def html(
    bot: str,
    *,
    max_chars: int = 12000,
    selector: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    args = ["html", "--max", str(max(500, min(int(max_chars), 100_000)))]
    if selector:
        args.extend(["--selector", selector])
    return _run(bot, args, home=home)


def text(bot: str, *, max_chars: int = 8000, home: Path | None = None) -> dict[str, Any]:
    out = _run(
        bot,
        ["text", "--max", str(max(500, min(int(max_chars), 100_000)))],
        home=home,
    )
    from autonomous.services.observe_gate import mark_dom_observe

    mark_dom_observe(bot)
    return out


def links(
    bot: str,
    *,
    query: str | None = None,
    max_links: int = 40,
    home: Path | None = None,
) -> dict[str, Any]:
    args = ["links", "--max", str(max(1, min(int(max_links), 200)))]
    if query:
        args.extend(["--query", query])
    return _run(bot, args, home=home)


def scroll(
    bot: str, *, dy: int = 600, dx: int = 0, home: Path | None = None
) -> dict[str, Any]:
    return _run(
        bot,
        ["scroll", "--dy", str(int(dy)), "--dx", str(int(dx))],
        home=home,
    )


def snapshot(
    bot: str,
    *,
    max_elements: int = 60,
    query: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Read interactive DOM controls without scrolling or clicking."""
    args = ["snapshot", "--max", str(max(1, min(int(max_elements), 120)))]
    if query:
        args.extend(["--query", query])
    out = _run(bot, args, home=home)
    from autonomous.services.observe_gate import mark_dom_observe, remember_browser_read

    mark_dom_observe(bot)
    if not query and isinstance(out, dict):
        remember_browser_read(bot, out)
    return out


def frames_snapshot(
    bot: str,
    *,
    max_elements: int = 60,
    query: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Page + cross-origin iframe controls with screen coords for VNC gestures."""
    args = ["frames_snapshot", "--max", str(max(1, min(int(max_elements), 120)))]
    if query:
        args.extend(["--query", query])
    out = _run(bot, args, home=home)
    from autonomous.services.observe_gate import mark_dom_observe, remember_browser_read

    mark_dom_observe(bot)
    if not query and isinstance(out, dict):
        remember_browser_read(bot, out)
    return out


def click_selector(
    bot: str, selector: str, *, home: Path | None = None
) -> dict[str, Any]:
    selector = (selector or "").strip()
    if not selector:
        raise ValidationError("selector required")
    return _run(bot, ["click_selector", "--selector", selector], home=home)


def evaluate(bot: str, js: str, *, home: Path | None = None) -> dict[str, Any]:
    js = (js or "").strip()
    if not js:
        raise ValidationError("js required")
    if len(js) > 8000:
        raise ValidationError("js too long")
    return _run(bot, ["eval", "--js", js], home=home)
