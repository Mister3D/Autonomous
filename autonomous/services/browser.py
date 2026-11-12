"""Generic Chrome CDP browser tools for a bot desk (no site-specific logic)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
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


def format_page_read(payload: dict[str, Any]) -> str:
    """One text block: controls with screen= plus a short visible-text excerpt."""
    if not isinstance(payload, dict):
        return "(no page read)"
    if payload.get("ok") is False and not payload.get("elements"):
        return f"(page read failed: {payload.get('error') or 'error'})"
    lines = [
        "Page now. If the visible text already states what the user asked, "
        "answer now and stop. Otherwise vm_click the next screen= point. "
        "Do not call browser_snapshot, browser_wait_load, or browser_text "
        "unless this list is empty.",
        f"url: {payload.get('url') or '?'}",
        f"title: {payload.get('title') or '?'}",
    ]
    overlays = payload.get("overlays") or []
    if isinstance(overlays, list) and overlays:
        lines.append("!! BLOCKING OVERLAY — vm_click its screen= point first:")
        for overlay in overlays[:3]:
            if not isinstance(overlay, dict):
                continue
            lines.append(
                f"   [{overlay.get('kind') or 'overlay'}] "
                f"\"{str(overlay.get('text') or '')[:160]}\""
            )
            for control in (overlay.get("controls") or [])[:8]:
                if not isinstance(control, dict):
                    continue
                screen = control.get("screen") or {}
                lines.append(
                    f"   - {control.get('tag') or 'control'} "
                    f"\"{str(control.get('text') or '')[:60]}\" "
                    f"screen={screen.get('x')},{screen.get('y')}"
                )
    elements = payload.get("elements") or []
    shown = 0
    if isinstance(elements, list):
        for el in elements:
            if not isinstance(el, dict) or shown >= 40:
                break
            screen = el.get("screen") or {}
            bits = [
                "[offscreen]" if el.get("in_viewport") is False else "[in-view]",
                f"[COVERED by {el.get('occluded_by')}]" if el.get("occluded_by") else "",
                "[FOCUSED]" if el.get("focused") else "",
                f"[filled {el.get('filled')} chars]" if isinstance(el.get("filled"), int) else "",
                str(el.get("tag") or "?"),
                f"\"{str(el.get('text') or '')[:80]}\"" if el.get("text") else "",
                f"screen={screen.get('x')},{screen.get('y')}" if screen else "",
            ]
            lines.append("- " + " ".join(bit for bit in bits if bit))
            shown += 1
    if shown == 0:
        lines.append("(no control in the top document)")
    text = str(payload.get("text") or "").strip()
    if text:
        lines.append("")
        lines.append("Visible text:")
        lines.append(text[:800])
    return "\n".join(lines)


def page_did_change(before: dict[str, Any] | None, after: dict[str, Any] | None) -> bool:
    """A load wait is needed when the document navigated or is still loading.

    A click that only focuses a field keeps the same URL, title and
    ``complete`` state: that one does not wait. Unknown markers wait.
    """
    if not before or not after:
        return True
    if after.get("ready") != "complete":
        return True
    return before.get("url") != after.get("url") or before.get("title") != after.get("title")


def page_marker(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    """Cheap URL / title / readyState sample. Empty when Chrome is not answering."""
    try:
        data = evaluate(
            bot,
            "({url:location.href,title:document.title,ready:document.readyState})",
            home=home,
        )
    except Exception:
        return {}
    value = data.get("value") if isinstance(data, dict) else None
    if not isinstance(value, dict):
        return {}
    return {
        "url": str(value.get("url") or ""),
        "title": str(value.get("title") or ""),
        "ready": str(value.get("ready") or ""),
    }


def read_after_gesture(
    bot: str,
    *,
    wait: bool = True,
    before: dict[str, Any] | None = None,
    home: Path | None = None,
) -> str:
    """Snapshot after a gesture. Wait for load only if the page changed."""
    if wait:
        try:
            time.sleep(0.15)
            after = page_marker(bot, home=home)
            if page_did_change(before, after):
                wait_load(bot, timeout=2.5, home=home)
        except Exception:
            pass
    try:
        snap = snapshot(bot, home=home)
    except Exception as exc:
        return f"(page read failed: {exc})"
    return format_page_read(snap)


def navigate(bot: str, url: str, *, home: Path | None = None) -> dict[str, Any]:
    url = (url or "").strip()
    if not url:
        raise ValidationError("url required")
    from autonomous.services.url_policy import assert_seen_url

    url = assert_seen_url(bot, url, home=home)
    result = _run(bot, ["navigate", "--url", url], home=home)
    _wander_async(bot, home=home)
    if isinstance(result, dict):
        try:
            result = dict(result)
            result["page"] = read_after_gesture(bot, wait=False, home=home)
        except Exception:
            pass
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
