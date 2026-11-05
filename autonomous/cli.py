"""CLI entry point: `autonomous …` (argparse)."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from getpass import getpass
from pathlib import Path

from autonomous import __version__, auth as auth_mod
from autonomous.db import migrate
from autonomous.i18n import t
from autonomous.paths import default_home, ensure_home, serve_pid_path, vite_watch_pid_path
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import desk as desk_svc
from autonomous.services import files as files_svc
from autonomous.services import jobs as jobs_svc
from autonomous.services import settings as settings_svc
from autonomous.services import terminal as term_svc
from autonomous.services.errors import AutonomousError


def _home_from_args(args) -> Path:
    raw = getattr(args, "home", None)
    home = Path(raw).expanduser() if raw else default_home()
    return ensure_home(home)


def _out(data, *, as_json: bool, plain: str | None = None) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    elif plain is not None:
        print(plain)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def cmd_init(args) -> int:
    home = _home_from_args(args)
    migrate(home)
    settings_svc.ensure_defaults(home)
    token = auth_mod.write_token(home)
    password = args.password
    if not password:
        password = getpass("Login password: ")
        confirm = getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match", file=sys.stderr)
            return 1
    if not password:
        print("Password required", file=sys.stderr)
        return 2
    auth_mod.set_password(home, password)
    print(t("init.done", home=str(home)))
    print(t("init.password_set"))
    print(t("init.token_written"))
    if args.json:
        _out({"home": str(home), "token": token}, as_json=True)
    return 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _read_serve_pid(home: Path) -> int | None:
    path = serve_pid_path(home)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip().splitlines()
        return int(raw[0].strip())
    except (OSError, ValueError):
        return None


def _write_serve_pid(home: Path, pid: int, *, host: str, port: int) -> None:
    path = serve_pid_path(home)
    path.write_text(f"{pid}\nhost={host}\nport={port}\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _clear_serve_pid(home: Path, expected_pid: int | None = None) -> None:
    path = serve_pid_path(home)
    if not path.is_file():
        return
    if expected_pid is not None:
        current = _read_serve_pid(home)
        if current is not None and current != expected_pid:
            return
    try:
        path.unlink()
    except OSError:
        pass


def _read_pid_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip().splitlines()[0].strip())
    except (OSError, ValueError):
        return None


def _stop_pid_file(path: Path, *, name: str) -> None:
    pid = _read_pid_file(path)
    if pid is None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return

    def _kill(sig: signal.Signals) -> None:
        # Prefer process group (vite watch uses start_new_session).
        try:
            os.killpg(pid, sig)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass

    if _pid_alive(pid):
        _kill(signal.SIGTERM)
        deadline = time.time() + 5
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.15)
        if _pid_alive(pid):
            _kill(signal.SIGKILL)
    # Also sweep leftover vite build watchers for this project.
    try:
        subprocess.run(
            ["pkill", "-f", f"vite build --watch"],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _frontend_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "frontend"


def _start_vite_watch(home: Path) -> None:
    """Rebuild Vue → autonomous/static on change (for serve --dev on :8787)."""
    path = vite_watch_pid_path(home)
    existing = _read_pid_file(path)
    if existing is not None and _pid_alive(existing):
        return
    if existing is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    frontend = _frontend_dir()
    if not (frontend / "package.json").is_file():
        print(t("serve.vite_missing"), file=sys.stderr)
        return
    log_path = ensure_home(home) / "vite-watch.log"
    log_f = open(log_path, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            ["npm", "run", "build", "--", "--watch"],
            cwd=str(frontend),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        log_f.close()
        print(t("serve.vite_failed", error=str(exc)), file=sys.stderr)
        return
    path.write_text(f"{proc.pid}\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    print(t("serve.vite_watch", log=str(log_path)))


def cmd_serve_stop(args) -> int:
    home = _home_from_args(args)
    _stop_pid_file(vite_watch_pid_path(home), name="vite")
    pid = _read_serve_pid(home)
    if pid is None or not _pid_alive(pid):
        _clear_serve_pid(home)
        print(t("serve.not_running"), file=sys.stderr)
        return 1
    print(t("serve.stopping", pid=pid))

    def _kill(sig: signal.Signals) -> None:
        try:
            os.killpg(os.getpgid(pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass

    _kill(signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline:
        if not _pid_alive(pid):
            _clear_serve_pid(home, expected_pid=pid)
            print(t("serve.stopped"))
            return 0
        time.sleep(0.2)
    _kill(signal.SIGKILL)
    _clear_serve_pid(home, expected_pid=pid)
    print(t("serve.killed", pid=pid))
    return 0


def _serve_loop(home: Path, host: str, port: int, *, manage_pid: bool) -> int:
    migrate(home)
    settings_svc.ensure_defaults(home)
    from autonomous.app import create_app
    from autonomous.services import desk as desk_svc
    from autonomous.services import scheduler as scheduler_svc
    from autonomous.wsproxy import MuxServer

    app = create_app(home)
    scheduler_svc.start(home)
    try:  # compile the companion in the background (cached by source hash)
        from autonomous.services import companion_build as companion_build_svc

        companion_build_svc.start_background(home)
    except Exception as exc:  # never block serve
        print(f"[companion] build not started: {exc}", file=sys.stderr)
    print(t("serve.starting", host=host, port=port))

    def resolve_bot_port(bot: str) -> int | None:
        try:
            info = desk_svc.novnc_info(bot, home=home)
            return info.get("vnc_port")
        except Exception:
            return None

    def terminal_handler(conn, bot: str, leftover: bytes) -> None:
        from autonomous.ptyws import attach_container_pty

        attach_container_pty(conn, bot, home=home, leftover=leftover)

    def companion_handler(conn, token: str, leftover: bytes) -> None:
        from autonomous.companion_ws import attach_companion

        attach_companion(conn, home, token, leftover)

    # Mux: HTTP → Flask, WS /novnc, /ws/terminal, /ws/companion
    mux = MuxServer(
        host,
        port,
        app,
        resolve_bot_port,
        terminal_handler=terminal_handler,
        companion_handler=companion_handler,
        home=home,
    )
    mux.start()
    try:
        from autonomous.services import companion_egress as egress_svc

        egress_svc.refresh(home)
    except Exception:
        pass
    if manage_pid:
        _write_serve_pid(home, os.getpid(), host=host, port=port)
    print(f"  UI      http://{host}:{port}/")
    print(f"  OpenAPI http://{host}:{port}/api/docs")
    print(t("serve.stop_hint"))

    import threading

    stop = threading.Event()

    def _shutdown(*_args) -> None:
        stop.set()

    # Werkzeug's reloader may call us from a worker thread (signals = main only).
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)
    try:
        while not stop.is_set():
            stop.wait(timeout=1.0)
    finally:
        scheduler_svc.stop()
        mux.shutdown()
        if manage_pid:
            _clear_serve_pid(home, expected_pid=os.getpid())
        print(t("serve.stopped"))
    return 0


def _is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in {"127.0.0.1", "localhost", "::1"}


def cmd_serve(args) -> int:
    action = getattr(args, "serve_action", None) or "start"
    if action == "stop":
        return cmd_serve_stop(args)

    home = _home_from_args(args)
    host = args.host
    port = args.port
    reloader_main = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    from autonomous import auth as auth_mod

    if not auth_mod.read_token(home) and not os.environ.get("AUTONOMOUS_SECRET"):
        if os.environ.get("AUTONOMOUS_ALLOW_INSECURE", "").strip() not in ("1", "true", "yes"):
            print(
                "No API token — run `autonomous init` first "
                "(or set AUTONOMOUS_SECRET / AUTONOMOUS_ALLOW_INSECURE=1).",
                file=sys.stderr,
            )
            return 1

    if not _is_loopback_host(host):
        allow_public = os.environ.get("AUTONOMOUS_BIND_PUBLIC", "").strip() in (
            "1",
            "true",
            "yes",
        )
        if not allow_public:
            print(
                f"Refusing to bind {host!r}: Autonomous is a mono-user local hub.\n"
                "  Default is 127.0.0.1. To expose on a network interface you MUST:\n"
                "  - terminate TLS (reverse proxy),\n"
                "  - set AUTONOMOUS_COOKIE_SECURE=1 (or https AUTONOMOUS_PUBLIC_URL),\n"
                "  - and set AUTONOMOUS_BIND_PUBLIC=1 to acknowledge the risk.\n"
                "  WebSockets (VNC/terminal) require a logged-in session; still prefer localhost.",
                file=sys.stderr,
            )
            return 1
        print(
            f"WARNING: binding to {host!r} (AUTONOMOUS_BIND_PUBLIC=1). "
            "Use a reverse proxy with TLS; do not expose raw HTTP on the internet.",
            file=sys.stderr,
        )

    if args.dev:
        # Werkzeug re-execs the same process image; PID is stable across the re-exec.
        if not reloader_main:
            existing = _read_serve_pid(home)
            if existing is not None and _pid_alive(existing) and existing != os.getpid():
                print(t("serve.already_running", pid=existing), file=sys.stderr)
                return 1
            if existing is not None and existing != os.getpid():
                _clear_serve_pid(home)
            _write_serve_pid(home, os.getpid(), host=host, port=port)
            print(t("serve.dev_mode"))
            # Frontend → static/ watch (survives Python re-exec; stopped by serve stop)
            _start_vite_watch(home)

        from werkzeug._reloader import run_with_reloader

        pkg_dir = str(Path(__file__).resolve().parent)
        try:
            run_with_reloader(
                lambda: _serve_loop(home, host, port, manage_pid=False),
                extra_files=[pkg_dir],
                exclude_patterns=[
                    "*/__pycache__/*",
                    "*.pyc",
                    "*/node_modules/*",
                    "*/.git/*",
                    "*/static/assets/*",
                ],
            )
        finally:
            # Parent monitor only (WERKZEUG_RUN_MAIN unset): tear down watchers/pid.
            if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
                _stop_pid_file(vite_watch_pid_path(home), name="vite")
                _clear_serve_pid(home, expected_pid=os.getpid())
        return 0

    existing = _read_serve_pid(home)
    if existing is not None and _pid_alive(existing):
        print(t("serve.already_running", pid=existing), file=sys.stderr)
        return 1
    if existing is not None:
        _clear_serve_pid(home)
    return _serve_loop(home, host, port, manage_pid=True)


def cmd_health(args) -> int:
    _out({"ok": True, "version": __version__}, as_json=args.json, plain=t("health.ok", version=__version__))
    return 0


def cmd_bot_create(args) -> int:
    home = _home_from_args(args)
    bot = bots_svc.create_bot(
        args.name,
        label=args.label,
        internet=not args.no_internet,
        home=home,
    )
    _out(bot, as_json=args.json, plain=t("bot.created", name=bot["name"]))
    return 0


def cmd_bot_list(args) -> int:
    home = _home_from_args(args)
    bots = bots_svc.list_bots(home=home)
    if args.json:
        _out(bots, as_json=True)
    else:
        for b in bots:
            print(f"{b['name']}\t{b['capability']}\t{b['status']}\t{b['label']}")
    return 0


def cmd_bot_show(args) -> int:
    home = _home_from_args(args)
    bot = bots_svc.get_bot(args.name, home=home)
    _out(bot, as_json=True)
    return 0


def cmd_bot_delete(args) -> int:
    home = _home_from_args(args)
    if not args.yes:
        print("Pass --yes to confirm deletion", file=sys.stderr)
        return 2
    bots_svc.delete_bot(args.name, home=home)
    print(t("bot.deleted", name=args.name))
    return 0


def cmd_bot_set(args) -> int:
    home = _home_from_args(args)
    fields = {}
    if args.label is not None:
        fields["label"] = args.label
    if args.internet:
        fields["internet"] = True
    if args.no_internet:
        fields["internet"] = False
    if fields:
        bots_svc.patch_bot(args.name, fields, home=home)
    if args.capability:
        bots_svc.set_capability(args.name, args.capability, home=home, wait=True)
    bot = bots_svc.get_bot(args.name, home=home)
    _out(bot, as_json=args.json, plain=t("ok"))
    return 0


def cmd_chat_send(args) -> int:
    home = _home_from_args(args)
    msg = chat_svc.send_message(args.name, args.text, home=home)
    _out(msg, as_json=args.json, plain=t("chat.sent"))
    return 0


def cmd_chat_history(args) -> int:
    home = _home_from_args(args)
    msgs = chat_svc.list_messages(args.name, limit=args.limit, home=home)
    if args.json:
        _out(msgs, as_json=True)
    else:
        for m in msgs:
            print(f"[{m['role']}] {m['content']}")
    return 0


def cmd_chat_clear(args) -> int:
    home = _home_from_args(args)
    if not args.yes:
        print("Pass --yes to confirm", file=sys.stderr)
        return 2
    chat_svc.clear_messages(args.name, home=home)
    print(t("chat.cleared"))
    return 0


def cmd_desk_create(args) -> int:
    home = _home_from_args(args)
    internet = True
    if getattr(args, "no_internet", False):
        internet = False
    elif getattr(args, "internet", False):
        internet = True
    job = desk_svc.create(
        args.name,
        home=home,
        internet=internet,
        wait=args.wait,
    )
    _out(job, as_json=True)
    return 0


def cmd_desk_destroy(args) -> int:
    home = _home_from_args(args)
    if not args.yes:
        print("Pass --yes to confirm", file=sys.stderr)
        return 2
    job = desk_svc.destroy(args.name, home=home, wait=args.wait)
    _out(job, as_json=True)
    return 0


def cmd_desk_restart(args) -> int:
    home = _home_from_args(args)
    desk = desk_svc.restart(args.name, home=home)
    _out(desk, as_json=True)
    return 0


def cmd_desk_reset(args) -> int:
    home = _home_from_args(args)
    if not args.yes:
        print("Pass --yes to confirm", file=sys.stderr)
        return 2
    job = desk_svc.reset(args.name, confirm=True, home=home)
    _out(job, as_json=True)
    return 0


def cmd_desk_status(args) -> int:
    home = _home_from_args(args)
    desk = desk_svc.status(args.name, home=home)
    _out(desk, as_json=True)
    return 0


def cmd_terminal_exec(args) -> int:
    home = _home_from_args(args)
    parts = list(args.cmd or [])
    if parts and parts[0] == "--":
        parts = parts[1:]
    if not parts:
        print("Usage: autonomous terminal exec <name> -- <command>", file=sys.stderr)
        return 2
    command = " ".join(parts)
    entry = term_svc.exec_command(args.name, command, timeout=args.timeout, home=home)
    if args.json:
        _out(entry, as_json=True)
    else:
        print(entry["output"], end="" if entry["output"].endswith("\n") else "\n")
        print(t("terminal.done", code=entry["exit_code"]))
    return 0 if entry.get("exit_code") == 0 else 1


def cmd_terminal_log(args) -> int:
    home = _home_from_args(args)
    logs = term_svc.list_logs(args.name, limit=args.limit, home=home)
    _out(logs, as_json=args.json)
    return 0


def cmd_files_ls(args) -> int:
    home = _home_from_args(args)
    entries = files_svc.list_dir(args.name, args.path or ".", home=home)
    if args.json:
        _out(entries, as_json=True)
    else:
        for e in entries:
            kind = "d" if e["is_dir"] else "f"
            print(f"{kind}\t{e['path']}")
    return 0


def cmd_files_get(args) -> int:
    home = _home_from_args(args)
    src = files_svc.resolve(args.name, args.path, home=home)
    if not src.is_file():
        print("Not a file", file=sys.stderr)
        return 1
    dest = Path(args.output) if args.output else Path(src.name)
    dest.write_bytes(src.read_bytes())
    print(str(dest))
    return 0


def cmd_files_rm(args) -> int:
    home = _home_from_args(args)
    if not args.yes:
        print("Pass --yes to confirm", file=sys.stderr)
        return 2
    files_svc.delete_path(args.name, args.path, home=home)
    print(t("ok"))
    return 0


def cmd_job_show(args) -> int:
    home = _home_from_args(args)
    job = jobs_svc.get_job(args.id, home=home)
    _out(job, as_json=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", help="AUTONOMOUS_HOME override")
    common.add_argument("--json", action="store_true", help="JSON output")

    p = argparse.ArgumentParser(prog="autonomous", description="Autonomous bot hub CLI")
    p.add_argument("--version", action="version", version=f"autonomous {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", parents=[common], help="Initialize data dir, token, password")
    init.add_argument("--password", help="Login password (prompted if omitted)")
    init.set_defaults(func=cmd_init)

    serve = sub.add_parser("serve", parents=[common], help="Run or stop HTTP server")
    serve.add_argument(
        "serve_action",
        nargs="?",
        default="start",
        choices=["start", "stop"],
        help="start (default) or stop",
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument(
        "--dev",
        action="store_true",
        help="Autoreload when Python files under autonomous/ change",
    )
    serve.set_defaults(func=cmd_serve)

    health = sub.add_parser("health", parents=[common])
    health.set_defaults(func=cmd_health)

    bot = sub.add_parser("bot", parents=[common])
    bot_sub = bot.add_subparsers(dest="bot_cmd", required=True)

    bc = bot_sub.add_parser("create", parents=[common])
    bc.add_argument("name")
    bc.add_argument("--label")
    bc.add_argument("--internet", action="store_true", default=True)
    bc.add_argument("--no-internet", action="store_true")
    bc.set_defaults(func=cmd_bot_create)

    bl = bot_sub.add_parser("list", parents=[common])
    bl.set_defaults(func=cmd_bot_list)

    bs = bot_sub.add_parser("show", parents=[common])
    bs.add_argument("name")
    bs.set_defaults(func=cmd_bot_show)

    bd = bot_sub.add_parser("delete", parents=[common])
    bd.add_argument("name")
    bd.add_argument("--yes", action="store_true")
    bd.set_defaults(func=cmd_bot_delete)

    bset = bot_sub.add_parser("set", parents=[common])
    bset.add_argument("name")
    bset.add_argument("--label")
    bset.add_argument("--internet", action="store_true")
    bset.add_argument("--no-internet", action="store_true")
    bset.add_argument(
        "--capability",
        choices=["none", "terminal", "screen"],
        help="none removes the VM; terminal is an alias of screen (one VM, shell + desktop)",
    )
    bset.set_defaults(func=cmd_bot_set)

    chat = sub.add_parser("chat", parents=[common])
    chat_sub = chat.add_subparsers(dest="chat_cmd", required=True)
    cs = chat_sub.add_parser("send", parents=[common])
    cs.add_argument("name")
    cs.add_argument("text")
    cs.set_defaults(func=cmd_chat_send)
    ch = chat_sub.add_parser("history", parents=[common])
    ch.add_argument("name")
    ch.add_argument("--limit", type=int, default=50)
    ch.set_defaults(func=cmd_chat_history)
    cc = chat_sub.add_parser("clear", parents=[common])
    cc.add_argument("name")
    cc.add_argument("--yes", action="store_true")
    cc.set_defaults(func=cmd_chat_clear)

    desk = sub.add_parser("desk", parents=[common])
    desk_sub = desk.add_subparsers(dest="desk_cmd", required=True)
    dc = desk_sub.add_parser("create", parents=[common])
    dc.add_argument("name")
    dc.add_argument("--internet", action="store_true", default=False)
    dc.add_argument("--no-internet", action="store_true", default=False)
    dc.add_argument("--wait", action="store_true")
    dc.set_defaults(func=cmd_desk_create)
    dd = desk_sub.add_parser("destroy", parents=[common])
    dd.add_argument("name")
    dd.add_argument("--yes", action="store_true")
    dd.add_argument("--wait", action="store_true")
    dd.set_defaults(func=cmd_desk_destroy)
    dr = desk_sub.add_parser("restart", parents=[common])
    dr.add_argument("name")
    dr.set_defaults(func=cmd_desk_restart)
    drs = desk_sub.add_parser("reset", parents=[common])
    drs.add_argument("name")
    drs.add_argument("--yes", action="store_true")
    drs.set_defaults(func=cmd_desk_reset)
    ds = desk_sub.add_parser("status", parents=[common])
    ds.add_argument("name")
    ds.set_defaults(func=cmd_desk_status)

    term = sub.add_parser("terminal", parents=[common])
    term_sub = term.add_subparsers(dest="term_cmd", required=True)
    te = term_sub.add_parser("exec", parents=[common])
    te.add_argument("name")
    te.add_argument("cmd", nargs=argparse.REMAINDER, help="Command after --")
    te.add_argument("--timeout", type=int, default=30)
    te.set_defaults(func=cmd_terminal_exec)
    tl = term_sub.add_parser("log", parents=[common])
    tl.add_argument("name")
    tl.add_argument("--limit", type=int, default=50)
    tl.set_defaults(func=cmd_terminal_log)

    files = sub.add_parser("files", parents=[common])
    files_sub = files.add_subparsers(dest="files_cmd", required=True)
    fl = files_sub.add_parser("ls", parents=[common])
    fl.add_argument("name")
    fl.add_argument("path", nargs="?", default=".")
    fl.set_defaults(func=cmd_files_ls)
    fg = files_sub.add_parser("get", parents=[common])
    fg.add_argument("name")
    fg.add_argument("path")
    fg.add_argument("-o", "--output")
    fg.set_defaults(func=cmd_files_get)
    fr = files_sub.add_parser("rm", parents=[common])
    fr.add_argument("name")
    fr.add_argument("path")
    fr.add_argument("--yes", action="store_true")
    fr.set_defaults(func=cmd_files_rm)

    job = sub.add_parser("job", parents=[common])
    job_sub = job.add_subparsers(dest="job_cmd", required=True)
    js = job_sub.add_parser("show", parents=[common])
    js.add_argument("id")
    js.set_defaults(func=cmd_job_show)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AutonomousError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
