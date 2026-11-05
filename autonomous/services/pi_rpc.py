"""Long-lived Pi `--mode rpc` sessions (one per bot, host-side)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from autonomous import auth as auth_mod
from autonomous.ids import new_autonomous_id
from autonomous.paths import bot_pi_dir, default_home, serve_pid_path
from autonomous.services.pi_status import pi_env, resolve_pi_bin

log = logging.getLogger("autonomous.pi_rpc")

EventHandler = Callable[[dict[str, Any]], None]

_EXTENSIONS_DIR = Path(__file__).resolve().parent.parent / "pi_extensions"
_PI_EXTENSIONS = (
    _EXTENSIONS_DIR / "vault.ts",
    _EXTENSIONS_DIR / "vm.ts",
    _EXTENSIONS_DIR / "files.ts",
    _EXTENSIONS_DIR / "browser.ts",
    _EXTENSIONS_DIR / "botmail.ts",
    _EXTENSIONS_DIR / "events.ts",
    _EXTENSIONS_DIR / "chat_search.ts",
    _EXTENSIONS_DIR / "react.ts",
    _EXTENSIONS_DIR / "memory.ts",
    _EXTENSIONS_DIR / "approval.ts",
    _EXTENSIONS_DIR / "clarify.ts",
    _EXTENSIONS_DIR / "companion.ts",
)

_APPROVAL_SYSTEM_HINT = (
    "User approval: call ask_approval(prompt, title?) whenever you need an "
    "explicit Accept/Refuse before acting — especially if a core memory rule says "
    "to ask first (e.g. before a command). It shows a chat card and BLOCKS until "
    "the user clicks or writes in chat. On refuse: do not proceed. On accept: "
    "continue. If the tool returns human_redirect / cancelled with a chat message, "
    "follow that guidance (not a hard refusal)."
)

_MEMORY_SYSTEM_HINT = (
    "Shared household memory: core facts for this conversation are in the system "
    "prompt when this bot has memory access (loaded once per new conversation, "
    "not every message). Use memory_list / memory_get / memory_search for "
    "browse-tier facts. To store something, call memory_propose — chat card, "
    "returns immediately; keep working, never block or poll. "
    "TIER RULES: "
    "core = standing rules and always-important facts the agent must respect "
    "every turn — identity (preferred_name), hard preferences about how to act "
    "(e.g. « always ask approval before running a command »), safety/ops rules. "
    "browse = situational / nice-to-know details looked up when relevant — "
    "likes, food, address, hobbies, trivia (e.g. favourite_food=raclette). "
    "If unsure: browse. Newly approved core facts apply on the next conversation."
)

_CHAT_SEARCH_SYSTEM_HINT = (
    "Chat history: use chat_search(query, bot?, mode?) to find past messages "
    "across bots (keywords or a natural question). Share the returned "
    "/b/<bot>/discussion?msg=<id> link so the user can jump there. "
    "Never invent message ids."
)

_FILES_SYSTEM_HINT = (
    "Bot files (~/shared = ~/workspace, same as the Files inspector): use "
    "files_list, files_read, files_write, files_mkdir, files_delete, "
    "files_share_image, files_attach. "
    "These work WITHOUT host bash and WITHOUT a running desk. "
    "IMAGES (mandatory): call files_share_image(path) for each file, then paste the "
    "EXACT returned markdown line (![](/api/v1/bots/…/files/raw?path=…)) into your reply. "
    "FORBIDDEN: inventing image URLs, external http(s) links, or guessing paths — "
    "those break the chat. Only the markdown from files_share_image works. "
    "PDF/zip/other non-preview files: files_attach(path) → download card on the reply. "
    "Do NOT use attachments for images. Do NOT request a screen desk or vm_screenshot "
    "just to show a workspace image. "
    "Do NOT overwrite images with files_write. "
    "There is no host bash: shell commands run in the bot VM via vm_terminal_exec."
)

_BOTMAIL_SYSTEM_HINT = (
    "Inter-bot mail: bot_tell(to, content) sends a one-way message; "
    "bot_ask(to, content) asks and WAITS for a reply (blocks this run). "
    "The user may also type « Dit à @name … » or « Demande à @name … » in chat. "
    "When you receive « [Question de @x] », answer clearly in your next message; "
    "the answer is forwarded to @x. When you receive « [@x a répondu] » or a "
    "« Dit à » from a peer, continue with that information."
)

_MANAGER_SYSTEM_HINT = (
    "MANAGER / ORCHESTRATOR: you may list peers with bot_list and assign work with "
    "bot_delegate(to, task, expect_reply?). "
    "CRITICAL: you do NOT stay waiting for workers. Never use bot_ask for orchestration. "
    "bot_delegate sends the task AND tells the worker to relaunch you with "
    "« Dit à @you … » when finished (success or failure). After bot_delegate, continue "
    "other work or idle; when their Dit arrives, you are relaunched automatically. "
    "Formulate every multi-bot plan around that callback — do not poll or block."
)

def _events_system_hint(home) -> str:
    from autonomous.services.cronutil import user_clock

    clock = user_clock(home)
    tz = clock["timezone"]
    off = clock["utc_offset"]
    return (
        "Scheduled tasks & webhooks: use schedule_list/create/update/delete and "
        "webhook_list/create/update/delete. Cron is 5 fields (minute hour dom month dow) "
        f"in the user's timezone ({tz}, UTC{off}), set in Settings — not the host OS "
        "and not the VM clock. The server stores the UTC equivalent (cron_utc) and "
        "next_run_at in UTC. schedule_list shows the cron already in that timezone, "
        "plus cron_utc and the UTC next run — pass that same cron back on update, "
        "never invent a second timezone. To know the current time before writing a "
        f"cron, run `TZ={tz} date` with vm_terminal_exec — never `date -u` "
        "(the -u flag forces UTC and ignores TZ=), never invent the hour, "
        "never add the UTC offset on top of the cron hour, and "
        "never trust the VM clock's own zone. "
        "The schedule tool's Next fire line is the time you tell the user. "
        "If it fails with oneshot_too_far, that clock time already passed today: "
        "recompute from the local time in the error. "
        "recurring=false → delete after a successful fire, unless the next slot is "
        "within 15 minutes (a short burst such as every 5 minutes). "
        "For one hour of reminders, pin the day and the hour; hour '*' repeats the burst every hour. "
        "Webhooks expose a public token URL (/api/v1/hooks/<token>); GET/POST injects "
        "a user chat message (queued if busy). Only you create schedules and webhooks "
        "(schedule_create / webhook_create). The user pauses, resumes and deletes them "
        "in the Events inspector — there is no create form there."
    )

_CLARIFY_SYSTEM_HINT = (
    "Clarifying questions: call ask_clarify(prompt, title?, choices?, allow_text?) "
    "when you need a structured answer before continuing (a short text, or a pick "
    "from choices). It shows a chat card and BLOCKS until the user answers or "
    "writes in chat. choices = 2–8 short labels (click to answer). Omit choices "
    "for a short text field; set allow_text=true together with choices to allow "
    "either. Do not use ask_clarify for yes/no consent on a risky action — that "
    "is ask_approval. On human_redirect / cancelled, follow the chat message."
)

_REACT_SYSTEM_HINT = (
    "Reactions: call react(emoji) to put one emoji on the user message you are "
    "answering (❤️ after thanks, 👍 after a confirmation). It returns immediately "
    "and does NOT end the turn and does NOT replace a reply. If they still need "
    "an answer, an action, or any follow-up, write that text after the tool. "
    "If the reaction alone is the whole response, stop with no filler. "
    "Do not describe the tool call in the chat."
)

_VISION_SYSTEM_HINT = (
    "Vision budget: the LLM accepts only a small number of images per prompt "
    "(often 2). Autonomous already caps attached vision images. If many image "
    "files are listed, analyze at most that many per turn, then continue on the "
    "remaining paths in later turns — never pack every image into one prompt. "
    "Prefer paths + sequential turns over bulk vision."
)

_VAULT_SYSTEM_HINT = """\
VAULT (secrets are global, encrypted, and NEVER shown to you)
- By default you have access to nothing. Call vault_catalog first: if an entry matches the site (label/origin), call request_vault_access(entry_id) and wait for the user. Only if none exists use request_credentials / request_login / request_secret.
- A grant returns entry_id and the public fields (username, …), never the password. vault_granted lists what you already have: the account identity is its "user: …" — read it there, never invent an account or e-mail.
- Secrets reach the page only through vault_type(entry_id, field) into an already-focused field. Everything non-secret (username, search text) goes through vm_type. Never put a secret in the username field, never invent a password or key.
- NEVER reveal vault secrets in chat (quote / spell / hint), even on auth failure. Continue answering the task without the secret. If the user pastes a password, API key or token into the chat: call report_user_secret SILENTLY as your FIRST action — zero assistant text before or after (do not name the tool, do not say you will call it, do not explain). Do NOT put the secret in the tool args. Then stop and wait. Never invent passwords from memory. Never put a secret in a shell command the user can read.
- Full login procedure: see LOGIN in the desktop section."""

_VM_SYSTEM_HINT = """\
DESKTOP & BROWSER (server-side; works without the web UI open)

