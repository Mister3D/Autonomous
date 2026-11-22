"""Pi and its npm plugins: what is behind, and a checked update.

Pi itself is compared with https://pi.dev/api/latest-version (the same source
``pi update`` uses). Plugins listed in ``~/.pi/agent/settings.json`` whose
source is ``npm:…`` are compared with ``npm view``. Apply runs the fixed
``pi update`` argv for the boxes the user left checked. No shell.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from autonomous.paths import ensure_home
from autonomous.services.errors import Conflict, ValidationError

_LATEST_PI = "https://pi.dev/api/latest-version"
_CACHE_NAME = "pi-packages-check.json"
_CACHE_TTL_S = 6 * 3600
_lock = threading.Lock()
_apply_running = False


def _agent_dir() -> Path:
    return Path.home() / ".pi" / "agent"


def _now() -> float:
    return time.time()


def _cache_path(home: Path | None) -> Path:
    return ensure_home(home) / _CACHE_NAME


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _version_key(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in str(raw or "").strip().split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or "0"))
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    if not latest or not current:
        return bool(latest) and not current
    return _version_key(latest) > _version_key(current)


def _pi_version(agent: Path) -> str:
    pointer = agent / "install" / "current-version"
    if pointer.is_file():
        text = pointer.read_text(encoding="utf-8").strip()
        if text:
            return text
    pi = shutil.which("pi")
    if not pi:
        return ""
    try:
        proc = subprocess.run(
            [pi, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip().split()[-1] if proc.returncode == 0 else ""


def _latest_pi() -> str:
    req = urllib.request.Request(_LATEST_PI, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    version = str((data or {}).get("version") or "").strip()
    if not version:
        raise ValidationError("Pi version feed returned no version", code="pi_version_failed")
    return version


def _configured(agent: Path) -> list[str]:
    data = _read_json(agent / "settings.json")
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, list):
        return []
    out: list[str] = []
    for item in packages:
        source = str(item or "").strip()
        if source and source not in out:
            out.append(source)
    return out


def _npm_spec(source: str) -> str:
    if not source.startswith("npm:"):
        return ""
    return source[4:].strip()


def _installed_npm_version(agent: Path, spec: str) -> str:
    path = agent / "npm" / "node_modules" / spec / "package.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return ""
    return str(data.get("version") or "").strip()


def _npm_bin() -> str:
    found = shutil.which("npm")
    if found:
        return found
    managed = Path.home() / ".local" / "share" / "pi-node" / "current" / "bin" / "npm"
    if managed.is_file():
        return str(managed)
    raise ValidationError("npm not found", code="npm_missing")


def _npm_latest(spec: str) -> str:
    proc = subprocess.run(
        [_npm_bin(), "view", spec, "version", "--json"],
        capture_output=True,
        text=True,
        timeout=25,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "npm view failed").strip()
        raise ValidationError(err[:200], code="npm_view_failed")
    parsed = json.loads(proc.stdout or "null")
    if isinstance(parsed, list):
        parsed = parsed[-1] if parsed else ""
    version = str(parsed or "").strip().strip('"')
    if not version:
        raise ValidationError(f"no version for {spec}", code="npm_view_failed")
    return version


def _row(item_id: str, label: str, current: str, latest: str, *, error: str = "") -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "current": current,
        "latest": latest,
        "update": is_newer(latest, current) if not error else False,
        "error": error,
    }


def check(*, home: Path | None = None, force: bool = False, agent: Path | None = None) -> dict[str, Any]:
    """Pi plus configured npm plugins. Cached for six hours unless ``force``."""
    path = _cache_path(home)
    if not force and path.is_file():
        cached = _read_json(path)
        if isinstance(cached, dict):
            age = _now() - float(cached.get("checked_at_epoch") or 0)
            if 0 <= age < _CACHE_TTL_S and cached.get("ok"):
                return {**cached, "cached": True}

    root = agent or _agent_dir()
    items: list[dict[str, Any]] = []
    pi_error = ""
    current_pi = _pi_version(root)
    latest_pi = ""
    try:
        latest_pi = _latest_pi()
    except Exception as exc:  # noqa: BLE001
        pi_error = str(exc)[:200]
    if current_pi or latest_pi or pi_error:
        items.append(_row("pi", "Pi", current_pi, latest_pi, error=pi_error))

    for source in _configured(root):
        spec = _npm_spec(source)
        if not spec:
            continue
        current = _installed_npm_version(root, spec)
        latest = ""
        error = ""
        try:
            latest = _npm_latest(spec)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:200]
        items.append(_row(source, spec, current, latest, error=error))

    out = {
        "ok": True,
        "cached": False,
        "checked_at_epoch": _now(),
        "items": items,
        "updates": sum(1 for row in items if row["update"]),
    }
    try:
        path.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


def _allowed_sources(agent: Path) -> set[str]:
    return {"pi", *_configured(agent)}


def start_apply(items: list[str], *, home: Path | None = None, agent: Path | None = None) -> dict[str, Any]:
    """Update the checked entries. ``pi`` runs ``pi update --self``; a plugin source runs ``pi update <source>``."""
    global _apply_running
    from autonomous.services import jobs as jobs_svc
    from autonomous.services import setup as setup_svc

    pi = shutil.which("pi")
    if not pi:
        raise ValidationError("pi CLI not found", code="no_pi")
    wanted = []
    for raw in items or []:
        item = str(raw or "").strip()
        if item and item not in wanted:
            wanted.append(item)
    if not wanted:
        raise ValidationError("nothing selected", code="nothing_selected")
    allowed = _allowed_sources(agent or _agent_dir())
    unknown = [item for item in wanted if item not in allowed]
    if unknown:
        raise ValidationError("unknown package", code="unknown_package")

    with _lock:
        if _apply_running:
            raise Conflict("a Pi update is already running", code="update_running")
        _apply_running = True

    job = jobs_svc.create_job(setup_svc.SETUP_BOT, "setup.pi_packages", home=home)

    def worker() -> None:
        global _apply_running
        try:
            jobs_svc.update_job(job["id"], state="running", progress=5, home=home)
            for item in wanted:
                argv = [pi, "update", "--self"] if item == "pi" else [pi, "update", item]
                jobs_svc.update_job(job["id"], log_line="$ " + " ".join(argv), home=home)
                rc = setup_svc._stream(job["id"], argv, home)
                if rc != 0:
                    raise RuntimeError(f"{item} failed (exit {rc})")
            try:
                _cache_path(home).unlink()
            except OSError:
                pass
            jobs_svc.update_job(
                job["id"],
                state="done",
                progress=100,
                log_line="✓ done",
                home=home,
            )
        except Exception as exc:  # noqa: BLE001
            jobs_svc.update_job(
                job["id"],
                state="failed",
                progress=100,
                error=str(exc)[:300],
                log_line=f"✗ {exc}",
                home=home,
            )
        finally:
            with _lock:
                _apply_running = False

    threading.Thread(target=worker, name="pi-packages", daemon=True).start()
    return jobs_svc.get_job(job["id"], home=home)
