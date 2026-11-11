"""Desktop VM orchestration via Docker."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.paths import bot_dir
from autonomous.services import bots as bots_svc
from autonomous.services import jobs as jobs_svc
from autonomous.services import settings as settings_svc
from autonomous.services.errors import AutonomousError, ValidationError
from autonomous.services.events import BUS

_LABEL = "autonomous.bot"


def _refresh_companion_egress(home: Path | None) -> None:
    """Reapply per-bot companion routes now that a desk IP exists or is gone."""
    try:
        from autonomous.services import companion_egress as egress_svc

        egress_svc.refresh(home)
    except Exception:
        pass
_PORT_BASE = 15900
# Idle desk → docker stop (bind-mounted ~/files stays on host).
AUTO_SLEEP_SEC = 5 * 60
_REPO_DESKTOP = Path(__file__).resolve().parents[2] / "docker" / "desktop"
_DESKTOP_SCRIPTS = (
    ("bot-chrome", "/usr/local/bin/bot-chrome", 0o755),
    ("maximize-window.py", "/usr/local/bin/maximize-window.py", 0o755),
    ("dismiss-chrome-tos.py", "/usr/local/bin/dismiss-chrome-tos.py", 0o755),
    ("webgl-spoof-cdp.py", "/usr/local/bin/webgl-spoof-cdp.py", 0o755),
    ("webgl-spoof.js", "/usr/local/share/autonomous/webgl-spoof.js", 0o644),
    ("chrome-policy.json", "/etc/opt/chrome/policies/managed/autonomous.json", 0o644),
    ("autonomous-hook", "/usr/local/bin/autonomous-hook", 0o755),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _docker():
    try:
        import docker
    except ImportError as exc:
        raise AutonomousError("docker SDK not installed") from exc
    return docker.from_env()


def container_name(bot: str, home: Path | None = None) -> str:
    """Docker container name for a bot desk (opaque `autonomous-<uuid>` in desk JSON)."""
    from autonomous.services import bots as bots_svc

    desk = (bots_svc.get_bot(bot, home=home) or {}).get("desk") or {}
    name = (desk.get("container_name") or "").strip()
    if name:
        return name
    # Legacy desks created before opaque ids.
    return f"autonomous-{bot}"


# Back-compat for older imports / local helpers.
def _container_name(bot: str, home: Path | None = None) -> str:
    return container_name(bot, home=home)


def _remove_bot_containers(client: Any, bot: str, *extra_names: str) -> list[str]:
    """Force-remove every desk container for this bot (by label + known names)."""
    removed: list[str] = []
    seen: set[str] = set()
    candidates = [n for n in extra_names if n]
    try:
        labeled = client.containers.list(
            all=True, filters={"label": f"{_LABEL}={bot}"}
        )
        candidates.extend(c.name for c in labeled)
    except Exception:
        pass
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            c = client.containers.get(name)
            c.remove(force=True)
            removed.append(name)
        except Exception:
            pass
    return removed


def sync_desktop_scripts(bot: str, home: Path | None = None) -> list[str]:
    """Copy host docker/desktop helpers into a running desk (CDP-capable bot-chrome).

    Chrome ≥136 ignores --remote-debugging-port on the default profile path;
    the repo ``bot-chrome`` uses ``~/.autonomous-chrome``. Images may lag the
    repo — sync on desk create so every new VM gets a working CDP.
    """
    name = container_name(bot, home=home)
    updated: list[str] = []
    for src_name, dest, mode in _DESKTOP_SCRIPTS:
        src = _REPO_DESKTOP / src_name
        if not src.is_file():
            continue
        tmp = f"/tmp/{src_name}.autonomous-sync"
        try:
            # Ensure parent dir exists (e.g. /usr/local/share/autonomous).
            parent = str(Path(dest).parent)
            subprocess.run(
                ["docker", "exec", "-u", "root", name, "mkdir", "-p", parent],
                check=True,
                capture_output=True,
                timeout=15,
            )
            subprocess.run(
                ["docker", "cp", str(src), f"{name}:{tmp}"],
                check=True,
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-u",
                    "root",
                    name,
                    "install",
                    f"-m{mode:o}",
                    tmp,
                    dest,
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            updated.append(src_name)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return updated


def restart_bot_chrome(bot: str, home: Path | None = None) -> bool:
    """Kill Chrome + WebGL spoof and relaunch ``bot-chrome`` (CDP profile).

    Needed after ``sync_desktop_scripts`` on first boot: xstartup often starts the
    *image* bot-chrome (default profile → CDP dead → spoof never attaches →
    ``llvmpipe`` fingerprint → flagged by anti-bot services) before the host sync.
    """
    name = container_name(bot, home=home)
    # Kill → wait → relaunch → require CDP 200 AND autonomous-chrome profile.
    # Do NOT `pkill -f '/opt/google/chrome/chrome'` from a bash -c that embeds that
    # string — pkill matches the script itself (SIGTERM → exit 143).
    script = r"""
export DISPLAY=:1 HOME=/home/autonomous
# Wait for X (wake/create race).
for _ in $(seq 1 40); do
  xdpyinfo >/dev/null 2>&1 && break
  sleep 0.25