== 1. Desk and shell ==
- Two desk modes: terminal (shell only) and screen (GUI). vm_request_desk(mode) WAITS for the user; call nothing else meanwhile. Ask for screen only for GUI work (browser, clicks, drags). Check state with vm_desk_status. If the desk is down, ask the user once.
- Shell work: vm_terminal_exec (cwd /home/autonomous/workspace). Bot files (~/shared): files_*. Any command whose output you need (date, curl, ping, and the rest) is vm_terminal_exec — if there is no desk it asks the user for a terminal VM and waits. Never invent command output. There is no host bash on the Autonomous server: the agent cannot run commands on the host machine.
- Chrome is already started by the screen desk: check with browser_tabs, then browser_navigate. Only if no Chrome exists: `setsid bot-chrome 'https://…' >/dev/null 2>&1 &` (it never exits: never run it in the foreground, never start a second Chrome).

== 2. Tools: what each one is for ==
- READ the page (no side effects), from best to last resort: browser_snapshot (controls with screen=x,y, in_viewport, overlays, [FOCUSED], [filled N chars]) > browser_text > browser_links(query) > browser_html. browser_frames_snapshot for widgets and forms inside iframes (returns center_screen / bbox_screen).
- WAIT: browser_wait_load after any click, submit, redirect or Chrome launch (bounded, returns as soon as loaded; on timed_out=true carry on). Never `sleep N` to wait for a page.
- SEE: vm_look returns a text description of the screen (text, errors, blockers, form state). Use it when the DOM tools are empty or inconclusive, after an action whose result you cannot read, and ALWAYS before telling the user what went wrong (never quote an error you did not read). Its coordinates are guesses: NEVER use them. vm_screenshot is for the user chat only.
- ACT with real VNC input: vm_click, vm_drag, vm_type, vm_scroll (dy>0 = down), vm_key. Avoid browser_scroll / browser_click_selector on anti-bot pages (no real wheel/pointer events).
- LOCATE what the DOM cannot give (canvas, images, native dialogs): vm_ground(English description, action_hint=<gesture>), slow (~10 s), returns geometry only.

