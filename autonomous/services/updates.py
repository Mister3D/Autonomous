"""Self-update: branch + optional remote URL, check cache 24h, apply + systemd restart.

Threat model: mono-user hub. Apply runs a fixed argv sequence (fetch / ff-only /
frontend build / pip install -e). No user-supplied shell. Restart uses
``systemctl`` when an ``autonomous.service`` unit is active.

Presets ``main`` / ``dev`` remain; any other valid branch name is allowed (forks).
``update.remote_url`` points fetches at a dedicated ``updates`` remote when set.
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

CHANNELS = ("main", "dev")  # UI presets; channel() also accepts custom branches
CACHE_TTL_S = 24 * 3600
CHANNEL_KEY = "update.channel"
REMOTE_URL_KEY = "update.remote_url"
UPDATES_REMOTE = "updates"
CACHE_NAME = "update-check.json"
SERVICE_NAMES = (
    os.environ.get("AUTONOMOUS_SERVICE_NAME", "").strip(),
    "autonomous.service",
    "autonomous",
)

_MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")
# 001_schema.sql replaced the old incremental files 1..22. A branch that
# still has that squash already contains this schema; those version ints
# must not look like the database is ahead of the branch.
_SQUASH_THROUGH = 22
_VERSION_RE = re.compile(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", re.M)
# Safe git branch / ref name (no shell metacharacters, no path escape).
_BRANCH_RE = re.compile(r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
# https / ssh only — http:// and git:// are rejected (cleartext / unauthenticated).
_REMOTE_URL_RE = re.compile(
    r"^(https://|ssh://|git@)[^\s\"'`;|&$<>]+$",
    re.IGNORECASE,
)
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


def version_in_source(text: str) -> str:
    match = _VERSION_RE.search(text or "")
    return match.group(1).strip() if match else ""


def _version_at(rev: str) -> str:
    """``__version__`` at a git revision, or empty when the file cannot be read."""
    rev = str(rev or "").strip()
    if not rev or not git_available():
        return ""
    try:
        proc = _git("show", f"{rev}:autonomous/__init__.py", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return version_in_source(proc.stdout or "")


def git_available() -> bool:
    if not (_repo_root() / ".git").exists():
        return False
    return shutil.which("git") is not None


def normalize_branch(raw: str | None) -> str:
    name = str(raw or "").strip()
    # Keep case for custom branches (Feature/foo); presets lowercased.
    if name.lower() in CHANNELS:
        return name.lower()
    if not name or not _BRANCH_RE.match(name):
        raise ValidationError(
            "Invalid branch name (letters, digits, . _ / - ; no '..')",
            code="invalid_channel",
        )
    return name


def channel(home: Path | None = None) -> str:
    raw = str(settings_svc.get(CHANNEL_KEY, home=home, default="main") or "main").strip()
    try:
        return normalize_branch(raw)
    except ValidationError:
        return "main"


def normalize_remote_url(raw: str | None) -> str:
    url = str(raw or "").strip()
    if not url:
        return ""
    if not _REMOTE_URL_RE.match(url):
        raise ValidationError(
            "Remote URL must be https://, ssh://, or git@… (http:// and git:// rejected)",
            code="invalid_remote_url",
        )
    if len(url) > 500:
        raise ValidationError("Remote URL too long", code="invalid_remote_url")
    return url


def remote_url(home: Path | None = None) -> str:
    raw = settings_svc.get(REMOTE_URL_KEY, home=home, default="")
    try:
        return normalize_remote_url(raw if isinstance(raw, str) else str(raw or ""))
    except ValidationError:
        return ""


def _remote_url_configured(home: Path | None) -> str:
    return remote_url(home)


def _git_remote_get_url(name: str) -> str | None:
    p = _git("remote", "get-url", name)
    if p.returncode != 0:
        return None
    return (p.stdout or "").strip() or None


def origin_url() -> str | None:
    return _git_remote_get_url("origin")


def _ensure_updates_remote(url: str) -> None:
    """Point the dedicated ``updates`` remote at ``url`` (add or set-url)."""
    current = _git_remote_get_url(UPDATES_REMOTE)
    if current is None:
        p = _git("remote", "add", UPDATES_REMOTE, url)
    elif current != url:
        p = _git("remote", "set-url", UPDATES_REMOTE, url)
    else:
        return
    if p.returncode != 0:
        err = ((p.stderr or p.stdout or "git remote failed")[:300]).strip()
        raise ValidationError(err or "Could not configure updates remote", code="remote_config_failed")


def _fetch_remote_name(home: Path | None) -> str:
    """Remote name used for fetch/merge: ``updates`` when a URL is set, else ``origin``."""
    url = _remote_url_configured(home)
    if url:
        _ensure_updates_remote(url)
        return UPDATES_REMOTE
    return "origin"


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
    """Whether settings may change the update branch to ``target``."""
    target = normalize_branch(target)
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

    remote = _fetch_remote_name(home)
    # Soft fetch so remote/<target> exists when possible (best-effort).
    try:
        _git("fetch", "--quiet", remote, target, timeout=45.0)
    except (OSError, subprocess.TimeoutExpired):
        pass

    ref = f"{remote}/{target}"
    if not _rev_parse(ref):
        # Fall back to local branch tip if remote missing.
        ref = target if _rev_parse(target) else ""
    if not ref:
        return {
            "ok": False,
            "code": "unknown_branch",
            "message": f"Branch {target} is not available on {remote} yet.",
            "channel": target,
            "current": current,
        }

    applied = _applied_migrations(home)
    target_migs = _migration_versions_in_tree(ref)
    # Also union working-tree files if we're already on that branch tip.
    if not target_migs:
        target_migs = _migration_versions_in_tree(None)
    covered = set(target_migs)
    if 1 in covered:
        covered.update(v for v in applied if v <= _SQUASH_THROUGH)
    extra = sorted(applied - covered)
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
        "warning_dev": target != "main",
    }


def set_channel(target: str, *, home: Path | None = None, confirm_dev: bool = False) -> dict[str, Any]:
    target = normalize_branch(target)
    gate = can_switch_to(target, home=home)
    if not gate.get("ok"):
        raise ValidationError(gate.get("message") or "cannot switch channel", code=gate.get("code") or "channel_blocked")
    # Leaving main for any other branch (dev or custom) needs an explicit confirm.
    if target != "main" and channel(home) != target and not confirm_dev:
        raise ValidationError(
            "Switching away from main requires confirm_dev=true (unstable + harder to return).",
            code="confirm_dev_required",
        )
    settings_svc.set_value(CHANNEL_KEY, target, home=home)
    invalidate_cache(home)
    return {"ok": True, "channel": target, "warning_dev": target != "main"}


def set_remote_url(url: str | None, *, home: Path | None = None) -> dict[str, Any]:
    """Set or clear the self-update remote URL (empty → use origin)."""
    cleaned = normalize_remote_url(url)
    settings_svc.set_value(REMOTE_URL_KEY, cleaned, home=home)
    if cleaned and git_available():
        _ensure_updates_remote(cleaned)
    invalidate_cache(home)
    return {
        "ok": True,
        "remote_url": cleaned,
        "origin_url": origin_url() if git_available() else None,
    }


def configure(
    *,
    home: Path | None = None,
    branch: str | None = None,
    remote_url_value: str | None = None,
    set_remote: bool = False,
    confirm_dev: bool = False,
) -> dict[str, Any]:
    """Update branch and/or remote URL from PUT /setup/update."""
    out: dict[str, Any] = {"ok": True}
    if set_remote:
        out.update(set_remote_url(remote_url_value, home=home))
    if branch is not None and str(branch).strip() != "":
        out.update(set_channel(branch, home=home, confirm_dev=confirm_dev))
    out["channel"] = channel(home)
    out["remote_url"] = remote_url(home)
    out["origin_url"] = origin_url() if git_available() else None
    return out


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    """True when ``ancestor`` is contained in ``descendant`` (a fast-forward is possible)."""
    return _git("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


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
    url = remote_url(home)
    cached = _read_cache(home)
    now = time.time()
    if (
        cached
        and not force
        and cached.get("channel") == ch
        and cached.get("remote_url") == url
        and isinstance(cached.get("checked_at_epoch"), (int, float))
        and now - float(cached["checked_at_epoch"]) < CACHE_TTL_S
    ):
        return {**cached, "cached": True}

    base: dict[str, Any] = {
        "ok": True,
        "available": False,
        "channel": ch,
        "remote_url": url,
        "origin_url": None,
        "fetch_remote": "origin",
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

    base["origin_url"] = origin_url()
    local = _rev_parse("HEAD")
    base["local_sha"] = local
    base["dirty"] = _dirty()

    try:
        remote_name = _fetch_remote_name(home)
    except ValidationError as exc:
        base.update(ok=False, code=exc.code or "remote_config_failed", message=exc.message)
        _write_cache(home, base)
        return base
    base["fetch_remote"] = remote_name

    try:
        fetch = _git("fetch", "--quiet", remote_name, ch, timeout=90.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        base.update(
            ok=False,
            code="fetch_failed",
            message=(str(exc) or "Could not reach the remote.")[:300],
        )
        _write_cache(home, base)
        return base

    if fetch.returncode != 0:
        err = ((fetch.stderr or fetch.stdout or "git fetch failed")[:300]).strip()
        base.update(ok=False, code="fetch_failed", message=err)
        _write_cache(home, base)
        return base

    remote_sha = _rev_parse(f"{remote_name}/{ch}") or _rev_parse(ch)
    base["remote_sha"] = remote_sha
    if local and remote_sha and local != remote_sha:
        behind = _behind_count(local, remote_sha)
        base["behind"] = behind
        if _is_ancestor(local, remote_sha):
            base["available"] = behind > 0
        else:
            # Remote history was rewritten (force-push). A fast-forward cannot apply.
            # Commits on the remote still count as an update; apply resets to that tip.
            base["code"] = "diverged"
            base["available"] = behind > 0
            base["message"] = (
                "Remote history was rewritten. Update will match the remote tip."
            )
    elif local and remote_sha and local == remote_sha:
        base["available"] = False
        base["behind"] = 0

    if base["dirty"] and base["available"]:
        base["message"] = "Working tree has local changes — update will be refused until it is clean."
        base["code"] = "dirty"

    _write_cache(home, base)
    return base


def status(*, home: Path | None = None, force: bool = False) -> dict[str, Any]:
    from autonomous import __version__ as app_version

    st = check(home=home, force=force)
    st["channels"] = list(CHANNELS)
    st["version"] = app_version
    remote_version = ""
    if st.get("git") is not False and st.get("remote_sha"):
        remote_version = _version_at(str(st.get("remote_sha") or ""))
    st["latest_version"] = remote_version or app_version
    st["remote_url"] = remote_url(home)
    st["origin_url"] = origin_url() if git_available() else None
    current = channel(home)
    st["can_switch"] = {
        c: can_switch_to(c, home=home) for c in CHANNELS if c != current
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
                log("Restart attempt failed.")
                continue
            if p.returncode == 0:
                log("Service restarted.")
                return
            log("Restart was refused.")
        log("Could not restart automatically — restart autonomous serve / systemctl manually.")

    threading.Thread(target=worker, name="autonomous-restart", daemon=True).start()


def _stream_argv(
    job_id: str,
    argv: list[str],
    home: Path | None,
    *,
    cwd: str | None = None,
) -> int:
    from autonomous.services import jobs as jobs_svc

    env = os.environ.copy()
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    jobs_svc.update_job(job_id, log_line=("$ " + " ".join(argv))[:500], home=home)
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=cwd or str(_repo_root()),
    )
    assert proc.stdout is not None
    last = 0.0
    buf: list[str] = []
    for line in proc.stdout:
        shown = line.rstrip()[:500]
        if shown:
            buf.append(shown)
        if time.monotonic() - last > 0.4:
            for b in buf:
                jobs_svc.update_job(job_id, log_line=b, home=home)
            buf.clear()
            last = time.monotonic()
    for b in buf:
        jobs_svc.update_job(job_id, log_line=b, home=home)
    return proc.wait()


def sync_steps(
    remote_name: str,
    branch: str,
    *,
    force: bool,
    match_remote: bool = False,
) -> list[tuple[str, list[str]]]:
    """Fixed git argv. Force discards local commits and tracked edits, then matches the remote tip.

    ``match_remote`` is the rewritten-history path: same branch reset, without deleting
    untracked files.
    """
    root = str(_repo_root())
    tip = f"{remote_name}/{branch}"
    steps: list[tuple[str, list[str]]] = [
        ("fetch", ["git", "-C", root, "fetch", remote_name, branch]),
    ]
    if force or match_remote:
        if force:
            # Untracked files (not ignored ones: data/, .venv, node_modules stay).
            steps.append(("clean", ["git", "-C", root, "clean", "-fd"]))
        steps.append(("reset", ["git", "-C", root, "checkout", "-f", "-B", branch, tip]))
        return steps
    if _git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode != 0:
        steps.append(("branch", ["git", "-C", root, "branch", "--track", branch, tip]))
    steps.extend(
        [
            ("checkout", ["git", "-C", root, "checkout", "-q", branch]),
            ("ff-only", ["git", "-C", root, "merge", "-q", "--ff-only", tip]),
        ]
    )
    return steps


def start_apply(*, home: Path | None = None, force: bool = False) -> dict[str, Any]:
    """Pull the configured channel, rebuild UI + package, restart when possible.

    ``force`` replaces the local branch with the remote tip (dirty tree, amended
    commit, or any other history that cannot fast-forward).
    """
    global _apply_running
    from autonomous.services import jobs as jobs_svc
    from autonomous.services import setup as setup_svc

    if not git_available():
        raise ValidationError("Not a git install", code="no_git")
    if _dirty() and not force:
        raise ValidationError(
            "Working tree has local changes — commit, stash or discard them before updating.",
            code="dirty",
        )

    ch = channel(home)
    remote_name = _fetch_remote_name(home)
    with _lock:
        if _apply_running:
            raise Conflict("an update is already running", code="update_running")
        _apply_running = True

    job = jobs_svc.create_job(setup_svc.SETUP_BOT, "setup.self_update", home=home)

    def log(line: str) -> None:
        text = str(line or "").rstrip()
        if text:
            jobs_svc.update_job(job["id"], log_line=text[:500], home=home)

    def worker() -> None:
        global _apply_running
        root = _repo_root()
        try:
            jobs_svc.update_job(job["id"], state="running", progress=5, home=home)
            log(f"Updating channel={ch} remote={remote_name} force={force}")
            planned = sync_steps(remote_name, ch, force=force)
            index = 0
            while index < len(planned):
                label, argv = planned[index]
                jobs_svc.update_job(job["id"], progress=15, home=home)
                rc = _stream_argv(job["id"], argv, home)
                if rc != 0:
                    raise RuntimeError(f"{label} failed (exit {rc})")
                if label == "fetch" and not force:
                    local = _rev_parse("HEAD")
                    tip = _rev_parse(f"{remote_name}/{ch}")
                    if (
                        local
                        and tip
                        and local != tip
                        and not _is_ancestor(local, tip)
                    ):
                        log("The remote branch was rewritten. Matching its tip.")
                        planned = [
                            step
                            for step in sync_steps(
                                remote_name, ch, force=False, match_remote=True
                            )
                            if step[0] != "fetch"
                        ]
                        index = 0
                        continue
                index += 1

            venv_python = root / ".venv" / "bin" / "python"
            npm = shutil.which("npm")
            if not npm:
                raise RuntimeError("npm not found")
            if not (root / ".venv" / "bin" / "pip").is_file() and not venv_python.is_file():
                raise RuntimeError(".venv missing — re-run install.sh")

            jobs_svc.update_job(job["id"], progress=40, home=home)
            frontend = root / "frontend"
            for label, argv in (
                ("npm ci", [npm, "ci", "--no-audit", "--no-fund", "--loglevel=error"]),
                ("npm run build", [npm, "run", "build", "--silent"]),
            ):
                rc = _stream_argv(job["id"], argv, home, cwd=str(frontend))
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
                log("Restarting the service…")
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