done
killall -u autonomous -q chrome 2>/dev/null || true
killall -u autonomous -q chrome_crashpad_handler 2>/dev/null || true
pgrep -u autonomous -f 'webgl-spoof-cdp[.]py' | xargs -r kill 2>/dev/null || true
sleep 2
killall -u autonomous -q -9 chrome 2>/dev/null || true
pgrep -u autonomous -f 'webgl-spoof-cdp[.]py' | xargs -r kill -9 2>/dev/null || true
sleep 1
rm -f "$HOME/.config/google-chrome/SingletonLock" \
      "$HOME/.config/google-chrome/SingletonSocket" \
      "$HOME/.autonomous-chrome/SingletonLock" \
      "$HOME/.autonomous-chrome/SingletonSocket" \
      "$HOME/shared/.autonomous-chrome/SingletonLock" \
      "$HOME/shared/.autonomous-chrome/SingletonSocket" 2>/dev/null || true
export BOT_CHROME_USER_DATA_DIR="${BOT_CHROME_USER_DATA_DIR:-$HOME/shared/.autonomous-chrome}"
nohup /usr/local/bin/bot-chrome >>"$HOME/.chrome-autostart.log" 2>&1 &
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9222/json/version 2>/dev/null || true)
  if [ "$code" = "200" ]; then
    exit 0
  fi
  sleep 0.5
done
exit 1
"""
    try:
        r = subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "autonomous",
                "-e",
                "DISPLAY=:1",
                "-e",
                "HOME=/home/autonomous",
                name,
                "bash",
                "-lc",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
        return False


def _serve_port(home: Path | None = None) -> int | None:
    from autonomous.paths import default_home, serve_pid_path

    path = serve_pid_path(home or default_home())
    if not path.is_file():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("port="):
                return int(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        return None
    return None


def vm_api_base(home: Path | None = None) -> str | None:
    """API base URL as seen from a bridge desk (host.docker.internal)."""
    port = _serve_port(home)
    if not port:
        return None
    return f"http://host.docker.internal:{port}/api/v1"


def _ensure_files_alias(bot: str, *, home: Path | None = None) -> None:
    """Expose this bot's private files as ~/files inside an already running VM.

    New desks bind-mount that path. Older containers only have ~/workspace
    (and the legacy ~/shared mount Chrome still uses), so add a symlink once.
    """
    marker = bot_dir(bot, home) / "home" / ".autonomous" / "files-alias"
    if marker.is_file():
        return
    name = container_name(bot, home=home)
    script = (
        "if [ ! -e /home/autonomous/files ]; then "
        "ln -sfn workspace /home/autonomous/files; "
        "fi"
    )
    try:
        result = subprocess.run(
            ["docker", "exec", "-u", "root", name, "bash", "-lc", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok\n", encoding="utf-8")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return


def ensure_files_aliases(*, home: Path | None = None) -> None:
    """Point ~/files at the private folder on every desk already running.

    Called at serve start, before stale-run recovery opens Pi. Sleeping desks
    get the same link in ``wake_desk`` / ``ensure_awake``. The new prompt then
    tells the bot to use ~/files and to stop using ~/shared.
    """
    from autonomous.services import bots as bots_svc

    for bot in bots_svc.list_bots(home=home):
        name = str(bot.get("name") or "")
        desk = bot.get("desk") or {}
        if not name or desk.get("state") != "running":
            continue
        try:
            _ensure_files_alias(name, home=home)
        except Exception:
            continue


def sync_host_api_env(bot: str, *, home: Path | None = None) -> Path | None:
    """Write host API URLs into the bind-mounted private files for VM scripts."""
    base = vm_api_base(home)
    if not base:
        return None
    root = bot_dir(bot, home) / "home" / ".autonomous"
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chown(root, 1000, 1000)
    except OSError:
        pass
    path = root / "host-api.env"
    body = (
        f"AUTONOMOUS_API_BASE={base}\n"
        f"AUTONOMOUS_HOOKS_BASE={base}/hooks\n"
        f"AUTONOMOUS_BOT={bot}\n"
    )
    path.write_text(body, encoding="utf-8")
    try:
        os.chown(path, 1000, 1000)
    except OSError:
        pass
    return path


def _allocate_vnc_port(home: Path | None) -> int:
    used = set()
    for b in bots_svc.list_bots(home=home):
        desk = b.get("desk") or {}
        port = desk.get("vnc_port")
        if port:
            used.add(int(port))
    port = _PORT_BASE
    while port in used or not _host_port_free(port):
        port += 1
    return port


def _drop_if_bot_deleted(bot: str, container: Any, *, home: Path | None) -> None:
    """A bot deleted while its desk was still being created must not leave a container."""
    try:
        bots_svc.get_bot(bot, home=home)
        return
    except Exception:
        pass
    try:
        container.remove(force=True)
    except Exception:
        pass
    raise AutonomousError(f"bot {bot} supprimé pendant la création du bureau")


def _host_port_free(port: int) -> bool:
    """False when something (e.g. an orphan container) already holds the port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _desk_request_flags(
    bot: str, *, home: Path | None = None
) -> dict[str, str | None]:
    """Latest desk_request card — for agent poll while waiting on the user."""
    from autonomous.services import chat as chat_svc

    for msg in reversed(chat_svc.list_messages(bot, limit=40, home=home)):
        meta = msg.get("meta") or {}
        if msg.get("role") == "event" and meta.get("kind") == "desk_request":
            state = str(meta.get("state") or "")
            if state == "pending":
                return {
                    "pending_request_id": str(msg["id"]),
                    "pending_state": "pending",
                }
            if state in ("approved", "denied"):
                return {
                    "pending_request_id": None,
                    "pending_state": state,
                }
            break
    return {"pending_request_id": None, "pending_state": None}