== 3. Action loop (any website, no site-specific recipes) ==
1. NAVIGATE BY CONTROLS, NOT BY GUESSED URLs. Start from the site's homepage. Never type a URL you have not SEEN (on screen, or returned by browser_links / a snapshot): guessed paths and sub-domains (/account, /orders, /mescommandes…) lead to 404s, certificate errors and anti-bot flags, and waste your time. Reach every goal by clicking visible menus, account/profile controls and links. If a menu is not in the DOM snapshot, open it with a click (account / profile / hamburger control in the header; vm_look tells you what is there, vm_ground locates it), then snapshot again and read its links. Never bypass a browser security warning: go back.
2. Observe: first browser_snapshot of a page WITHOUT query. It reports 'BLOCKING OVERLAY' (with its buttons) and '[COVERED by …]' controls. Dismiss overlays first (cookie/consent banners, modals). Native dialogs are not in the DOM: vm_look, vm_ground + vm_click, or vm_key Return. A click that changes nothing = suspect an overlay first.
3. Decide the gesture (left_click | right_click | double | drag), then WHERE:
   - control in the DOM: use its screen=x,y from browser_snapshot / browser_frames_snapshot directly (exact and fast; vm_ground only if it is [COVERED]). Off-screen (in_viewport=false): vm_scroll until visible.
   - not in the DOM: vm_ground. If ok=false, NEVER click the rejected point (it is usually another control, e.g. a « send me a code » button): re-observe, try browser_frames_snapshot, reword, or scroll.
   Only click a control whose label matches your intent.
