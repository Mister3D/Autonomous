"""First-run setup: readiness checks + whitelisted install jobs.

``status()`` lists what is left to configure. ``ready`` is True when every
*required* check is ``ok``; bot creation is refused (409) until then.

Install jobs run a fixed argv chosen from :data:`JOB_COMMANDS` — never a
user-provided command — one job per kind at a time, logged in the ``jobs``
table (``bot = "_setup"``) so the UI can poll ``/jobs/<id>``.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from autonomous.services import settings as settings_svc
from autonomous.services.errors import AutonomousError, Conflict, ValidationError

SETUP_BOT = "_setup"
CACHE_TTL = 10.0
DOCKER_INSTALL_CMD = "curl -fsSL https://get.docker.com | sh"
PI_PACKAGE = "@earendil-works/pi-coding-agent"

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()
_jobs_lock = threading.Lock()
_running: dict[str, str] = {}  # kind -> job id


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def gate_enabled(home: Path | None = None) -> bool:
    """Setup gate only applies to the real Pi backend (tests use ``null``)."""
    if os.environ.get("AUTONOMOUS_SETUP_GATE", "1") == "0":
        return False
    backend = str(settings_svc.get("agent_backend", home=home, default="pi") or "pi")
    return backend == "pi"


def _check(cid: str, *, required: bool, status: str, details: str = "",
           action: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "label": f"setup.check.{cid}",
        "required": required,
        "status": status,
        "details": details,
        "action": action,
        **extra,
    }


def _link(section: str) -> dict[str, Any]:
    return {"type": "link", "to": f"/settings/{section}"}


def _job_action(kind: str) -> dict[str, Any]:
    act: dict[str, Any] = {"type": "job", "job": kind}
    jid = _running.get(kind)
    if jid:
        act["job_id"] = jid
    return act


def _run(argv: list[str], timeout: float = 10.0) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "not found"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)[:200]
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


# ── individual checks ─────────────────────────────────────────────────────


def check_pi() -> dict[str, Any]:
    from autonomous.services import pi_status

    binary = pi_status.resolve_pi_bin()
    if not binary:
        return _check("pi", required=True, status="running" if "pi_install" in _running else "missing",
                      details="pi CLI not found (npm install -g " + PI_PACKAGE + ")",
                      action=_job_action("pi_install") if shutil.which("npm") else
                      {"type": "command", "command": "Install Node.js ≥ 20 (npm), then: npm install -g " + PI_PACKAGE})
    version = pi_status.pi_version(binary) or "?"
    return _check("pi", required=True, status="ok", details=f"pi {version}", version=version)


def check_llm() -> dict[str, Any]:
    from autonomous.services import setup_config as cfg

    try:
        provs = cfg.llm_providers()
    except AutonomousError as exc:
        return _check("llm", required=True, status="error", details=exc.message, action=_link("llm"))
    if not provs:
        return _check("llm", required=True, status="missing",
                      details="No LLM provider configured", action=_link("llm"))
    problems: list[str] = []
    for prov in provs:
        if not prov["models"]:
            problems.append(f"{prov['provider']}: no model")
            continue
        raw = cfg._read_models_json()["providers"][prov["provider"]].get("apiKey")
        key, source = cfg.resolve_api_key(raw)
        if source == "command":
            # Can't test without running the user's command: trust it.
            ok_model = next((m for m in prov["models"] if m["images"]), None)
            if ok_model:
                return _check("llm", required=True, status="ok",
                              details=f"{prov['provider']}/{ok_model['id']} (key via command, not tested)",
                              action=_link("llm"))
        r = cfg.list_remote_models(prov["base_url"], key)
        if not r["ok"]:
            problems.append(f"{prov['provider']}: {r['error']}")
            continue
        img = [m for m in prov["models"] if m["images"]]
        if not img:
            problems.append(f"{prov['provider']}: model does not accept images")
            continue
        served = set(r["models"])
        pick = next((m for m in img if not served or m["id"] in served), None)
        if pick is None:
            problems.append(f"{prov['provider']}: {img[0]['id']} not served")
            continue
        return _check("llm", required=True, status="ok",
                      details=f"{prov['provider']}/{pick['id']} · images ✓", action=_link("llm"))
    return _check("llm", required=True, status="error", details="; ".join(problems)[:400],
                  action=_link("llm"))


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _debian_like() -> bool:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return any(x in text for x in ("id=debian", "id=ubuntu", "id_like=debian", "id_like=ubuntu"))


def docker_install_allowed() -> bool:
    return platform.system() == "Linux" and _is_root() and _debian_like()


def check_docker() -> dict[str, Any]:
    if not shutil.which("docker"):
        action = (_job_action("docker_install") if docker_install_allowed()
                  else {"type": "command", "command": DOCKER_INSTALL_CMD})
        return _check("docker", required=True,
                      status="running" if "docker_install" in _running else "missing",
                      details="docker CLI not found", action=action)
    rc, out = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=10)
    if rc != 0:
        return _check("docker", required=True, status="error",
                      details=(out.splitlines() or ["docker daemon unreachable"])[-1][:300],
                      action={"type": "command", "command": "systemctl start docker"})
    return _check("docker", required=True, status="ok", details=f"Docker {out.splitlines()[0]}")


def check_desk_image(home: Path | None, docker_ok: bool) -> dict[str, Any]:
    from autonomous.services import desk_image_build as desk_build

    image = str(settings_svc.get("desktop_image", home=home) or "autonomous-desktop:latest")
    if "desk_image" in _running:
        return _check("desk_image", required=True, status="running", details=image,
                      action=_job_action("desk_image"))
    if not docker_ok:
        return _check("desk_image", required=True, status="missing",
                      details=f"{image} (Docker first)", action=None)
    st = desk_build.status(home)
    if st.get("state") == "building":
        return _check(
            "desk_image",
            required=True,
            status="running",
            details=f"{image} building (~10 min)",
            action=_job_action("desk_image"),
        )
    if st.get("state") == "failed" or st.get("error"):
        return _check(
            "desk_image",
            required=True,
            status="error",
            details=str(st.get("error") or "build failed")[:300],
            action=_job_action("desk_image"),
        )
    if not st.get("present"):
        return _check("desk_image", required=True, status="missing",
                      details=f"{image} not built", action=_job_action("desk_image"))
    detail = image + (" (update available)" if st.get("stale") else "")
    return _check("desk_image", required=True, status="ok", details=detail,
                  action=_job_action("desk_image") | {"rebuild": True})


def check_grounding(home: Path | None) -> list[dict[str, Any]]:
    from autonomous.services import grounding as g_svc
    from autonomous.services import setup_config as cfg

    out: list[dict[str, Any]] = []
    g = g_svc.grounder_config(home)
    if not g["base_url"]:
        out.append(_check("grounding", required=False, status="optional",
                          details="Off (UI-TARS not configured)", action=_link("grounding")))
    else:
        r = cfg.list_remote_models(g["base_url"], g["api_key"])
        if r["ok"] and g["model"] and r["models"] and g["model"] not in r["models"]:
            r = {**r, "ok": False, "error": "model_not_served"}
        out.append(_check("grounding", required=False, status="ok" if r["ok"] else "error",
                          details=g["model"] if r["ok"] else f"{g['model']}: {r['error']}",
                          action=_link("grounding")))
    return out


def check_companion(home: Path | None) -> dict[str, Any]:
    from autonomous.services import companion_build as build_svc

    st = build_svc.status(home)
    state = st.get("state")
    plats = ", ".join(sorted({a.get("platform", a.get("target", "")) for a in st["artifacts"]}))
    if state == "building":
        return _check("companion", required=False, status="running", details="building…",
                      action=_link("companions"))
    if st["artifacts"]:
        return _check("companion", required=False, status="ok",
                      details=f"v{st.get('version')} · {plats}" + (" (stale)" if st.get("stale") else "")
                      + (f" · {st.get('builder')}" if st.get("builder") else ""),
                      action=_job_action("companion") | {"rebuild": True, "to": "/settings/companions"})
    if state == "no_toolchain":
        return _check("companion", required=False, status="optional",
                      details="Neither Docker nor a Rust toolchain is available",
                      action={"type": "command", "command": st.get("rustup_hint") or ""})
    if state in ("error", "failed") or st.get("error"):
        detail = st.get("error") or "; ".join(st.get("notes") or [])
        return _check("companion", required=False, status="error", details=str(detail)[:300],
                      action=_job_action("companion"))
    return _check("companion", required=False, status="optional", details=str(state or "not built"),
                  action=_job_action("companion"))


# ── aggregate ─────────────────────────────────────────────────────────────


def compute(home: Path | None = None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for fn in (check_pi, check_llm, check_docker):
        try:
            checks.append(fn())
        except Exception as exc:  # noqa: BLE001 — a broken check must not 500 the page
            checks.append(_check(fn.__name__[6:], required=True, status="error", details=str(exc)[:300]))
    docker_ok = checks[-1]["status"] == "ok"
    checks.append(check_desk_image(home, docker_ok))
    for fn in (lambda: check_grounding(home), lambda: [check_companion(home)]):
        try:
            checks.extend(fn())
        except Exception as exc:  # noqa: BLE001
            checks.append(_check("optional", required=False, status="error", details=str(exc)[:300]))
    ready = all(c["status"] == "ok" for c in checks if c["required"])
    return {
        "ready": ready,
        "gate": gate_enabled(home),
        "checks": checks,
        "jobs": dict(_running),
        "checked_at": time.time(),
    }


def status(home: Path | None = None, *, force: bool = False) -> dict[str, Any]:
    key = str(home or "")
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not force and now - hit[0] < CACHE_TTL:
            return hit[1]
    res = compute(home)
    with _cache_lock:
        _cache[key] = (time.monotonic(), res)
    return res


def invalidate() -> None:
    with _cache_lock:
        _cache.clear()


def ensure_ready(home: Path | None = None) -> None:
    """Raise 409 when the gate applies and setup is not finished."""
    if not gate_enabled(home):
        return
    st = status(home)
    if st["ready"]:
        return
    missing = [c["id"] for c in st["checks"] if c["required"] and c["status"] != "ok"]
    raise Conflict(
        "Setup is not finished (" + ", ".join(missing) + "). Open / to complete it.",
        code="setup_incomplete",
    )


# ── whitelisted jobs ──────────────────────────────────────────────────────


def _desk_build_argv(home: Path | None) -> list[str]:
    image = str(settings_svc.get("desktop_image", home=home) or "autonomous-desktop:latest")
    return ["docker", "build", "-t", image, str(_repo_root() / "docker" / "desktop")]


JOB_COMMANDS: dict[str, Callable[[Path | None], list[str] | None]] = {
    "pi_install": lambda home: ["npm", "install", "-g", "--ignore-scripts", PI_PACKAGE],
    "desk_image": _desk_build_argv,
    "docker_install": lambda home: ["sh", "-c", DOCKER_INSTALL_CMD],
    "companion": lambda home: None,  # in-process builder (companion_build)
}


def _stream(job_id: str, argv: list[str], home: Path | None) -> int:
    from autonomous.services import jobs as jobs_svc

    env = os.environ.copy()
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, env=env, cwd=str(_repo_root()))
    assert proc.stdout is not None
    last = 0.0
    buf: list[str] = []
    for line in proc.stdout:
        buf.append(line.rstrip()[:500])
        if time.monotonic() - last > 0.5:
            for b in buf:
                jobs_svc.update_job(job_id, log_line=b, home=home)
            buf.clear()
            last = time.monotonic()
    for b in buf:
        jobs_svc.update_job(job_id, log_line=b, home=home)
    return proc.wait()


def _companion_job(job_id: str, home: Path | None) -> int:
    from autonomous.services import companion_build as build_svc
    from autonomous.services import jobs as jobs_svc

    build_svc.start_background(home, force=True)
    time.sleep(1.5)
    seen = 0
    log_path = build_svc.work_dir(home) / "build.log"
    offset = 0

    def pump() -> None:
        nonlocal offset
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(offset)
                chunk = fh.read()
                offset = fh.tell()
        except OSError:
            return
        for line in chunk.splitlines():
            if line.strip():
                jobs_svc.update_job(job_id, log_line=line.rstrip()[:500], home=home)

    while True:
        pump()
        st = build_svc.status(home)
        notes = st.get("notes") or []
        for n in notes[seen:]:
            jobs_svc.update_job(job_id, log_line=str(n)[:500], home=home)
        seen = len(notes)
        if st["state"] != "building":
            pump()
            break
        time.sleep(1.0)
    if st.get("error"):
        jobs_svc.update_job(job_id, log_line=str(st["error"])[:500], home=home)
    return 0 if st.get("artifacts") and not st.get("error") else 1


def start_job(kind: str, home: Path | None = None) -> dict[str, Any]:
    from autonomous.services import jobs as jobs_svc

    if kind not in JOB_COMMANDS:
        raise ValidationError(f"unknown setup job: {kind}", code="unknown_job")
    if kind == "docker_install" and not docker_install_allowed():
        raise ValidationError(
            "Docker can only be installed from the UI as root on Debian/Ubuntu. Run: " + DOCKER_INSTALL_CMD,
            code="docker_install_unsupported",
        )
    if kind == "pi_install" and not shutil.which("npm"):
        raise ValidationError("npm not found: install Node.js ≥ 20 first", code="npm_missing")
    with _jobs_lock:
        if kind in _running:
            raise Conflict(f"a {kind} job is already running", code="job_running")
        job = jobs_svc.create_job(SETUP_BOT, f"setup.{kind}", home=home)
        _running[kind] = job["id"]
    argv = JOB_COMMANDS[kind](home)

    def worker() -> None:
        try:
            jobs_svc.update_job(job["id"], state="running", progress=5,
                                log_line="$ " + (" ".join(argv) if argv else "companion build"), home=home)
            rc = _companion_job(job["id"], home) if argv is None else _stream(job["id"], argv, home)
            if rc == 0:
                jobs_svc.update_job(job["id"], state="done", progress=100, log_line="✓ done", home=home)
            else:
                jobs_svc.update_job(job["id"], state="failed", progress=100,
                                    error=f"exit code {rc}", log_line=f"✗ exit code {rc}", home=home)
        except Exception as exc:  # noqa: BLE001
            try:
                jobs_svc.update_job(job["id"], state="failed", error=str(exc)[:300], home=home)
            except Exception:  # noqa: BLE001
                pass
        finally:
            with _jobs_lock:
                _running.pop(kind, None)
            invalidate()

    threading.Thread(target=worker, name=f"setup-{kind}", daemon=True).start()
    invalidate()
    return jobs_svc.get_job(job["id"], home=home)
