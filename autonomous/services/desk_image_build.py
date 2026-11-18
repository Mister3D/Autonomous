"""Build ``autonomous-desktop`` in the background when serve starts.

Same idea as companion_build: hash ``docker/desktop/`` sources; rebuild when the
image is missing or the hash changed. Never blocks ``serve``.

Disable with ``AUTONOMOUS_DESK_IMAGE_BUILD=0``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from autonomous.paths import ensure_home
from autonomous.services import settings as settings_svc

_lock = threading.Lock()
_thread: threading.Thread | None = None


def source_dir() -> Path:
    override = os.environ.get("AUTONOMOUS_DESKTOP_SRC")
    if override:
        return Path(override).expanduser().resolve()
    repo = Path(__file__).resolve().parents[2] / "docker" / "desktop"
    if (repo / "Dockerfile").is_file():
        return repo
    return Path.cwd() / "docker" / "desktop"


def work_dir(home: Path | None = None) -> Path:
    d = ensure_home(home) / "desk-image"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_path(home: Path | None) -> Path:
    return work_dir(home) / "status.json"


def _log_path(home: Path | None) -> Path:
    return work_dir(home) / "build.log"


def image_tag(home: Path | None = None) -> str:
    return str(settings_svc.get("desktop_image", home=home) or "autonomous-desktop:latest")


def source_hash(src: Path | None = None) -> str:
    src = src or source_dir()
    h = hashlib.sha256()
    if not src.is_dir():
        return h.hexdigest()[:16]
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = str(path.relative_to(src)).replace("\\", "/")
        if any(part.startswith(".") for part in Path(rel).parts):
            continue
        h.update(rel.encode())
        h.update(b"\0")
        try:
            h.update(path.read_bytes())
        except OSError:
            continue
        h.update(b"\0")
    return h.hexdigest()[:16]


def docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def image_present(tag: str | None = None) -> bool:
    tag = tag or image_tag()
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
                capture_output=True,
                timeout=15,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def _read_status(home: Path | None) -> dict[str, Any]:
    path = _status_path(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _write_status(home: Path | None, data: dict[str, Any]) -> None:
    path = _status_path(home)
    payload = {**_read_status(home), **data}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def status(home: Path | None = None) -> dict[str, Any]:
    home = ensure_home(home)
    st = _read_status(home)
    digest = source_hash()
    tag = image_tag(home)
    present = image_present(tag)
    built_hash = str(st.get("hash") or "")
    stale = bool(present and built_hash and built_hash != digest)
    state = str(st.get("state") or "")
    if _thread is not None and _thread.is_alive():
        state = "building"
    elif not state:
        if not docker_ok():
            state = "no_docker"
        elif not present:
            state = "missing"
        elif stale:
            state = "stale"
        else:
            state = "ready"
    return {
        "state": state,
        "hash": digest,
        "built_hash": built_hash,
        "image": tag,
        "present": present,
        "stale": stale,
        "error": st.get("error") or "",
        "log": str(_log_path(home)),
        "finished_at": st.get("finished_at"),
    }


def needs_build(home: Path | None = None, *, force: bool = False) -> bool:
    if force:
        return True
    st = status(home)
    if st["state"] == "building":
        return False
    if not docker_ok():
        return False
    if not st["present"]:
        return True
    if st["stale"]:
        return True
    return False


def _build(home: Path, *, force: bool = False) -> None:
    del force  # caller already decided; kept for API symmetry with companion_build
    src = source_dir()
    tag = image_tag(home)
    digest = source_hash(src)
    log_path = _log_path(home)
    if not (src / "Dockerfile").is_file():
        _write_status(
            home,
            {"state": "failed", "error": f"Dockerfile missing in {src}", "hash": digest},
        )
        return
    if not docker_ok():
        _write_status(
            home,
            {"state": "no_docker", "error": "Docker daemon not available", "hash": digest},
        )
        return

    _write_status(
        home,
        {
            "state": "building",
            "hash": digest,
            "image": tag,
            "error": "",
            "started_at": time.time(),
        },
    )
    argv = ["docker", "build", "-t", tag, str(src)]
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(argv)}\n")
        log.flush()
        try:
            proc = subprocess.run(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=None,
            )
            rc = proc.returncode
        except OSError as exc:
            log.write(f"\nerror: {exc}\n")
            _write_status(
                home,
                {
                    "state": "failed",
                    "error": str(exc),
                    "hash": digest,
                    "finished_at": time.time(),
                },
            )
            return
    if rc == 0:
        _write_status(
            home,
            {
                "state": "ready",
                "hash": digest,
                "image": tag,
                "error": "",
                "finished_at": time.time(),
            },
        )
    else:
        _write_status(
            home,
            {
                "state": "failed",
                "error": f"docker build exited {rc} (see {log_path})",
                "hash": digest,
                "finished_at": time.time(),
            },
        )


def start_background(home: Path | None = None, *, force: bool = False) -> bool:
    """Start a desk image build thread when needed. Never blocks."""
    global _thread
    if os.environ.get("AUTONOMOUS_DESK_IMAGE_BUILD", "1") == "0" and not force:
        return False
    home = ensure_home(home)
    if not force and not needs_build(home):
        return False
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False

        def run() -> None:
            try:
                _build(home, force=force)
            except Exception as exc:  # never crash serve
                _write_status(home, {"state": "failed", "error": str(exc)})
            st = status(home)
            print(
                f"[desk-image] build {st.get('state')}: {st.get('image')}"
                + (f" ({st.get('error')})" if st.get("error") else ""),
                flush=True,
            )

        print(
            f"[desk-image] building {image_tag(home)} in the background (~10 min)…",
            flush=True,
        )
        _thread = threading.Thread(target=run, name="desk-image-build", daemon=True)
        _thread.start()
    return True