4. Execute the one matching tool (click → vm_click, drag → vm_drag), then VERIFY with a fresh snapshot/text. Nothing changed → change approach; never repeat the same action more than twice.
5. Text fields: click the field, then vm_type; check browser_snapshot shows [filled N chars] rather than retyping blindly or switching to another login method.
6. Verification widgets (checkbox, slider, puzzle, retry button) are ordinary UI. browser_navigate / browser_wait_load print a « SLIDE-TO-VERIFY WIDGET » line with the exact vm_drag(x, y, x2, y2): do that ONE drag at once (no vm_look / vm_ground first), then browser_wait_load. Otherwise find the widget with browser_frames_snapshot WITHOUT query (cross-origin iframes included). Buttons/checkboxes → vm_click. Sliders → ONE vm_drag from the handle's center to the far end of its track (never click a track, never aim at a point you guessed). Verify with browser_wait_load / browser_snapshot (vm_look if unclear); if a retry control or a fresh widget appears, use it at once; at most 2 attempts, then step back.

== 4. Block pages ==
A page that only says access is restricted / denied / unusual traffic, with NO widget to act on (a verification widget is NOT a block page: act on it), is a decision about your browsing SESSION (cookies, state), not a puzzle.
- Do not reload in a loop. Do not curl/wget that site from the VM, write your own CDP/websocket/input scripts, or pip/apt install anything.
- Recovery, ONLY once vm_look confirms such a page: browser_reset_session (forgets cookies/cache/storage = a fresh visitor), browser_navigate to the homepage, start over (you are logged out: log in again). A block right after a verification widget is a failed attempt, not the end: a reset gives a fresh widget, so do the widget again. If the next page is blocked again, use your SECOND reset; do not report failure before both resets were used. Only then stop and report exactly what you saw and tried.

== 5. LOGIN ==
vault_catalog → request_vault_access → click the username field (screen=x,y from the snapshot) → vm_type the username from the grant → click the password field → vault_type (password only) → submit → browser_wait_load → browser_text to see where you landed.
- Prefer the password path; do not ask the site to send a code unless no password path exists.
- If a one-time code is sent by e-mail/SMS: request_credentials with fields [{id:'otp',label:'Code',secret:true}] (secret=true is required), wait for approval, then vm_type it. Never invent a code.
- If the page asks to approve on another device / push notification (no code to type): do NOT open an OTP vault form — tell the user in chat and wait (browser_wait_load / vm_look). If a vault tool returns human_redirect / cancelled with their message, follow that guidance; it is not a refusal.

