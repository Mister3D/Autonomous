"""Self-update: channel (main|dev), check cache 24h, apply + optional systemd restart.

Threat model: mono-user hub. Apply runs a fixed argv sequence (fetch / ff-only /
frontend build / pip install -e). No user-supplied shell. Restart uses
``systemctl`` when an ``autonomous.service`` unit is active.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.paths import ensure_home
from autonomous.services import settings as settings_svc
from autonomous.services.errors import Conflict, ValidationError

CHANNELS = ("main", "dev")
CACHE_TTL_S = 24 * 3600
CHANNEL_KEY = "update.channel"
CACHE_NAME = "update-check.json"
SERVICE_NAMES = (
    os.environ.get("AUTONOMOUS_SERVICE_NAME", "").strip(),
    "autonomous.service",
    "autonomous",
)

_MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")
_lock = threading.Lock()
_apply_running = False


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cache_path(home: Path | None) -> Path:
    return ensure_home(home) / CACHE_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(*args: str, timeout: float = 60.0, check: bool = False) -> subprocess.CompletedProcess[str]:
    root = _repo_root()
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def git_available() -> bool:
    if not (_repo_root() / ".git").exists():
        return False
    return shutil.which("git") is not None


def channel(home: Path | None = None) -> str:
    raw = str(settings_svc.get(CHANNEL_KEY, home=home, default="main") or "main").strip().lower()
    return raw if raw in CHANNELS else "main"


def _read_cache(home: Path | None) -> dict[str, Any] | None:
    path = _cache_path(home)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_cache(home: Path | None, data: dict[str, Any]) -> None:
    path = _cache_path(home)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def invalidate_cache(home: Path | None = None) -> None:
    path = _cache_path(home)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _rev_parse(ref: str) -> str | None:
    p = _git("rev-parse", "--verify", ref)
    if p.returncode != 0:
        return None
    return (p.stdout or "").strip() or None


def _short(sha: str | None) -> str:
    return (sha or "")[:12]


def _dirty() -> bool:
    p = _git("status", "--porcelain")
    return bool((p.stdout or "").strip())


def _migration_versions_in_tree(ref: str | None = None) -> set[int]:
    """Migration version ints present in the working tree or at ``ref``."""
    out: set[int] = set()
    if ref:
        p = _git("ls-tree", "-r", "--name-only", ref, "--", "autonomous/migrations")
        if p.returncode != 0:
            return out
        names = (p.stdout or "").splitlines()
    else:
        mig = _repo_root() / "autonomous" / "migrations"
        names = [f.name for f in mig.glob("*.sql")] if mig.is_dir() else []
    for name in names:
        base = Path(name).name
        m = _MIGRATION_RE.match(base)
        if m:
            out.add(int(m.group(1)))
    return out


def _applied_migrations(home: Path | None) -> set[int]:
    with get_db(home) as conn:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(r["version"]) for r in rows}


def can_switch_to(target: str, *, home: Path | None = None) -> dict[str, Any]:
    """Whether settings may change the update channel to ``target``."""
    target = (target or "").strip().lower()
    if target not in CHANNELS:
        raise ValidationError("channel must be main or dev", code="invalid_channel")
    current = channel(home)
    if target == current:
        return {"ok": True, "channel": target, "current": current}

    if not git_available():
        return {
            "ok": False,
            "code": "no_git",
            "message": "This install is not a git checkout; channel changes are unavailable.",
            "channel": target,
            "current": current,
        }

    # Fetch soft so origin/<target> exists when possible (best-effort).
    try:
        _git("fetch", "--quiet", "origin", target, timeout=45.0)
    except (OSError, subprocess.TimeoutExpired):
        pass

    ref = f"origin/{target}"
    if not _rev_parse(ref):
        # Fall back to local branch tip if origin missing.
        ref = target if _rev_parse(target) else ""
    if not ref:
        return {
            "ok": False,
            "code": "unknown_branch",
            "message": f"Branch {target} is not available on origin yet.",
            "channel": target,
            "current": current,
        }

    applied = _applied_migrations(home)
    target_migs = _migration_versions_in_tree(ref)
    # Also union working-tree files if we're already on that branch tip.
    if not target_migs:
        target_migs = _migration_versions_in_tree(None)
    extra = sorted(applied - target_migs)
    if extra:
        return {
            "ok": False,
            "code": "migrations_ahead",
            "message": (
                f"This database has migrations {extra} that are not on {target}. "
                "Stay on the current channel until that branch includes them "
                "(usually after a release merges into main)."
            ),
            "channel": target,
            "current": current,
            "extra_migrations": extra,
        }

    return {
        "ok": True,
        "channel": target,
        "current": current,
        "warning_dev": target == "dev",
    }


def set_channel(target: str, *, home: Path | None = None, confirm_dev: bool = False) -> dict[str, Any]:
    target = (target or "").strip().lower()
    gate = can_switch_to(target, home=home)
    if not gate.get("ok"):
        raise ValidationError(gate.get("message") or "cannot switch channel", code=gate.get("code") or "channel_blocked")
    if target == "dev" and channel(home) != "dev" and not confirm_dev:
        raise ValidationError(
            "Switching to dev requires confirm_dev=true (unstable + harder to return to main).",
            code="confirm_dev_required",
        )
    settings_svc.set_value(CHANNEL_KEY, target, home=home)
    invalidate_cache(home)
    return {"ok": True, "channel": target, "warning_dev": target == "dev"}


def _behind_count(local: str, remote: str) -> int:
    p = _git("rev-list", "--count", f"{local}..{remote}")
    if p.returncode != 0:
        return 0
    try:
        return int((p.stdout or "0").strip() or "0")
    except ValueError:
        return 0


def check(*, home: Path | None = None, force: bool = False) -> dict[str, Any]:
    """Return update status; refresh remote tip when cache expired or force=True."""
    ch = channel(home)
    cached = _read_cache(home)
    now = time.time()
    if (
        cached
        and not force
        and cached.get("channel") == ch
        and isinstance(cached.get("checked_at_epoch"), (int, float))
        and now - float(cached["checked_at_epoch"]) < CACHE_TTL_S
    ):
        return {**cached, "cached": True}

    base: dict[str, Any] = {
        "ok": True,
        "available": False,
        "channel": ch,
        "cached": False,
        "checked_at": _now_iso(),
        "checked_at_epoch": now,
        "local_sha": None,
        "remote_sha": None,
        "behind": 0,
        "dirty": False,
        "git": git_available(),
        "service_restart": _systemd_unit_active(),
        "message": None,
        "code": None,
    }

    if not git_available():
        base.update(
            ok=False,
            code="no_git",
            message="Not a git install — update from the UI is unavailable. Re-run install.sh from a clone.",
        )
        _write_cache(home, base)
        return base

    local = _rev_parse("HEAD")
    base["local_sha"] = local
    base["dirty"] = _dirty()

    try:
        fetch = _git("fetch", "--quiet", "origin", ch, timeout=90.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        base.update(ok=False, code="fetch_failed", message=str(exc)[:300])
        _write_cache(home, base)
        return base

    if fetch.returncode != 0:
        err = ((fetch.stderr or fetch.stdout or "git fetch failed")[:300]).strip()
        base.update(ok=False, code="fetch_failed", message=err)
        _write_cache(home, base)
        return base

    remote = _rev_parse(f"origin/{ch}") or _rev_parse(ch)
    base["remote_sha"] = remote
    if local and remote and local != remote:
        behind = _behind_count(local, remote)
        base["behind"] = behind
        base["available"] = behind > 0
        if behind == 0:
            # Local has commits remote doesn't (or diverge) — still offer update only if behind.
            base["message"] = "Local branch differs from origin; fast-forward update may not apply."
            base["code"] = "diverged"
    elif local and remote and local == remote:
        base["available"] = False
        base["behind"] = 0

    if base["dirty"] and base["available"]:
        base["message"] = "Working tree has local changes — update will be refused until it is clean."
        base["code"] = "dirty"

    _write_cache(home, base)
    return base


def status(*, home: Path | None = None, force: bool = False) -> dict[str, Any]:
    st = check(home=home, force=force)
    st["channels"] = list(CHANNELS)
    st["can_switch"] = {
        c: can_switch_to(c, home=home) for c in CHANNELS if c != channel(home)
    }
    with _lock:
        st["applying"] = _apply_running
    return st


def _systemd_unit_active() -> str | None:
    if not shutil.which("systemctl"):
        return None
    for name in SERVICE_NAMES:
        if not name:
            continue
        for argv in (
            ["systemctl", "is-active", "--quiet", name],
            ["systemctl", "--user", "is-active", "--quiet", name],
        ):
            try:
                p = subprocess.run(argv, capture_output=True, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if p.returncode == 0:
                return name
    return None


def _schedule_systemd_restart(unit: str, log) -> None:
    """Restart after the HTTP response / job log flush. Prefer non-interactive sudo."""

    def worker() -> None:
        time.sleep(2.0)
        attempts = [
            ["systemctl", "restart", unit],
            ["systemctl", "--user", "restart", unit],
            ["sudo", "-n", "systemctl", "restart", unit],
        ]
        for argv in attempts:
            try:
                p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as exc:
                log(f"restart attempt failed ({' '.join(argv)}): {exc}")
                continue
            if p.returncode == 0:
                log(f"restarted via {' '.join(argv)}")
                return
            err = (p.stderr or p.stdout or "").strip()[:200]
            log(f"restart refused ({' '.join(argv)}): {err or p.returncode}")
        log("Could not restart automatically — restart autonomous serve / systemctl manually.")

    threading.Thread(target=worker, name="autonomous-restart", daemon=True).start()


def _stream_argv(job_id: str, argv: list[str], home: Path | None) -> int:
    from autonomous.services import jobs as jobs_svc

    env = os.environ.copy()
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    jobs_svc.update_job(job_id, log_line="$ " + " ".join(argv), home=home)
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(_repo_root()),
    )
    assert proc.stdout is not None
    last = 0.0
    buf: list[str] = []
    for line in proc.stdout:
        buf.append(line.rstrip()[:500])
        if time.monotonic() - last > 0.4:
            for b in buf:
                jobs_svc.update_job(job_id, log_line=b, home=home)
            buf.clear()
            last = time.monotonic()
    for b in buf:
        jobs_svc.update_job(job_id, log_line=b, home=home)
    return proc.wait()


def start_apply(*, home: Path | None = None) -> dict[str, Any]:
    """Pull the configured channel, rebuild UI + package, restart when possible."""
    global _apply_running
    from autonomous.services import jobs as jobs_svc
    from autonomous.services import setup as setup_svc

    if not git_available():
        raise ValidationError("Not a git install", code="no_git")
    if _dirty():
        raise ValidationError(
            "Working tree has local changes — commit, stash or discard them before updating.",
            code="dirty",
        )

    ch = channel(home)
    with _lock:
        if _apply_running:
            raise Conflict("an update is already running", code="update_running")
        _apply_running = True

    job = jobs_svc.create_job(setup_svc.SETUP_BOT, "setup.self_update", home=home)

    def log(line: str) -> None:
        jobs_svc.update_job(job["id"], log_line=line[:500], home=home)

    def worker() -> None:
        global _apply_running
        root = _repo_root()
        try:
            jobs_svc.update_job(job["id"], state="running", progress=5, home=home)
            log(f"Updating channel={ch}")
            steps: list[tuple[str, list[str]]] = [
                ("fetch", ["git", "-C", str(root), "fetch", "origin", ch]),
                ("checkout", ["git", "-C", str(root), "checkout", "-q", ch]),
                (
                    "ff-only",
                    ["git", "-C", str(root), "merge", "-q", "--ff-only", f"origin/{ch}"],
                ),
            ]
            for label, argv in steps:
                jobs_svc.update_job(job["id"], progress=15, home=home)
                rc = _stream_argv(job["id"], argv, home)
                if rc != 0:
                    raise RuntimeError(f"{label} failed (exit {rc})")

            venv_python = root / ".venv" / "bin" / "python"
            npm = shutil.which("npm")
            if not npm:
                raise RuntimeError("npm not found")
            if not (root / ".venv" / "bin" / "pip").is_file() and not venv_python.is_file():
                raise RuntimeError(".venv missing — re-run install.sh")

            jobs_svc.update_job(job["id"], progress=40, home=home)
            env = os.environ.copy()
            frontend = root / "frontend"
            for label, argv in (
                ("npm ci", [npm, "ci", "--no-audit", "--no-fund", "--loglevel=error"]),
                ("npm run build", [npm, "run", "build", "--silent"]),
            ):
                log(f"$ cd frontend && {' '.join(argv)}")
                proc = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=str(frontend),
                    env=env,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    log(line.rstrip()[:500])
                rc = proc.wait()
                if rc != 0:
                    raise RuntimeError(f"{label} failed (exit {rc})")

            jobs_svc.update_job(job["id"], progress=75, home=home)
            py = str(venv_python if venv_python.is_file() else sys.executable)
            rc = _stream_argv(
                job["id"],
                [py, "-m", "pip", "install", "-q", "-e", str(root)],
                home,
            )
            if rc != 0:
                raise RuntimeError(f"pip install failed (exit {rc})")

            invalidate_cache(home)
            # Refresh check snapshot after update.
            try:
                check(home=home, force=True)
            except Exception:  # noqa: BLE001
                pass

            unit = _systemd_unit_active()
            if unit:
                log(f"Scheduling restart of {unit}…")
                _schedule_systemd_restart(unit, log)
                jobs_svc.update_job(
                    job["id"],
                    state="done",
                    progress=100,
                    log_line="✓ update applied — service restarting",
                    home=home,
                )
            else:
                log("No active autonomous.service — restart `autonomous serve` manually.")
                jobs_svc.update_job(
                    job["id"],
                    state="done",
                    progress=100,
                    log_line="✓ update applied — restart the process manually",
                    home=home,
                )
        except Exception as exc:  # noqa: BLE001
            try:
                jobs_svc.update_job(
                    job["id"],
                    state="failed",
                    progress=100,
                    error=str(exc)[:300],
                    log_line=f"✗ {exc}",
                    home=home,
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            with _lock:
                _apply_running = False

    threading.Thread(target=worker, name="self-update", daemon=True).start()
    return jobs_svc.get_job(job["id"], home=home)