_CREATING_STALE_SEC = 240


def _creating_is_stale(desk: dict[str, Any]) -> bool:
    """A desk stuck in ``creating`` (e.g. server restarted mid-job) must not hang forever."""
    raw = desk.get("created_at")
    if not raw:
        return True
    try:
        then = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - then).total_seconds() > _CREATING_STALE_SEC


def status(bot: str, home: Path | None = None) -> dict[str, Any] | None:
    b = bots_svc.get_bot(bot, home=home)
    desk = b.get("desk")
    flags = _desk_request_flags(bot, home=home)
    if not desk:
        return {"state": "absent", **flags}
    # refresh running state from Docker when possible
    try:
        client = _docker()
        name = container_name(bot, home=home)
        try:
            c = client.containers.get(name)
            if desk.get("state") == "sleeping":
                if c.status == "running":
                    desk = {**desk, "state": "running", "slept_at": None, "last_error": None}
                    bots_svc.patch_bot(bot, {"desk": desk}, home=home)
                # stopped/exited while sleeping is expected
            elif c.status == "running":
                if desk.get("state") == "creating" and not _creating_is_stale(desk):
                    # Container is up but the create job is still syncing scripts and
                    # restarting Chrome (CDP profile + WebGL spoof). Reporting "running"
                    # now frees the agent too early: its first tab dies in the restart.
                    pass
                elif desk.get("state") != "running":
                    desk = {**desk, "state": "running", "last_error": None}
                    bots_svc.patch_bot(bot, {"desk": desk}, home=home)
            elif c.status not in ("running", "created"):
                if desk.get("state") != "sleeping":
                    desk = {
                        **desk,
                        "state": "error" if c.status == "exited" else c.status,
                    }
                    bots_svc.patch_bot(bot, {"desk": desk}, home=home)
        except Exception:
            if desk.get("state") in ("running", "sleeping"):
                desk = {**desk, "state": "absent", "last_error": "container missing"}
                bots_svc.patch_bot(bot, {"desk": desk}, home=home)
    except Exception:
        pass
    out = dict(bots_svc.get_bot(bot, home=home).get("desk") or {"state": "absent"})
    out.update(flags)
    return out


def touch_activity(bot: str, *, home: Path | None = None) -> None:
    """Mark desk as recently used (resets the auto-sleep idle timer)."""
    try:
        bots_svc.patch_bot(bot, {"desk_last_active_at": _now()}, home=home)
    except Exception:
        pass


def sleep_desk(bot: str, *, home: Path | None = None) -> dict[str, Any] | None:
    """Stop the container (veille). Shared files on the host bind mount are kept."""
    b = bots_svc.get_bot(bot, home=home)
    desk = b.get("desk") or {}
    if desk.get("state") != "running":
        return desk or None
    try:
        client = _docker()
        c = client.containers.get(container_name(bot, home=home))
        if c.status == "running":
            c.stop(timeout=15)
    except Exception as exc:
        raise AutonomousError(f"Sleep failed: {exc}") from exc
    now = _now()
    desk = {**desk, "state": "sleeping", "slept_at": now, "last_error": None}
    bots_svc.patch_bot(bot, {"desk": desk}, home=home)
    BUS.publish("desk.updated", {"desk": desk}, bot=bot)
    return desk