FORBIDDEN: inventing passwords or codes, quoting/revealing any secret in chat, site-specific hacks, bypass scripts."""



def _serve_api_base(home: Path | None = None) -> str | None:
    path = serve_pid_path(home or default_home())
    if not path.is_file():
        return None
    host = "127.0.0.1"
    port = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("host="):
                host = line.split("=", 1)[1].strip() or host
            elif line.startswith("port="):
                try:
                    port = int(line.split("=", 1)[1].strip())
                except ValueError:
                    port = None
    except OSError:
        return None
    if not port:
        return None
    if host in ("0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    return f"http://{host}:{port}/api/v1"


def _pi_session_env(bot: str, home: Path | None = None) -> dict[str, str]:
    env = pi_env()
    root = home or default_home()
    base = _serve_api_base(root)
    # Scoped bot token (abt_…) — not the admin data/token Bearer.
    token = auth_mod.issue_bot_api_token(bot, home=root)
    if base:
        env["AUTONOMOUS_API_BASE"] = base
    env["AUTONOMOUS_TOKEN"] = token
    env["AUTONOMOUS_BOT"] = bot
    env["AUTONOMOUS_HOME"] = str(root)
    return env


class PiRpcError(RuntimeError):
    pass


class PiRpcSession:
    """One Pi RPC child process bound to a bot working directory."""

    def __init__(
        self,
        bot: str,
        *,
        session_id: str,
        model: str | None = None,
        home: Path | None = None,
        on_event: EventHandler | None = None,
    ) -> None:
        self.bot = bot
        self.session_id = session_id
        self.model = (model or "").strip()
        self.home = home
        self.on_event = on_event
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._reader: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._alive = False
        self._stderr_tail: list[str] = []

    @property
    def alive(self) -> bool:
        return bool(self._alive and self._proc and self._proc.poll() is None)

    def start(self) -> None:
        with self._lock:
            if self.alive:
                return
            binary = resolve_pi_bin()
            if not binary:
                raise PiRpcError("Pi is not installed")
            cwd = bot_pi_dir(self.bot, self.home)
            session_dir = cwd / "sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            is_manager = False
            try:
                from autonomous.services import bots as bots_svc

                row = bots_svc.get_bot(self.bot, home=self.home)
                is_manager = bool(row.get("is_manager"))
            except Exception:
                is_manager = False
            cmd = [
                binary,
                "--mode",
                "rpc",
                "--session-id",
                self.session_id,
                "--session-dir",
                str(session_dir),
                "--name",
                f"autonomous-{self.bot}",
                "--no-context-files",
                "--offline",
                # Never expose Pi bash on the host — shell work is VM-only.
                "--exclude-tools",
                "bash",
            ]
            for ext in _PI_EXTENSIONS:
                if ext.is_file():
                    cmd.extend(["--extension", str(ext)])
            if self.model:
                cmd.extend(["--model", self.model])
            memory_core = ""
            try:
                from autonomous.services import memory as memory_svc

                memory_core = memory_svc.prompt_prefix_for_bot(
                    self.bot, home=self.home
                )
            except Exception:
                log.exception("memory core block failed for %s", self.bot)
            role_parts = [
                p
                for p in (
                    memory_core,
                    _VAULT_SYSTEM_HINT,
                    _FILES_SYSTEM_HINT,
                    _VM_SYSTEM_HINT,
                    _BOTMAIL_SYSTEM_HINT,
                    _MANAGER_SYSTEM_HINT if is_manager else "",
                    _events_system_hint(self.home),
                    _MEMORY_SYSTEM_HINT,
                    _APPROVAL_SYSTEM_HINT,
                    _CLARIFY_SYSTEM_HINT,
                    _CHAT_SEARCH_SYSTEM_HINT,
                    _REACT_SYSTEM_HINT,
                    _VISION_SYSTEM_HINT,
                )
                if p
            ]
            if role_parts:
                cmd.extend(["--append-system-prompt", "\n\n".join(role_parts)])
            log.info("Starting Pi RPC for bot=%s session=%s model=%s", self.bot, self.session_id, self.model)
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(cwd),
                env=_pi_session_env(self.bot, self.home),
                bufsize=0,
            )
            self._alive = True
            self._reader = threading.Thread(target=self._read_stdout, name=f"pi-out-{self.bot}", daemon=True)
            self._stderr_thread = threading.Thread(
                target=self._read_stderr, name=f"pi-err-{self.bot}", daemon=True
            )
            self._reader.start()
            self._stderr_thread.start()
        # Handshake outside the lock — request() also needs _lock (non-reentrant).
        state = self.request("get_state", timeout=20.0)
        if not state.get("success"):
            err = state.get("error") or "get_state failed"
            self.stop()
            raise PiRpcError(str(err))

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
            self._alive = False
            self._proc = None
        if not proc:
            return
        try:
            if proc.poll() is None:
                try:
                    self._write({"type": "abort"})
                except Exception:
                    pass
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        finally:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            with self._lock:
                for waiter in self._pending.values():
                    waiter["error"] = "session stopped"
                    waiter["event"].set()
                self._pending.clear()

    def request(self, command_type: str, timeout: float = 30.0, **fields: Any) -> dict[str, Any]:
        if not self.alive:
            raise PiRpcError("Pi session is not running")
        req_id = fields.pop("id", None) or str(uuid.uuid4())
        payload = {"id": req_id, "type": command_type, **fields}
        event = threading.Event()
        slot: dict[str, Any] = {"event": event, "response": None, "error": None}
        with self._lock:
            self._pending[req_id] = slot
        try:
            self._write(payload)
            if not event.wait(timeout):
                raise PiRpcError(f"Pi RPC timeout on {command_type}")
            if slot["error"]:
                raise PiRpcError(str(slot["error"]))
            return slot["response"] or {}
        finally:
            with self._lock:
                self._pending.pop(req_id, None)

    def prompt(
        self,
        message: str,
        *,
        images: list[dict[str, Any]] | None = None,
        streaming_behavior: str | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {"message": message}
        if images:
            fields["images"] = images
        if streaming_behavior:
            fields["streamingBehavior"] = streaming_behavior
        return self.request("prompt", timeout=30.0, **fields)

    def steer(self, message: str) -> dict[str, Any]:
        """Queue a steering message (delivered after current tool turn, before next LLM call)."""
        return self.request("steer", timeout=15.0, message=message)

    def abort(self) -> None:
        """Best-effort abort. Never block long — Pi may be stuck on a provider HTTP call."""
        if not self.alive:
            return
        try:
            self._write({"type": "abort"})
        except Exception:
            pass

    def set_model(self, model_ref: str) -> dict[str, Any]:
        provider, _, model_id = model_ref.partition("/")
        if not model_id:
            model_id = provider
            provider = ""
        fields: dict[str, Any] = {"modelId": model_id}
        if provider:
            fields["provider"] = provider
        resp = self.request("set_model", timeout=20.0, **fields)
        if resp.get("success"):
            self.model = model_ref
        return resp

    def _write(self, obj: dict[str, Any]) -> None:
        proc = self._proc
        if not proc or not proc.stdin:
            raise PiRpcError("Pi stdin closed")
        line = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            proc.stdin.write(line)
            proc.stdin.flush()

    def _read_stdout(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        buf = b""
        while self._alive and proc.poll() is None:
            try:
                chunk = proc.stdout.read(4096)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                raw = buf[:nl]
                buf = buf[nl + 1 :]
                if raw.endswith(b"\r"):
                    raw = raw[:-1]
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    log.warning("Pi RPC bad JSON: %s", raw[:200])
                    continue
                self._dispatch(record)
        was_alive = self._alive
        self._alive = False
        if was_alive and self.on_event:
            try:
                self.on_event({"type": "agent_settled", "aborted": True, "reason": "process_ended"})
            except Exception:
                pass
        with self._lock:
            for waiter in self._pending.values():
                if not waiter["event"].is_set():
                    waiter["error"] = "pi process ended"
                    waiter["event"].set()

    def _read_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for line in iter(proc.stderr.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            self._stderr_tail.append(text)
            if len(self._stderr_tail) > 50:
                self._stderr_tail = self._stderr_tail[-50:]
            log.debug("pi[%s] stderr: %s", self.bot, text)

    def _dispatch(self, record: dict[str, Any]) -> None:
        rtype = record.get("type")
        if rtype == "response":
            req_id = record.get("id")
            if req_id:
                with self._lock:
                    slot = self._pending.get(req_id)
                if slot:
                    slot["response"] = record
                    if not record.get("success"):
                        slot["error"] = record.get("error") or record.get("message") or "command failed"
                    slot["event"].set()
            return
        if self.on_event:
            try:
                self.on_event(record)
            except Exception:
                log.exception("Pi event handler failed for bot=%s", self.bot)


class PiSessionManager:
    """Process table: bot name → PiRpcSession."""

    def __init__(self) -> None:
        self._sessions: dict[str, PiRpcSession] = {}
        self._lock = threading.Lock()

    def get(self, bot: str) -> PiRpcSession | None:
        with self._lock:
            return self._sessions.get(bot)

    def ensure(
        self,
        bot: str,
        *,
        session_id: str,
        model: str | None,
        home: Path | None = None,
        on_event: EventHandler | None = None,
    ) -> PiRpcSession:
        with self._lock:
            existing = self._sessions.get(bot)
            if existing and existing.alive:
                if model and existing.model != model:
                    try:
                        existing.set_model(model)
                    except PiRpcError as exc:
                        log.warning("set_model failed for %s: %s", bot, exc)
                if on_event:
                    existing.on_event = on_event
                return existing
            if existing:
                existing.stop()
            session = PiRpcSession(
                bot,
                session_id=session_id,
                model=model,
                home=home,
                on_event=on_event,
            )
            self._sessions[bot] = session
        session.start()
        return session

    def stop(self, bot: str) -> None:
        with self._lock:
            session = self._sessions.pop(bot, None)
        if session:
            session.stop()

    def abort(self, bot: str) -> None:
        session = self.get(bot)
        if session:
            session.abort()

    def steer(self, bot: str, message: str) -> dict[str, Any] | None:
        session = self.get(bot)
        if not session or not session.alive:
            return None
        try:
            return session.steer(message)
        except Exception:
            return None

    def stop_all(self) -> None:
        with self._lock:
            bots = list(self._sessions.keys())
        for bot in bots:
            self.stop(bot)


MANAGER = PiSessionManager()


def new_session_id(_bot: str | None = None) -> str:
    """Opaque Pi session id. Mapping bot/chat ↔ session = colonne `bots.pi_session_id`."""
    return new_autonomous_id()


def purge_pi_sessions(bot: str, home: Path | None = None) -> int:
    """Delete on-disk Pi session transcripts for a bot. Returns file count removed."""
    sessions = bot_pi_dir(bot, home) / "sessions"
    if not sessions.is_dir():
        return 0
    n = 0
    for path in sessions.iterdir():
        if path.is_file():
            try:
                path.unlink()
                n += 1
            except OSError as exc:
                log.warning("Could not remove Pi session %s: %s", path, exc)
    return n


_SECRET_LINE_RE = re.compile(
    r"(?i)^\s*(?:mot\s*de\s*passe|password|passwd|secret|api[_ ]?key|token|"
    r"clé(?:\s*api)?)\s*[:=]\s*(.+)\s*$"
)


def _fragments_from_leaked_text(text: str) -> list[str]:
    """Extract likely secret values from a pasted user message."""
    out: list[str] = []
    raw = str(text or "")
    if raw.strip():
        out.append(raw)
    for line in raw.splitlines():
        m = _SECRET_LINE_RE.match(line.strip())
        if not m:
            continue
        val = m.group(1).strip().strip("\"'`")
        if len(val) >= 4:
            out.append(val)
    # Longest first so we replace full message before fragments.
    out.sort(key=len, reverse=True)
    # Dedupe while preserving order.
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return uniq


def _scrub_string(value: str, replacements: list[tuple[str, str]], home: Path | None) -> str:
    text = value
    for old, new in replacements:
        if old and old in text:
            text = text.replace(old, new)
    try:
        from autonomous.services import vault as vault_svc

        text = vault_svc.redact_secrets_in_text(text, home=home)
    except Exception:
        pass
    return text


def _scrub_json_value(value: Any, replacements: list[tuple[str, str]], home: Path | None) -> Any:
    if isinstance(value, str):
        return _scrub_string(value, replacements, home)
    if isinstance(value, list):
        return [_scrub_json_value(v, replacements, home) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_json_value(v, replacements, home) for k, v in value.items()}
    return value


def scrub_pi_session_files(
    bot: str,
    *,
    leaked_text: str = "",
    placeholder: str = (
        "Ce message a été supprimé car un secret a été détecté."
    ),
    home: Path | None = None,
) -> dict[str, Any]:
    """Rewrite on-disk Pi session jsonl to remove a pasted secret.

    Replaces the full leaked user text and extracted secret fragments, then
    redacts known vault secrets. Caller should stop the live Pi process first
    so RAM context cannot keep the cleartext.
    """
    sessions = bot_pi_dir(bot, home) / "sessions"
    if not sessions.is_dir():
        return {"files": 0, "lines_changed": 0}

    fragments = _fragments_from_leaked_text(leaked_text)
    replacements = [(frag, placeholder if frag == leaked_text else "[secret retiré]") for frag in fragments]
    # Full message → conversational placeholder; fragments → short redaction.
    if leaked_text.strip():
        replacements = [(leaked_text, placeholder)] + [
            (frag, "[secret retiré]")
            for frag in fragments
            if frag != leaked_text
        ]

    files = 0
    lines_changed = 0
    for path in sorted(sessions.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".jsonl":
            continue
        try:
            raw_lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            log.warning("Could not read Pi session %s: %s", path, exc)
            continue
        out_lines: list[str] = []
        changed = False
        for line in raw_lines:
            if not line.strip():
                out_lines.append(line)
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                scrubbed_line = _scrub_string(line, replacements, home)
                if scrubbed_line != line:
                    changed = True
                    lines_changed += 1
                out_lines.append(scrubbed_line)
                continue
            new_obj = _scrub_json_value(obj, replacements, home)
            new_line = json.dumps(new_obj, ensure_ascii=False, separators=(",", ":"))
            if new_line != line:
                changed = True
                lines_changed += 1
            out_lines.append(new_line)
        if changed:
            tmp = path.with_suffix(path.suffix + ".scrubtmp")
            try:
                tmp.write_text("\n".join(out_lines) + ("\n" if raw_lines else ""), encoding="utf-8")
                tmp.replace(path)
                files += 1
            except OSError as exc:
                log.warning("Could not write scrubbed Pi session %s: %s", path, exc)
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
    return {"files": files, "lines_changed": lines_changed}


def wipe_bot_files(bot: str, home: Path | None = None) -> None:
    """Remove the whole host bot directory (Pi sessions, VM home, downloads)."""
    import shutil

    root = (home or default_home()) / "bots" / bot
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
        log.info("Wiped bot files for %s (%s)", bot, root)
