"""Build the companion binary in the background and serve it for download.

At ``autonomous serve`` startup the companion (``companion/`` in the repo) is
compiled for Linux (``x86_64-unknown-linux-gnu``) and Windows
(``x86_64-pc-windows-gnu``). When Docker works, the build runs in a throwaway
container from the ``autonomous-companion-builder`` image
(``companion/build/Dockerfile``: Rust, MinGW-w64, GTK/tray dev libs), so the
host needs no packages. Without Docker it falls back to the host ``cargo``
(host target, plus Windows when MinGW-w64 is installed). macOS binaries are
not built: compile them on a Mac with ``cargo build --release``. Builds are cached
by a hash of the companion sources, so restarts don't rebuild anything.

Disable with ``AUTONOMOUS_COMPANION_BUILD=0``; force the host cargo path with
``AUTONOMOUS_COMPANION_DOCKER=0``.

Layout under ``AUTONOMOUS_HOME/companion/``::

    status.json        last build status (read by the API)
    build.log          cargo output of the last build
    target/            cargo target dir (host cache)
    docker-target/     cargo target dir (Docker cache)
    docker-cargo/      cargo registry cache (Docker)
    dist/<hash>/<triple>/autonomous-companion[.exe]
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from autonomous.paths import ensure_home

BIN_NAME = "autonomous-companion"
WINDOWS_GNU = "x86_64-pc-windows-gnu"
RUSTUP_HINT = (
    "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
)

LINUX_GNU = "x86_64-unknown-linux-gnu"
BUILDER_IMAGE = "autonomous-companion-builder"
MACOS_NOTE = "macOS is not built here: run `cargo build --release` on a Mac."

_lock = threading.Lock()
_docker_cache: tuple[float, bool] = (0.0, False)
_thread: threading.Thread | None = None


def source_dir() -> Path:
    override = os.environ.get("AUTONOMOUS_COMPANION_SRC")
    if override:
        return Path(override).expanduser().resolve()
    repo = Path(__file__).resolve().parents[2] / "companion"
    if (repo / "Cargo.toml").is_file():
        return repo
    return Path.cwd() / "companion"


def work_dir(home: Path | None = None) -> Path:
    d = ensure_home(home) / "companion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _status_path(home: Path | None) -> Path:
    return work_dir(home) / "status.json"


def _cargo() -> str | None:
    found = shutil.which("cargo")
    if found:
        return found
    local = Path.home() / ".cargo" / "bin" / "cargo"
    return str(local) if local.is_file() else None


def _rustup() -> str | None:
    found = shutil.which("rustup")
    if found:
        return found
    local = Path.home() / ".cargo" / "bin" / "rustup"
    return str(local) if local.is_file() else None


def docker_ok() -> bool:
    """True when Docker can run containers (cached 30 s). Off with AUTONOMOUS_COMPANION_DOCKER=0."""
    global _docker_cache
    if os.environ.get("AUTONOMOUS_COMPANION_DOCKER", "1") == "0" or not shutil.which("docker"):
        return False
    now = time.monotonic()
    if now - _docker_cache[0] < 30:
        return _docker_cache[1]
    try:
        ok = subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    _docker_cache = (now, ok)
    return ok


def builder() -> str:
    """'docker', 'cargo' or '' (nothing can build)."""
    if docker_ok():
        return "docker"
    return "cargo" if _cargo() else ""


def dockerfile_dir(src: Path | None = None) -> Path:
    return (src or source_dir()) / "build"


def builder_image(src: Path | None = None) -> str:
    """Image tag keyed by the Dockerfile hash, so edits rebuild the image."""
    try:
        data = (dockerfile_dir(src) / "Dockerfile").read_bytes()
    except OSError:
        data = b""
    return f"{BUILDER_IMAGE}:{hashlib.sha256(data).hexdigest()[:12]}"


def docker_run_argv(src: Path, wd: Path, triple: str, image: str) -> list[str]:
    """Throwaway container: sources read-only, caches under AUTONOMOUS_HOME, no privileges."""
    uid, gid = (os.getuid(), os.getgid()) if hasattr(os, "getuid") else (0, 0)
    script = (
        f"cargo build --release --locked --target {triple}; rc=$?; "
        f"chown -R {uid}:{gid} /target /usr/local/cargo/registry 2>/dev/null; exit $rc"
    )
    return [
        "docker", "run", "--rm", "--init",
        "--security-opt", "no-new-privileges",
        "-v", f"{src}:/src:ro",
        "-v", f"{wd / 'docker-target'}:/target",
        "-v", f"{wd / 'docker-cargo'}:/usr/local/cargo/registry",
        "-e", "CARGO_TARGET_DIR=/target",
        "-w", "/src", image, "sh", "-c", script,
    ]


def crate_version(src: Path | None = None) -> str:
    src = src or source_dir()
    try:
        text = (src / "Cargo.toml").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else ""


def source_hash(src: Path | None = None) -> str:
    src = src or source_dir()
    h = hashlib.sha256()
    files = [src / "Cargo.toml", src / "Cargo.lock"]
    files += sorted(p for p in (src / "src").rglob("*") if p.is_file())
    for p in files:
        if not p.is_file():
            continue
        h.update(str(p.relative_to(src)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:16]


def host_triple() -> str:
    rustc = shutil.which("rustc") or str(Path.home() / ".cargo" / "bin" / "rustc")
    try:
        out = subprocess.run(
            [rustc, "-vV"], capture_output=True, text=True, timeout=30
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"^host:\s*(\S+)", out, re.M)
    return m.group(1) if m else ""


def _installed_targets() -> set[str]:
    rustup = _rustup()
    if not rustup:
        return set()
    try:
        out = subprocess.run(
            [rustup, "target", "list", "--installed"],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def _mingw_linker() -> str | None:
    env = os.environ.get("CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER")
    if env:
        return env
    return shutil.which("x86_64-w64-mingw32-gcc")


def platform_of(triple: str) -> str:
    if "windows" in triple:
        return "windows"
    if "apple" in triple or "darwin" in triple:
        return "macos"
    if "linux" in triple:
        return "linux"
    return triple


def _exe_name(triple: str) -> str:
    return BIN_NAME + (".exe" if "windows" in triple else "")


def plan_targets() -> tuple[list[str], list[str]]:
    """Return (targets to build, notes explaining skipped targets)."""
    notes: list[str] = []
    host = host_triple()
    targets = [host] if host else []
    if host and "windows" not in host:
        if not _mingw_linker():
            notes.append(
                "Windows build skipped: install mingw-w64 "
                "(apt install gcc-mingw-w64-x86-64) to cross-compile "
                f"{WINDOWS_GNU}. Only the host target ({host}) is built."
            )
        elif WINDOWS_GNU not in _installed_targets():
            notes.append(
                f"Windows build skipped: run `rustup target add {WINDOWS_GNU}`."
            )
        else:
            targets.append(WINDOWS_GNU)
    return targets, notes


def _write_status(home: Path | None, data: dict[str, Any]) -> None:
    path = _status_path(home)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_status(home: Path | None) -> dict[str, Any]:
    try:
        return json.loads(_status_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def artifact_path(triple: str, home: Path | None = None) -> Path | None:
    st = _read_status(home)
    for a in st.get("artifacts") or []:
        if a.get("target") == triple:
            p = work_dir(home) / "dist" / st.get("hash", "") / triple / a["filename"]
            return p if p.is_file() else None
    return None


def status(home: Path | None = None) -> dict[str, Any]:
    src = source_dir()
    st = _read_status(home)
    out: dict[str, Any] = {
        "state": st.get("state") or "idle",
        "version": crate_version(src),
        "hash": st.get("hash", ""),
        "host": st.get("host", ""),
        "artifacts": [],
        "notes": st.get("notes") or [],
        "error": st.get("error", ""),
        "finished_at": st.get("finished_at"),
        "toolchain": bool(builder()),
        "builder": builder(),
        "rustup_hint": RUSTUP_HINT,
        "enabled": os.environ.get("AUTONOMOUS_COMPANION_BUILD", "1") != "0",
    }
    if not (src / "Cargo.toml").is_file():
        out["state"] = "no_source"
    elif not out["builder"]:
        out["state"] = "no_toolchain"
    with _lock:
        alive = _thread is not None and _thread.is_alive()
    if alive:
        out["state"] = "building"
    elif out["state"] == "building":
        # Previous process stopped mid-build (e.g. dev reloader); next start resumes.
        out["state"] = "interrupted"
    for a in st.get("artifacts") or []:
        p = work_dir(home) / "dist" / st.get("hash", "") / a["target"] / a["filename"]
        if p.is_file():
            out["artifacts"].append({**a, "size": p.stat().st_size})
    if out["artifacts"] and st.get("hash") and st.get("hash") != _safe_hash(src):
        out["stale"] = True
    return out


def _safe_hash(src: Path) -> str:
    try:
        return source_hash(src)
    except OSError:
        return ""


def _build(home: Path, force: bool = False) -> None:
    src = source_dir()
    wd = work_dir(home)
    log_path = wd / "build.log"
    cargo = _cargo()
    use_docker = docker_ok()
    if not (src / "Cargo.toml").is_file() or not (cargo or use_docker):
        _write_status(home, {"state": "no_source" if (cargo or use_docker) else "no_toolchain"})
        return
    digest = source_hash(src)
    prev = _read_status(home)
    if (
        not force
        and prev.get("hash") == digest
        and prev.get("state") == "ready"
        and all(
            (wd / "dist" / digest / a["target"] / a["filename"]).is_file()
            for a in prev.get("artifacts") or []
        )
    ):
        return  # cached
    if use_docker:
        _build_docker(home, src, wd, digest)
        return
    targets, notes = plan_targets()
    notes.append("Docker unavailable: built with the host cargo.")
    notes.append(MACOS_NOTE)
    host = targets[0] if targets else ""
    _write_status(home, {"state": "building", "hash": digest, "host": host,
                         "notes": notes, "started_at": time.time()})
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(wd / "target")
    cargo_bin = str(Path(cargo).parent)
    env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
    linker = _mingw_linker()
    if linker:
        env.setdefault("CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER", linker)
    artifacts: list[dict[str, Any]] = []
    errors: list[str] = []
    with log_path.open("w", encoding="utf-8") as log:
        for triple in targets:
            log.write(f"=== cargo build --release --target {triple}\n")
            log.flush()
            try:
                proc = subprocess.run(
                    [cargo, "build", "--release", "--locked", "--target", triple],
                    cwd=src, env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=3600,
                )
                rc = proc.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.write(f"\n{exc}\n")
                rc = -1
            built = wd / "target" / triple / "release" / _exe_name(triple)
            if rc == 0 and built.is_file():
                dest = wd / "dist" / digest / triple
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(built, dest / built.name)
                artifacts.append({
                    "target": triple,
                    "platform": platform_of(triple),
                    "filename": built.name,
                })
            else:
                errors.append(f"{triple}: cargo exited with {rc} (see {log_path})")
                if platform_of(triple) == "linux":
                    notes.append(
                        "Linux GUI build needs GTK/tray dev libraries "
                        "(apt install libgtk-3-dev libxdo-dev libayatana-appindicator3-dev)."
                    )
    # Drop older dist folders.
    for old in (wd / "dist").glob("*"):
        if old.name != digest:
            shutil.rmtree(old, ignore_errors=True)
    _write_status(home, {
        "state": "ready" if artifacts else "failed",
        "hash": digest,
        "host": host,
        "artifacts": artifacts,
        "notes": notes,
        "error": "; ".join(errors),
        "finished_at": time.time(),
        "builder": "cargo",
    })


def _logged(argv: list[str], log, timeout: int = 3600) -> int:
    log.write("$ " + " ".join(argv) + "\n")
    log.flush()
    try:
        return subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.write(f"\n{exc}\n")
        return -1


def _build_docker(home: Path, src: Path, wd: Path, digest: str) -> None:
    targets = [LINUX_GNU, WINDOWS_GNU]
    notes = ["Built in Docker (" + BUILDER_IMAGE + ").", MACOS_NOTE]
    _write_status(home, {"state": "building", "hash": digest, "host": LINUX_GNU,
                         "notes": notes, "started_at": time.time(), "builder": "docker"})
    (wd / "docker-target").mkdir(exist_ok=True)
    (wd / "docker-cargo").mkdir(exist_ok=True)
    image = builder_image(src)
    artifacts: list[dict[str, Any]] = []
    errors: list[str] = []
    log_path = wd / "build.log"
    with log_path.open("w", encoding="utf-8") as log:
        have = subprocess.run(["docker", "image", "inspect", image],
                              capture_output=True).returncode == 0
        if not have:
            log.write(f"=== docker build {image}\n")
            if _logged(["docker", "build", "-t", image, str(dockerfile_dir(src))], log) != 0:
                errors.append(f"docker build {image} failed (see {log_path})")
                targets = []
        for triple in targets:
            log.write(f"=== cargo build --release --target {triple} (docker)\n")
            rc = _logged(docker_run_argv(src, wd, triple, image), log)
            built = wd / "docker-target" / triple / "release" / _exe_name(triple)
            if rc == 0 and built.is_file():
                dest = wd / "dist" / digest / triple
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(built, dest / built.name)
                artifacts.append({"target": triple, "platform": platform_of(triple),
                                  "filename": built.name})
            else:
                errors.append(f"{triple}: build exited with {rc} (see {log_path})")
    for old in (wd / "dist").glob("*"):
        if old.name != digest:
            shutil.rmtree(old, ignore_errors=True)
    _write_status(home, {
        "state": "ready" if artifacts else "failed",
        "hash": digest, "host": LINUX_GNU, "artifacts": artifacts, "notes": notes,
        "error": "; ".join(errors), "finished_at": time.time(), "builder": "docker",
    })


def start_background(home: Path | None = None, *, force: bool = False) -> bool:
    """Start a build thread unless one is running. Never blocks."""
    global _thread
    if os.environ.get("AUTONOMOUS_COMPANION_BUILD", "1") == "0" and not force:
        return False
    home = ensure_home(home)
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False

        def run() -> None:
            try:
                _build(home, force=force)
            except Exception as exc:  # never crash serve
                _write_status(home, {"state": "failed", "error": str(exc)})
            st = _read_status(home)
            print(
                f"[companion] build {st.get('state')}: "
                + ", ".join(a["target"] for a in st.get("artifacts") or [])
                + (f" ({st.get('error')})" if st.get("error") else ""),
                flush=True,
            )

        _thread = threading.Thread(target=run, name="companion-build", daemon=True)
        _thread.start()
    return True