def wake_desk(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    """Start a sleeping desk container and wait until Docker reports running."""
    b = bots_svc.get_bot(bot, home=home)
    desk = dict(b.get("desk") or {})
    if not desk:
        raise AutonomousError("No desk to wake", code="desk_absent")
    if desk.get("state") == "running":
        touch_activity(bot, home=home)
        _ensure_files_alias(bot, home=home)
        return desk
    try:
        client = _docker()
        c = client.containers.get(container_name(bot, home=home))
        if c.status != "running":
            c.start()
        deadline = time.time() + 60
        while time.time() < deadline:
            c.reload()
            if c.status == "running":
                break
            time.sleep(0.4)
        else:
            raise AutonomousError("Desk wake timed out", code="desk_wake_timeout")
    except AutonomousError:
        raise
    except Exception as exc:
        raise AutonomousError(f"Wake failed: {exc}") from exc
    desk = {**desk, "state": "running", "slept_at": None, "last_error": None}
    bots_svc.patch_bot(bot, {"desk": desk}, home=home)
    touch_activity(bot, home=home)
    # Re-sync helpers + ensure CDP Chrome (same race as first create if image is stale).
    try:
        sync_desktop_scripts(bot, home=home)
        # Only relaunch if CDP is down (xstartup may already have started Chrome).
        probe = subprocess.run(
            [
                "docker",
                "exec",
                container_name(bot, home=home),
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "http://127.0.0.1:9222/json/version",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if (probe.stdout or "").strip() != "200":
            restart_bot_chrome(bot, home=home)
    except Exception:
        pass
    _ensure_files_alias(bot, home=home)
    BUS.publish("desk.updated", {"desk": desk}, bot=bot)
    return desk


def ensure_awake(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    """Ensure desk is running (wake from sleep if needed) and touch activity."""
    b = bots_svc.get_bot(bot, home=home)
    if b.get("capability") == "none":
        raise AutonomousError(
            "Bot has no desktop/terminal capability — create a desk first.",
            code="no_capability",
        )
    desk = b.get("desk") or {}
    state = desk.get("state")
    if state == "sleeping":
        desk = wake_desk(bot, home=home)
    elif state == "running":
        touch_activity(bot, home=home)
        _ensure_files_alias(bot, home=home)
    else:
        raise AutonomousError(
            "Desktop is not running — start the bot desk first.",
            code="desk_not_running",
        )
    sync_host_api_env(bot, home=home)
    return desk


def tick_auto_sleep(*, home: Path | None = None) -> int:
    """Put idle desks to sleep. Returns how many were slept."""
    slept = 0
    now = datetime.now(timezone.utc)
    for bot in bots_svc.list_bots(home=home):
        if not bot.get("auto_sleep", True):
            continue
        desk = bot.get("desk") or {}
        if desk.get("state") != "running":
            continue
        # Agent run (or a card waiting on the user): keep the idle clock at zero
        # so sleep starts only after the run ends.
        if bot.get("status") in ("busy", "waiting"):
            touch_activity(bot["name"], home=home)
            continue
        last = bot.get("desk_last_active_at") or desk.get("created_at")
        if not last:
            touch_activity(bot["name"], home=home)
            continue
        try:
            text = str(last).replace("Z", "+00:00")
            then = datetime.fromisoformat(text)
            if then.tzinfo is None:
                then = then.replace(tzinfo=timezone.utc)
        except ValueError:
            touch_activity(bot["name"], home=home)
            continue
        idle = (now - then.astimezone(timezone.utc)).total_seconds()
        if idle < AUTO_SLEEP_SEC:
            continue
        try:
            sleep_desk(bot["name"], home=home)
            slept += 1
        except Exception:
            pass
    return slept


def create(
    bot: str,
    *,
    home: Path | None = None,
    internet: bool | None = None,
    wait: bool = False,
) -> dict[str, Any]:
    """Start desk creation job (async unless wait=True).

    One container: shell and noVNC desktop. ``internet`` sets the Docker network.
    """
    bots_svc.get_bot(bot, home=home)
    fields: dict[str, Any] = {"capability": "screen"}
    if internet is not None:
        fields["internet"] = bool(internet)
    bots_svc.patch_bot(bot, fields, home=home)

    job = jobs_svc.create_job(bot, "desk.create", home=home)

    def _run() -> None:
        try:
            jobs_svc.update_job(
                job["id"],
                state="running",
                progress=3,
                log_line=f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] démarrage de la tâche",
                home=home,
            )
            _create_sync(bot, job["id"], home=home)
            jobs_svc.update_job(
                job["id"],
                state="done",
                progress=100,
                log_line=f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] bureau créé avec succès",
                home=home,
            )
        except Exception as exc:
            jobs_svc.update_job(
                job["id"],
                state="error",
                error=str(exc),
                log_line=f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] erreur : {exc}",
                home=home,
            )
            bots_svc.patch_bot(
                bot,
                {
                    "desk": {
                        "state": "error",
                        "container_id": None,
                        "image": settings_svc.get("desktop_image", home=home),
                        "vnc_port": None,
                        "novnc_path": None,
                        "mode": "screen",
                        "created_at": _now(),
                        "last_error": str(exc),
                    }
                },
                home=home,
            )
            BUS.publish("desk.updated", {"desk": bots_svc.get_bot(bot, home=home).get("desk")}, bot=bot)

    if wait:
        _run()
        return jobs_svc.get_job(job["id"], home=home)
    threading.Thread(target=_run, name=f"desk-create-{bot}", daemon=True).start()
    return job


def _job_log(job_id: str, msg: str, *, progress: int | None = None, home: Path | None) -> None:
    ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    jobs_svc.update_job(
        job_id,
        progress=progress,
        log_line=f"[{ts}] {msg}",
        home=home,
    )


def _ensure_image(client, image: str, job_id: str, *, home: Path | None) -> None:
    try:
        client.images.get(image)
        _job_log(job_id, f"image prête : {image}", progress=18, home=home)
        return
    except Exception:
        pass

    _job_log(
        job_id,
        f"image absente — téléchargement de {image} (peut prendre plusieurs minutes)…",
        progress=12,
        home=home,
    )
    last_emit = 0.0
    last_msg = ""
    try:
        for chunk in client.api.pull(image, stream=True, decode=True):
            status = str(chunk.get("status") or "").strip()
            progress_detail = str(chunk.get("progress") or "").strip()
            if not status:
                continue
            msg = f"{status} {progress_detail}".strip()
            now = time.time()
            # Throttle noisy pull layers; always emit status changes.
            if msg == last_msg and now - last_emit < 2.0:
                continue
            if now - last_emit < 0.8 and "Pull complete" not in status and "Digest" not in status:
                continue
            last_emit = now
            last_msg = msg
            _job_log(job_id, f"docker pull : {msg}", progress=20, home=home)
    except Exception as exc:
        raise AutonomousError(
            f"Impossible de récupérer l'image {image}: {exc}. "
            f"Construisez-la avec : docker build -t {image} docker/desktop"
        ) from exc
    _job_log(job_id, f"image téléchargée : {image}", progress=28, home=home)


def _wait_desktop_ready(
    container,
    *,
    job_id: str,
    vnc_port: int,
    home: Path | None,
    timeout_s: float = 120.0,
) -> None:
    """Poll container + noVNC HTTP until ready, with heartbeat logs."""
    import urllib.error
    import urllib.request

    started = time.time()
    last_log = 0.0
    _job_log(
        job_id,
        "démarrage du bureau (VNC / XFCE / Chrome)…",
        progress=55,
        home=home,
    )

    while True:
        elapsed = time.time() - started
        if elapsed > timeout_s:
            try:
                logs = container.logs(tail=30).decode("utf-8", errors="replace").strip()
            except Exception:
                logs = ""
            hint = logs.splitlines()[-1] if logs else "aucun log conteneur"
            raise AutonomousError(
                f"Bureau non prêt après {int(timeout_s)}s ({hint}). "
                f"Vérifiez : docker logs {container.name}"
            )

        try:
            container.reload()
        except Exception as exc:
            raise AutonomousError(f"Conteneur inaccessible : {exc}") from exc

        status = getattr(container, "status", None)
        if status != "running":
            try:
                logs = container.logs(tail=40).decode("utf-8", errors="replace").strip()
            except Exception:
                logs = ""
            detail = (
                logs.splitlines()[-1]
                if logs
                else f"status={status}"
            )
            raise AutonomousError(f"Le conteneur s'est arrêté : {detail}")

        ready = False
        if vnc_port:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{vnc_port}/", timeout=1.5)
                ready = True
            except (urllib.error.URLError, TimeoutError, OSError):
                ready = False

        if ready:
            _job_log(
                job_id,
                f"bureau prêt ({int(elapsed)}s)",
                progress=92,
                home=home,
            )
            return

        now = time.time()
        if now - last_log >= 3.0:
            last_log = now
            pct = min(88, 55 + int(elapsed / timeout_s * 30))
            _job_log(
                job_id,
                f"toujours en cours… {int(elapsed)}s / {int(timeout_s)}s "
                f"(attente noVNC :{vnc_port})",
                progress=pct,
                home=home,
            )
        time.sleep(1.5)


def _create_sync(bot: str, job_id: str, *, home: Path | None) -> None:
    b = bots_svc.get_bot(bot, home=home)
    image = settings_svc.get("desktop_image", home=home)
    client = _docker()
    _job_log(job_id, f"préparation (bot={bot})", progress=8, home=home)
    _ensure_image(client, image, job_id, home=home)

    # Opaque Docker name (same scheme as Pi session ids). Link = desk.container_name.
    from autonomous.ids import new_autonomous_id

    prev = (b.get("desk") or {}).get("container_name") or ""
    removed = _remove_bot_containers(
        client, bot, prev, f"autonomous-{bot}"
    )
    if removed:
        _job_log(
            job_id,
            f"ancien(s) conteneur(s) retiré(s) : {', '.join(removed)}",
            progress=32,
            home=home,
        )
    else:
        _job_log(job_id, "aucun ancien conteneur à retirer", progress=32, home=home)

    name = new_autonomous_id()
    vnc_port = _allocate_vnc_port(home)
    _job_log(job_id, f"port noVNC réservé : {vnc_port}", progress=36, home=home)

    desk = {
        "state": "creating",
        "container_id": None,
        "container_name": name,
        "image": image,
        "vnc_port": vnc_port,
        "novnc_path": f"/novnc/{bot}/",
        "mode": "screen",
        "internet": bool(b.get("internet", True)),
        "created_at": _now(),
        "last_error": None,
    }
    # Keep "waiting" (not agent "busy") while the VM boots — resume only when running.
    bots_svc.patch_bot(bot, {"desk": desk, "status": "waiting"}, home=home)
    BUS.publish("desk.updated", {"desk": desk}, bot=bot)
    BUS.publish("notification", {"kind": "desk.creating", "bot": bot}, bot=bot)

    root = bot_dir(bot, home)
    # Bind this bot's private files as ~/files (and workspace). Keep ~/shared
    # so the desktop image (Chrome downloads, autonomous-hook) still finds them.
    home_mount = root / "home"
    home_mount.mkdir(parents=True, exist_ok=True)
    try:
        os.chown(home_mount, 1000, 1000)
    except OSError:
        pass
    ports = {}
    if vnc_port:
        # noVNC websockify typically 6080 inside; VNC 5901
        ports["6080/tcp"] = ("127.0.0.1", vnc_port)

    network_mode = "bridge" if b.get("internet", True) else "none"
    net_label = "avec Internet" if network_mode == "bridge" else "sans Internet"
    _job_log(job_id, f"création du conteneur Docker ({net_label})…", progress=42, home=home)
    sync_host_api_env(bot, home=home)
    api_base = vm_api_base(home)

    try:
        from docker.types import Mount

        shared_mounts = [
            Mount(
                target="/home/autonomous/files",
                source=str(home_mount),
                type="bind",
                read_only=False,
            ),
            Mount(
                target="/home/autonomous/workspace",
                source=str(home_mount),
                type="bind",
                read_only=False,
            ),
            # Legacy alias. Same private folder — not shared with other bots.
            Mount(
                target="/home/autonomous/shared",
                source=str(home_mount),
                type="bind",
                read_only=False,
            ),
        ]
        env = {
            "AUTONOMOUS_BOT": bot,
            # Match a FR desktop — UTC/en-US alone is a strong anti-bot signal.
            "TZ": os.environ.get("AUTONOMOUS_DESK_TZ", "Europe/Paris"),
            "LANG": os.environ.get("AUTONOMOUS_DESK_LANG", "fr_FR.UTF-8"),
            "LANGUAGE": os.environ.get("AUTONOMOUS_DESK_LANGUAGE", "fr_FR:fr:en_US:en"),
            "LC_ALL": os.environ.get("AUTONOMOUS_DESK_LANG", "fr_FR.UTF-8"),
            "BOT_CHROME_PORT": "9222",
            # Chrome profile on the host bind-mount (survives container recreate).
            "BOT_CHROME_USER_DATA_DIR": "/home/autonomous/shared/.autonomous-chrome",
            # Fixed desktop resolution (no client-side resize).
            "VNC_GEOMETRY": "1920x1200",
            "CHROME_WINDOW_WIDTH": "1920",
            "CHROME_WINDOW_HEIGHT": "1200",
            "UNMASKED_VENDOR_WEBGL": os.environ.get(
                "UNMASKED_VENDOR_WEBGL", "Google Inc. (Intel)"
            ),
            "UNMASKED_RENDERER_WEBGL": os.environ.get(
                "UNMASKED_RENDERER_WEBGL",
                "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)",
            ),
        }
        if api_base and network_mode == "bridge":
            # Reach host serve from VM scripts (webhooks, etc.).
            env["AUTONOMOUS_API_BASE"] = api_base
            env["AUTONOMOUS_HOOKS_BASE"] = f"{api_base}/hooks"
        run_kwargs: dict[str, Any] = {
            "name": name,
            "detach": True,
            "ports": ports or None,
            "mounts": shared_mounts,
            "network_mode": network_mode,
            "labels": {_LABEL: bot, "autonomous.role": "desk"},
            "environment": env,
            "shm_size": "256m",
            "user": "1000:1000",
            # Let Chrome's real sandbox (zygote/userns) work. Without this, Chrome
            # needs --no-sandbox which anti-bots fingerprint hard.
            "security_opt": ["seccomp=unconfined"],
        }
        # Linux Docker 20.10+: map host.docker.internal → host gateway.
        if network_mode == "bridge":
            run_kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
        container = client.containers.run(image, **run_kwargs)
    except Exception as exc:
        # Image missing — clearer error
        raise AutonomousError(
            f"Échec du démarrage du conteneur : {exc}. "
            f"Construisez l'image avec : docker build -t {image} docker/desktop"
        ) from exc

    _job_log(
        job_id,
        f"conteneur lancé : {name} ({container.id[:12]})",
        progress=50,
        home=home,
    )
    _drop_if_bot_deleted(bot, container, home=home)
    _wait_desktop_ready(
        container,
        job_id=job_id,
        vnc_port=vnc_port,
        home=home,
    )

    _drop_if_bot_deleted(bot, container, home=home)
    synced = sync_desktop_scripts(bot, home=home)
    if synced:
        _job_log(
            job_id,
            f"scripts desktop synchronisés : {', '.join(synced)}",
            progress=90,
            home=home,
        )
    # Image may still ship old bot-chrome; xstartup often already launched it.
    # Relaunch so CDP + WebGL spoof (Intel UHD, not llvmpipe) are live.
    if restart_bot_chrome(bot, home=home):
        _job_log(job_id, "Chrome relancé (profil CDP + spoof WebGL)", progress=94, home=home)
    else:
        _job_log(
            job_id,
            "avertissement : relance Chrome / CDP non confirmée",
            progress=94,
            home=home,
        )

    desk.update(
        {
            "state": "running",
            "container_id": container.id[:12],
            "last_error": None,
        }
    )
    # Do NOT force status=idle here: the agent may still be mid-run (status was
    # waiting during boot). Clearing to idle kills the Working orb; continue
    # below restores busy or resume_run sets it.
    bots_svc.patch_bot(bot, {"desk": desk}, home=home)
    touch_activity(bot, home=home)
    _ensure_files_alias(bot, home=home)
    _refresh_companion_egress(home)
    _job_log(job_id, "terminé", progress=98, home=home)
    BUS.publish("desk.updated", {"desk": desk}, bot=bot)
    BUS.publish("notification", {"kind": "desk.running", "bot": bot}, bot=bot)
    approved = resolve_desk_requests(bot, state="approved", home=home)
    # User approved via chat card → continue the agent that was waiting for the desk.
    if approved:
        _continue_agent_after_desk(bot, home=home)
    else:
        try:
            row = bots_svc.get_bot(bot, home=home)
            if (row.get("status") or "") == "waiting":
                bots_svc.patch_bot(bot, {"status": "idle"}, home=home)
        except Exception:
            pass
        try:
            from autonomous.services import chat as chat_svc

            chat_svc.drain_queued_user_messages(bot, home=home)
        except Exception:
            pass


def request_authorization(
    bot: str,
    *,
    mode: str = "screen",
    reason: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    """Post a chat card so the user can authorize creating the VM.

    One VM includes the shell and the desktop. ``mode`` is ignored.
    Does not create the VM itself — the card does. Dedupes while a pending
    request already exists.
    """
    from autonomous.services import chat as chat_svc

    bots_svc.get_bot(bot, home=home)
    reason = (reason or "").strip()[:500]

    # Reuse pending card if still open (avoid spam from repeated tool calls).
    for msg in reversed(chat_svc.list_messages(bot, limit=40, home=home)):
        meta = msg.get("meta") or {}
        if (
            msg.get("role") == "event"
            and meta.get("kind") == "desk_request"
            and meta.get("state") == "pending"
        ):
            BUS.publish(
                "notification",
                {
                    "kind": "desk.request",
                    "bot": bot,
                    "mode": "screen",
                    "reason": meta.get("reason") or reason,
                    "message_id": msg["id"],
                },
                bot=bot,
            )
            return {
                "ok": True,
                "deduped": True,
                "message_id": msg["id"],
                "mode": "screen",
                "state": "pending",
            }

    content = "Autorisation bureau requise" + (f" — {reason}" if reason else "")
    msg = chat_svc.create_message(
        bot,
        content,
        role="event",
        meta={
            "kind": "desk_request",
            "reason": reason,
            "state": "pending",
        },
        home=home,
    )
    # Agent is blocked on user approval — same UX as vault waiting.
    try:
        row = bots_svc.get_bot(bot, home=home)
        if row.get("status") in ("busy", "waiting", "idle"):
            bots_svc.patch_bot(bot, {"status": "waiting"}, home=home)
    except Exception:
        pass
    BUS.publish(
        "notification",
        {
            "kind": "desk.request",
            "bot": bot,
            "reason": reason,
            "message_id": msg["id"],
        },
        bot=bot,
    )
    return {
        "ok": True,
        "deduped": False,
        "message_id": msg["id"],
        "state": "pending",
    }


def resolve_desk_requests(
    bot: str,
    *,
    state: str = "approved",
    home: Path | None = None,
) -> int:
    """Mark pending desk_request chat cards as approved/denied."""
    from autonomous.services import chat as chat_svc

    state = state if state in ("approved", "denied") else "approved"
    n = 0
    for msg in chat_svc.list_messages(bot, limit=80, home=home):
        meta = dict(msg.get("meta") or {})
        if (
            msg.get("role") == "event"
            and meta.get("kind") == "desk_request"
            and meta.get("state") == "pending"
        ):
            meta["state"] = state
            label = "Bureau autorisé." if state == "approved" else "Bureau refusé."
            chat_svc.update_message(
                bot,
                msg["id"],
                label,
                home=home,
                meta=meta,
            )
            n += 1
    return n


def _continue_agent_after_desk(bot: str, *, home: Path | None = None) -> None:
    """After a desk_request was approved and the VM is running, resume the agent.

    Called only once desk.state=running. Do not call at Authorize click — creation
    must finish first. Desk boot uses status=waiting so the UI does not look like
    an agent run.
    """
    from autonomous.services import agent as agent_svc
    from autonomous.services import chat as chat_svc
    from autonomous.services.errors import Conflict

    bot_row = bots_svc.get_bot(bot, home=home)
    status = bot_row.get("status") or "idle"
    # Agent already mid-run (e.g. bash sleep / polling while status=waiting for
    # the desk card) — same rule as vault: bump busy, never double-prompt Pi.
    if agent_svc.run_in_progress(bot) or status == "busy":
        try:
            bots_svc.patch_bot(bot, {"status": "busy"}, home=home)
        except Exception:
            pass
        return

    try:
        # resume_run requires idle; start_run then sets busy (orb back on).
        if status != "idle":
            bots_svc.patch_bot(bot, {"status": "idle"}, home=home)
        chat_svc.resume_run(bot, home=home)
    except Conflict:
        try:
            if agent_svc.run_in_progress(bot):
                bots_svc.patch_bot(bot, {"status": "busy"}, home=home)
        except Exception:
            pass
    except Exception:
        try:
            chat_svc.mark_interrupted_after_wait(bot, home=home)
        except Exception:
            pass


def destroy(bot: str, *, home: Path | None = None, wait: bool = False) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    job = jobs_svc.create_job(bot, "desk.destroy", home=home)

    def _run() -> None:
        try:
            jobs_svc.update_job(job["id"], state="running", progress=10, log_line="stopping", home=home)
            _destroy_sync(bot, home=home, remove_volumes=False)
            jobs_svc.update_job(job["id"], state="done", progress=100, log_line="done", home=home)
        except Exception as exc:
            jobs_svc.update_job(
                job["id"], state="error", error=str(exc), log_line=str(exc), home=home
            )

    if wait:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()
    return job


def _destroy_sync(bot: str, *, home: Path | None, remove_volumes: bool) -> None:
    bots_svc.patch_bot(
        bot,
        {
            "desk": {
                **(bots_svc.get_bot(bot, home=home).get("desk") or {}),
                "state": "stopping",
            }
        },
        home=home,
    )
    BUS.publish("desk.updated", {"desk": bots_svc.get_bot(bot, home=home).get("desk")}, bot=bot)
    try:
        client = _docker()
        prev = (bots_svc.get_bot(bot, home=home).get("desk") or {}).get("container_name") or ""
        _remove_bot_containers(client, bot, prev, f"autonomous-{bot}")
    except Exception:
        pass
    if remove_volumes:
        import shutil

        root = bot_dir(bot, home)
        home_path = root / "home"
        if home_path.exists():
            shutil.rmtree(home_path, ignore_errors=True)
            home_path.mkdir(parents=True, exist_ok=True)
    bots_svc.patch_bot(bot, {"desk": None, "status": "idle"}, home=home)
    _refresh_companion_egress(home)
    BUS.publish("desk.updated", {"desk": None}, bot=bot)
    BUS.publish("notification", {"kind": "desk.destroyed", "bot": bot}, bot=bot)


def restart(bot: str, home: Path | None = None) -> dict[str, Any]:
    bots_svc.get_bot(bot, home=home)
    try:
        client = _docker()
        c = client.containers.get(container_name(bot, home=home))
        if c.status != "running":
            c.start()
        else:
            c.restart(timeout=10)
        desk = bots_svc.get_bot(bot, home=home).get("desk") or {}
        desk = {**desk, "state": "running", "slept_at": None, "last_error": None}
        bots_svc.patch_bot(bot, {"desk": desk}, home=home)
        touch_activity(bot, home=home)
        _refresh_companion_egress(home)
        BUS.publish("desk.updated", {"desk": desk}, bot=bot)
        return desk
    except Exception as exc:
        raise AutonomousError(f"Restart failed: {exc}") from exc


def reset(bot: str, *, confirm: bool, home: Path | None = None) -> dict[str, Any]:
    if not confirm:
        raise ValidationError("confirm must be true to reset desktop")
    job = jobs_svc.create_job(bot, "desk.reset", home=home)

    def _run() -> None:
        try:
            jobs_svc.update_job(job["id"], state="running", progress=10, home=home)
            _destroy_sync(bot, home=home, remove_volumes=True)
            jobs_svc.update_job(job["id"], progress=50, log_line="recreating", home=home)
            b = bots_svc.get_bot(bot, home=home)
            if b.get("capability") in ("terminal", "screen"):
                bots_svc.patch_bot(bot, {"capability": "screen"}, home=home)
                _create_sync(bot, job["id"], home=home)
            jobs_svc.update_job(job["id"], state="done", progress=100, home=home)
        except Exception as exc:
            jobs_svc.update_job(job["id"], state="error", error=str(exc), home=home)

    threading.Thread(target=_run, daemon=True).start()
    return job


def novnc_info(bot: str, home: Path | None = None) -> dict[str, Any]:
    """Connection info only. Viewing the stream must not wake or reset auto-sleep."""
    desk = status(bot, home=home) or {}
    port = desk.get("vnc_port") if desk.get("state") == "running" else None
    if not port:
        return {
            "url": "",
            "direct_url": "",
            "ws_path": f"/novnc/{bot}/",
            "vnc_port": None,
            "state": desk.get("state", "absent"),
        }
    # Same-origin HTML + WS path so the browser never needs the mapped VNC port.
    return {
        # Remote stays 1920×1200; scaleViewport fits the pane (mouse remapped by noVNC).
        "url": (
            f"/novnc/{bot}/vnc_lite.html?autoconnect=1&scale=true"
            f"&path=novnc/{bot}/&v=8"
        ),
        "direct_url": (
            f"http://127.0.0.1:{port}/vnc_lite.html?autoconnect=1&scale=true"
        ),
        "ws_path": f"/novnc/{bot}/",
        "vnc_port": port,
        "state": desk.get("state", "absent"),
    }
