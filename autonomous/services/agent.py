"""Agent backends — Pi RPC (streaming) + NullAgent."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import settings as settings_svc
from autonomous.services.events import BUS
from autonomous.services.pi_rpc import MANAGER, PiRpcError, new_session_id
from autonomous.services.pi_status import status as pi_status

log = logging.getLogger("autonomous.agent")

# bot → settled Event for the worker currently owning the Pi prompt.
# Prevents desk/vault resume from starting a second start_run (Pi: "already processing")
# which would also steal session.on_event and orphan tool cards.
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_RUNS: dict[str, threading.Event] = {}

# Last Pi progress (token / tool / settle) — silent-busy watchdog (server-side).
_PROGRESS_LOCK = threading.Lock()
_LAST_PROGRESS: dict[str, float] = {}
_LAST_SILENT_RETRY: dict[str, float] = {}
_SILENT_BUSY_COOLDOWN_SEC = 90.0

# bot → True : prochain settle/abort ne doit pas poster « ⚠️ This operation was aborted »
# (ex. report_user_secret : abort volontaire, message remis dans la saisie).
_SILENT_ABORT_LOCK = threading.Lock()
_SILENT_ABORT: set[str] = set()


def mark_silent_abort(bot: str) -> None:
    with _SILENT_ABORT_LOCK:
        _SILENT_ABORT.add(bot)


def consume_silent_abort(bot: str) -> bool:
    with _SILENT_ABORT_LOCK:
        if bot in _SILENT_ABORT:
            _SILENT_ABORT.discard(bot)
            return True
        return False


_ABORT_PLACEHOLDER_RE = re.compile(
    r"(?is)^\s*(?:⚠️\s*)?(?:This operation was aborted|operation was aborted|"
    r"⏹\s*Stopped\.?|Run interrompu)\s*$"
)


def _is_abort_placeholder(text: str) -> bool:
    return bool(_ABORT_PLACEHOLDER_RE.match(str(text or "").strip()))


def run_in_progress(bot: str) -> bool:
    """True while a PiAgent worker is mid-prompt (tools / LLM), even if status=waiting."""
    with _ACTIVE_LOCK:
        ev = _ACTIVE_RUNS.get(bot)
        return bool(ev is not None and not ev.is_set())


def touch_run_progress(bot: str) -> None:
    """Mark live agent progress so the silent-busy watchdog does not fire."""
    name = str(bot or "").strip()
    if not name:
        return
    with _PROGRESS_LOCK:
        _LAST_PROGRESS[name] = time.monotonic()


def clear_active_run(bot: str) -> None:
    """Drop any in-memory run slot for ``bot`` (stop / crash recovery).

    ``stop_run`` used to leave a live Event in ``_ACTIVE_RUNS`` while forcing
    DB status back to ``idle``. Later ``start_run`` then hit
    ``start_run skipped — run already in progress`` forever until process restart.
    """
    with _ACTIVE_LOCK:
        ev = _ACTIVE_RUNS.pop(bot, None)
        if ev is not None and not ev.is_set():
            ev.set()
    with _PROGRESS_LOCK:
        _LAST_PROGRESS.pop(str(bot or "").strip(), None)


_RESTART_TOOL_ERROR = "Agent session interrupted (server restart)."


def has_pending_human_wait(bot: str, *, home: Path | None = None) -> bool:
    """True when a blocking chat card still needs the user."""
    try:
        from autonomous.services import approvals as approval_svc

        if approval_svc.list_pending_for_bot(bot, home=home):
            return True
    except Exception:
        pass
    try:
        from autonomous.services import clarifies as clarify_svc

        if clarify_svc.list_pending_for_bot(bot, home=home):
            return True
    except Exception:
        pass
    try:
        from autonomous.services import vault as vault_svc

        if vault_svc.list_pending_for_bot(bot, home=home):
            return True
    except Exception:
        pass
    try:
        from autonomous.services import desk as desk_svc

        flags = desk_svc._desk_request_flags(bot, home=home)
        if flags.get("pending_state") == "pending":
            return True
    except Exception:
        pass
    try:
        from autonomous.services import household as household_svc

        if household_svc.list_pending_delete_for_bot(bot, home=home):
            return True
    except Exception:
        pass
    return False


def abort_streaming_assistants(bot: str, *, home: Path | None = None) -> int:
    """Seal leftover streaming assistant bubbles after a dead process."""
    import json

    from autonomous.db import get_db

    n = 0
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT id, content, meta_json FROM messages
            WHERE bot = ? AND role = 'assistant'
            ORDER BY created_at DESC LIMIT 5
            """,
            (bot,),
        ).fetchall()
    for row in rows:
        meta = json.loads(row["meta_json"] or "{}")
        if not meta.get("streaming"):
            continue
        chat_svc.finalize_assistant(
            bot,
            row["id"],
            row["content"] or "⏹ Stopped.",
            home=home,
            meta={**meta, "aborted": True, "restart": True},
        )
        n += 1
    return n


def recover_stale_runs(*, home: Path | None = None) -> list[str]:
    """Clean bots left ``busy`` (or orphan ``waiting``) after process restart.

    Dev reloader / crash kills in-memory Pi workers while SQLite still says
    ``busy``. Without this, the Working orb stays forever and queued
    webhooks/messages never drain.

    ``waiting`` with a pending vault/approval/clarify/desk card is kept so the
    user can finish the form; otherwise it is treated as stale.
    """
    recovered: list[str] = []
    for bot in bots_svc.list_bots(home=home):
        name = str(bot.get("name") or "")
        if not name:
            continue
        status = str(bot.get("status") or "idle").strip()
        if status == "waiting":
            clear_active_run(name)
            if has_pending_human_wait(name, home=home):
                continue
        elif status != "busy":
            continue
        else:
            clear_active_run(name)

        try:
            MANAGER.abort(name)
        except Exception:
            pass
        try:
            MANAGER.stop(name)
        except Exception:
            pass
        try:
            chat_svc.close_running_tools(
                name,
                error=_RESTART_TOOL_ERROR,
                home=home,
                hint_resume=True,
            )
        except Exception:
            log.exception("recover: close_running_tools failed for %s", name)
        try:
            from autonomous.services import llm_turns as llm_turns_svc

            llm_turns_svc.close_running_turns(
                name, home=home, error=_RESTART_TOOL_ERROR
            )
        except Exception:
            log.exception("recover: close_running llm_turns failed for %s", name)
        try:
            abort_streaming_assistants(name, home=home)
        except Exception:
            log.exception("recover: abort streaming failed for %s", name)
        try:
            bots_svc.patch_bot(name, {"status": "idle"}, home=home)
        except Exception:
            log.exception("recover: idle patch failed for %s", name)

        drained = False
        try:
            drained = bool(chat_svc.drain_queued_user_messages(name, home=home))
        except Exception:
            log.exception("recover: drain queued failed for %s", name)
        if not drained:
            # Auto-resume unfinished work — do not leave a manual Resume card
            # (system must continue with no browser open).
            try:
                out = chat_svc.retry_unprocessed(name, home=home)
                log.info(
                    "recover: auto-retry bot=%s action=%s",
                    name,
                    (out or {}).get("action"),
                )
            except Exception:
                log.exception("recover: auto-retry failed for %s", name)

        recovered.append(name)
        log.info("recovered stale run for bot %s (was %s)", name, status)
    return recovered


def recover_silent_busy_runs(
    *,
    home: Path | None = None,
    grace_sec: float | None = None,
) -> list[str]:
    """Server watchdog. It never abort/stops a live Pi process.

    A running agent can sit for hours (a long tool, a slow model). Nothing
    here ends it. The user stops it from the UI (Working orb → ``stop_run``).

    This only resumes work when Pi is already gone:
    - ``busy`` with no live worker (zombie status) → ``retry_unprocessed``;
    - leftover pending Resume cards while idle;
    - idle retryable failures, and turns cut after a preamble plus tool cards.

    ``grace_sec`` is accepted for callers and ignored: duration is not a stop.
    """
    del grace_sec
    recovered: list[str] = []
    now = time.monotonic()
    for bot in bots_svc.list_bots(home=home):
        name = str(bot.get("name") or "")
        if not name:
            continue
        if has_pending_human_wait(name, home=home):
            continue

        status = str(bot.get("status") or "idle").strip()
        pending_card = False
        try:
            pending_card = bool(chat_svc.pending_resume_card(name, home=home))
        except Exception:
            pending_card = False

        live = run_in_progress(name)
        with _PROGRESS_LOCK:
            last_retry = _LAST_SILENT_RETRY.get(name, 0.0)

        should = False
        if status == "busy":
            if live:
                continue
            # DB busy but no worker → zombie. Nothing live to kill.
            should = True
        elif status == "idle" and not live:
            if pending_card:
                should = True
            else:
                try:
                    should = bool(
                        chat_svc.retryable_failed_turn(name, home=home)
                    ) or bool(chat_svc.turn_ended_on_tool(name, home=home))
                except Exception:
                    should = False

        if not should:
            continue
        if (now - last_retry) < _SILENT_BUSY_COOLDOWN_SEC:
            continue

        try:
            out = chat_svc.retry_unprocessed(name, home=home)
        except Exception:
            log.exception("silent-busy retry failed for %s", name)
            continue
        with _PROGRESS_LOCK:
            _LAST_SILENT_RETRY[name] = time.monotonic()
            _LAST_PROGRESS.pop(name, None)
        recovered.append(name)
        log.warning(
            "silent-busy recovered bot=%s action=%s live_worker=%s pending_card=%s",
            name,
            (out or {}).get("action"),
            live,
            pending_card,
        )
    return recovered


def _register_run(bot: str, settled: threading.Event) -> bool:
    """Claim the active-run slot. False if another run still owns it."""
    with _ACTIVE_LOCK:
        prev = _ACTIVE_RUNS.get(bot)
        if prev is not None and not prev.is_set():
            return False
        _ACTIVE_RUNS[bot] = settled
        return True


def _release_run(bot: str, settled: threading.Event) -> bool:
    """Drop our slot if we still own it. True when we owned it."""
    with _ACTIVE_LOCK:
        if _ACTIVE_RUNS.get(bot) is settled:
            _ACTIVE_RUNS.pop(bot, None)
            return True
        return False


def _owns_run(bot: str, settled: threading.Event) -> bool:
    """True when this worker still holds the slot (delete / reclaim may have taken it)."""
    with _ACTIVE_LOCK:
        return _ACTIVE_RUNS.get(bot) is settled


def _is_already_processing_error(err: str | None) -> bool:
    if not err:
        return False
    return "already processing" in str(err).lower()


# Inter-bot mail: no tool cards — only received exchange bubbles in chat.
_HIDDEN_TOOL_CARDS = frozenset(
    {
        "bot_list",
        "bot_tell",
        "bot_ask",
        "bot_delegate",
        "bot_models",
        "bot_create",
        "bot_delete",
        "schedule_list",
        "schedule_create",
        "schedule_update",
        "schedule_delete",
        "webhook_list",
        "webhook_create",
        "webhook_update",
        "webhook_delete",
        # Inline markdown / attach card — no tool card noise.
        "files_share_image",
        # Batch-order marker: not a user-visible tool.
        "batch_sequential",
        "files_attach",
        "files_claim_mail",
        # Shared memory: MemoryProposalCard only (no 🔧 dump in chat).
        "memory_propose",
        "memory_list",
        "memory_get",
        "memory_search",
        "notebook_list",
        "notebook_get",
        "notebook_remember",
        "notebook_close",
        # Approval: ApprovalCard only.
        "ask_approval",
        # Clarify: ClarifyCard only.
        "ask_clarify",
        # User secret report: system card only.
        "report_user_secret",
        # Chat history search — no tool card noise.
        "chat_search",
        # Emoji on the user bubble — no tool card.
        "react",
        # Desk auth: DeskRequestCard only (no « vm_request_desk · En cours » tool row).
        "vm_request_desk",
    }
)

# Desk pointer tools — keep coords in meta for chat analysis overlays.
_POINTER_TOOLS = frozenset({"vm_click", "vm_drag", "vm_scroll"})


class AgentBackend(Protocol):
    def start_run(
        self,
        bot: str,
        message: str,
        *,
        home: Path | None = None,
        images: list[dict[str, Any]] | None = None,
    ) -> str: ...

    def stop_run(self, bot: str, *, home: Path | None = None) -> None: ...


class NullAgent:
    """No-op agent used when settings.agent_backend == 'null'."""

    def start_run(
        self,
        bot: str,
        message: str,
        *,
        home: Path | None = None,
        images: list[dict[str, Any]] | None = None,
    ) -> str:
        return ""

    def stop_run(self, bot: str, *, home: Path | None = None) -> None:
        return None


def compaction_notice(record: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Chat line for a Pi compaction event. None when the record is unrelated.

    The full summary stays inside the Pi session. The thread only records that
    a summary started, finished, failed, or was cancelled, plus token counts.
    """
    rtype = record.get("type")
    if rtype not in ("compaction_start", "compaction_end"):
        return None
    reason = str(record.get("reason") or "").strip()
    if rtype == "compaction_start":
        return (
            "Pi résume la conversation…",
            {"kind": "compaction", "status": "running", "reason": reason},
        )
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    aborted = bool(record.get("aborted"))
    error = str(record.get("errorMessage") or "").strip()
    if aborted:
        status = "aborted"
        text = "Le résumé de la conversation a été annulé."
    elif error:
        status = "error"
        text = "Le résumé de la conversation a échoué."
    else:
        status = "done"
        text = "Pi a résumé la conversation."
    meta: dict[str, Any] = {
        "kind": "compaction",
        "status": status,
        "reason": reason,
    }
    for src, key in (
        ("tokensBefore", "tokens_before"),
        ("estimatedTokensAfter", "tokens_after"),
    ):
        value = result.get(src)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        meta[key] = int(value)
    if error:
        meta["error"] = error[:500]
    return text, meta


class PiAgent:
    """Drive one Pi RPC session per bot; stream tokens via SSE."""

    def start_run(
        self,
        bot: str,
        message: str,
        *,
        home: Path | None = None,
        images: list[dict[str, Any]] | None = None,
    ) -> str:
        info = pi_status()
        if not info.get("ready"):
            chat_svc.send_message(
                bot,
                _not_ready_text(info),
                role="system",
                home=home,
                trigger_agent=False,
            )
            return ""

        row = bots_svc.get_bot(bot, home=home)
        model = (row.get("model") or "").strip()
        if not model:
            chat_svc.send_message(
                bot,
                "No model selected for this bot. Pick one in Details or Settings.",
                role="system",
                home=home,
                trigger_agent=False,
            )
            return ""

        session_id = (row.get("pi_session_id") or "").strip() or new_session_id(bot)
        if not row.get("pi_session_id"):
            bots_svc.patch_bot(bot, {"pi_session_id": session_id}, home=home)

        settled = threading.Event()
        if not _register_run(bot, settled):
            # Stale slot: DB idle (or waiting) but memory still holds a dead run
            # after stop/abort without release. Steal the slot once.
            stale_status = (row.get("status") or "idle").strip()
            if stale_status in ("idle", "waiting"):
                log.warning(
                    "start_run reclaiming stale active slot for %s (db=%s)",
                    bot,
                    stale_status,
                )
                clear_active_run(bot)
            if not _register_run(bot, settled):
                log.warning("start_run skipped for %s — run already in progress", bot)
                return "busy"

        touch_run_progress(bot)
        bots_svc.patch_bot(bot, {"status": "busy"}, home=home)
        # A chat turn does not wake the VM. A tool that needs it waits
        # (and shows a vm_wake card) only when that tool actually runs.

        action_limit = _resolve_action_limit(row, home=home)
        review_every = _resolve_review_every(row, home=home)
        # Count since last user/webhook/cron — survives desk/vault resume mid-task.
        action_count = chat_svc.count_tools_since_last_user(bot, home=home)
        state: dict[str, Any] = {
            "content": "",
            "msg_id": None,
            "tool_msgs": {},  # toolCallId -> message id
            "tool_args": {},  # toolCallId -> args from start (Pi often omits on end)
            # Screenshot the agent last saw (vm_screenshot / vm_ground) — pinned on
            # each pointer tool so chat overlays use the image of *that* step.
            "last_shot_id": None,
            "tool_base_shot": {},  # toolCallId -> screenshot id at call start
            "pending_images_md": [],  # markdown from files_share_image to embed
            # Successful bot_tell / bot_ask / bot_delegate this run → {tool, to}.
            "mail_sent": [],
            "settled": settled,
            "aborted": False,
            "error": None,
            "action_count": action_count,
            "action_limit": action_limit,
            "review_every": review_every,
            "reviews_steered": set(),  # milestones already steered this process
            # Blocking review gate: no tools after the milestone until GUARD:CONTINUE|STOP.
            "guard_gate": None,  # None | "awaiting"
            "guard_gate_count": None,  # action_count at which the gate opened
            "guard_gate_violation": False,  # tools attempted while gate open
            "guard_tools_blocked": False,  # gate-only follow-up run: block every tool
            # Mid-lot review: milestone crossed → review_due_count; card/gate open
            # only when tools_in_flight returns to 0 (lot finished).
            "tools_in_flight": 0,
            "review_due_count": None,
            "compaction_msg_id": None,
            # True once this LLM call has an open llm_turn card (extension or fallback).
            "llm_turn_ensured": False,
            # CONTINUE arrived after a gate abort — settle must resume the task.
            "guard_resume_task": False,
            "pending_secret_reformulate": False,
            "meta_base": {
                "pi_session_id": session_id,
                "model": model,
            },
        }
        gate_mode = _take_guard_gate_run_mode(bot)
        if gate_mode:
            state["guard_gate"] = "awaiting"
            state["guard_gate_count"] = int(gate_mode.get("count") or 0)
            state["guard_tools_blocked"] = True

        def flush_pending_images(*, persist: bool = False) -> None:
            """Ensure shared-image markdown stays in the assistant text.

            The list is kept until the bubble closes. ``message_end`` replaces
            the draft with the model's text, and this puts the image back when
            the model did not paste it.
            """
            pending = list(state.get("pending_images_md") or [])
            if not pending:
                return
            content = state.get("content") or ""
            extras = [md for md in pending if md and md not in content]
            if not extras:
                return
            merged = (content.rstrip() + "\n\n" + "\n\n".join(extras)).strip()
            state["content"] = merged
            msg_id = state.get("msg_id")
            if persist and msg_id:
                try:
                    chat_svc.update_message(
                        bot,
                        msg_id,
                        merged,
                        home=home,
                        meta={
                            **state["meta_base"],
                            "streaming": True,
                        },
                    )
                except Exception:
                    pass

        def ensure_assistant() -> str:
            if state["msg_id"]:
                return state["msg_id"]
            # Reuse bubble opened by files_attach (download card) for the reply text.
            orphan = chat_svc.find_streaming_assistant(bot, home=home)
            if orphan:
                state["msg_id"] = orphan["id"]
                state["content"] = orphan.get("content") or ""
                flush_pending_images(persist=True)
                return orphan["id"]
            assistant = chat_svc.create_assistant_placeholder(bot, home=home)
            state["msg_id"] = assistant["id"]
            state["content"] = ""
            flush_pending_images(persist=True)
            return assistant["id"]

        def close_assistant(*, error: str | None = None) -> None:
            msg_id = state["msg_id"]
            if not msg_id:
                # Still drop pending images into a new bubble if we only shared files.
                if state.get("pending_images_md"):
                    ensure_assistant()
                    msg_id = state["msg_id"]
                else:
                    return
            flush_pending_images(persist=False)
            content = state["content"]
            if error and not content:
                content = f"⚠️ {error}"
            # Whitespace-only turns (common before tool batches) leave timestamp-only
            # bubbles in the thread — drop the placeholder instead of finalising.
            if not error and not (content or "").strip() and not state.get(
                "pending_images_md"
            ):
                try:
                    chat_svc.discard_message(bot, msg_id, home=home)
                except Exception:
                    log.exception("discard empty assistant failed for %s", bot)
                state["msg_id"] = None
                state["content"] = ""
                state["pending_images_md"] = []
                return
            meta = {
                **state["meta_base"],
                "aborted": state["aborted"],
                "error": error or state["error"],
            }
            # Vault secret in the reply → hide the leaky bubble and steer a reformulation.
            if content and _maybe_reformulate_secret_leak(
                bot,
                msg_id,
                content,
                state=state,
                home=home,
                meta=meta,
            ):
                state["pending_images_md"] = []
                return
            chat_svc.finalize_assistant(bot, msg_id, content, home=home, meta=meta)
            state["msg_id"] = None
            state["content"] = ""
            state["pending_images_md"] = []

        def note_compaction(record: dict[str, Any]) -> None:
            notice = compaction_notice(record)
            if notice is None:
                return
            text, meta = notice
            if meta.get("status") == "running":
                close_assistant()
            msg_id = state.get("compaction_msg_id")
            try:
                if meta.get("status") == "running" or not msg_id:
                    msg = chat_svc.create_message(
                        bot, text, role="system", meta=meta, home=home
                    )
                    state["compaction_msg_id"] = (
                        msg["id"] if meta.get("status") == "running" else None
                    )
                else:
                    chat_svc.update_message(bot, msg_id, text, home=home, meta=meta)
                    state["compaction_msg_id"] = None
            except Exception:
                log.exception("compaction notice failed for %s", bot)

        def ensure_llm_turn_open() -> None:
            """Fallback clock when llm_trace has not opened a card yet."""
            if state.get("llm_turn_ensured"):
                return
            try:
                from autonomous.services import llm_turns as llm_turns_svc

                if llm_turns_svc.find_open_turn(bot, home=home):
                    state["llm_turn_ensured"] = True
                    return
                # No request text here — the lone user prompt is not the payload.
                # llm_trace fills request_kind=context when the extension is loaded.
                llm_turns_svc.open_turn(
                    bot,
                    request="",
                    model=model,
                    home=home,
                )
                state["llm_turn_ensured"] = True
            except Exception:
                log.exception("llm_turn open fallback failed for %s", bot)

        def on_event(record: dict[str, Any]) -> None:
            touch_run_progress(bot)
            rtype = record.get("type")
            if rtype in ("compaction_start", "compaction_end"):
                note_compaction(record)
                return
            if rtype == "message_update":
                ev = record.get("assistantMessageEvent") or {}
                etype = ev.get("type")
                if etype == "text_delta":
                    delta = ev.get("delta") or ""
                    if delta:
                        ensure_llm_turn_open()
                        msg_id = ensure_assistant()
                        state["content"] += delta
                        # Open the gate as soon as CONTINUE streams — tools in the
                        # same turn must not race message_end and get aborted.
                        if _wants_guard_continue(state["content"]):
                            _release_guard_gate(
                                bot, state=state, from_continue=True, home=home
                            )
                        # Never stream raw vault secrets to the UI.
                        try:
                            from autonomous.services import vault as vault_svc

                            safe, hit = vault_svc.scrub_secrets(
                                state["content"], home=home, placeholder=""
                            )
                        except Exception:
                            safe, hit = state["content"], False
                        if hit:
                            try:
                                chat_svc.update_message(
                                    bot,
                                    msg_id,
                                    safe,
                                    home=home,
                                    meta={
                                        **state["meta_base"],
                                        "streaming": True,
                                    },
                                )
                            except Exception:
                                pass
                        else:
                            BUS.publish(
                                "message.delta",
                                {"bot": bot, "id": msg_id, "delta": delta},
                                bot=bot,
                            )
                elif etype == "toolcall_start":
                    # Close open text bubble so the tool card sits between turns.
                    # Do not open a new llm_turn here: message_end often already
                    # finalised the reflection; opening again duplicated the row.
                    close_assistant()
            elif rtype == "tool_execution_start":
                close_assistant()
                # Seal only if a turn is still running (message_end not yet).
                # Never ensure/open here — that created a second « Réflexion »
                # with only « [tool name] » right before the tool card.
                try:
                    from autonomous.services import llm_turns as llm_turns_svc

                    llm_turns_svc.seal_turn_for_tools(
                        bot,
                        tool_name=str(record.get("toolName") or ""),
                        home=home,
                    )
                except Exception:
                    log.exception("llm_turn tool seal failed for %s", bot)
                # CONTINUE may already be in the closed bubble content.
                if _wants_guard_continue(state.get("content") or ""):
                    _release_guard_gate(
                        bot, state=state, from_continue=True, home=home
                    )
                # Same-turn tools after CONTINUE — no separate resume run needed.
                if state.get("guard_resume_task") and state.get("guard_gate") is None:
                    state["guard_resume_task"] = False
                state["action_count"] = int(state.get("action_count") or 0) + 1
                limit = int(state.get("action_limit") or 1000)
                review_every = int(state.get("review_every") or 0)
                count = state["action_count"]
                if count > limit:
                    state["aborted"] = True
                    state["error"] = (
                        f"Limite d’actions atteinte ({limit} depuis le dernier "
                        "message utilisateur / webhook / cron). "
                        "Arrêt automatique de l’agent."
                    )
                    chat_svc.create_message(
                        bot,
                        f"⚠️ {state['error']}",
                        role="system",
                        meta={
                            "kind": "guard",
                            "max_actions": limit,
                            "action_count": count,
                        },
                        home=home,
                    )
                    try:
                        MANAGER.abort(bot)
                    except Exception:
                        pass
                    state["settled"].set()
                    return
                # Blocking review: no tools after the milestone until GUARD:CONTINUE|STOP.
                if (
                    state.get("guard_gate") == "awaiting"
                    and int(state.get("guard_gate_count") or 0) > 0
                    and count > int(state["guard_gate_count"])
                ):
                    _block_tools_for_guard_gate(bot, state=state, home=home)
                    return
                if state.get("guard_tools_blocked"):
                    _block_tools_for_guard_gate(bot, state=state, home=home)
                    return
                # New tool wave after a pack that crossed review_every: open the
                # deferred review now (lot already finished) and block this tool
                # until GUARD:CONTINUE — never open mid-lot when in_flight dips
                # to 0 while parallel siblings are still starting.
                if (
                    state.get("review_due_count") is not None
                    and int(state.get("tools_in_flight") or 0) == 0
                    and state.get("guard_gate") != "awaiting"
                ):
                    _open_deferred_review(bot, state=state, home=home)
                    _block_tools_for_guard_gate(bot, state=state, home=home)
                    return
                call_id = str(record.get("toolCallId") or "")
                tool_name = str(record.get("toolName") or "tool")
                args = record.get("args") if isinstance(record.get("args"), dict) else {}
                # Reject same-turn CONTINUE packs that jump over missing echoes
                # (gap steer arrives too late if those tools are already queued).
                if tool_name == "vm_terminal_exec":
                    skip = _echo_cmd_skips_required(
                        bot,
                        str((args or {}).get("command") or ""),
                        home=home,
                        state=state,
                    )
                    if skip:
                        try:
                            state["action_count"] = max(
                                0, int(state.get("action_count") or 1) - 1
                            )
                        except Exception:
                            pass
                        state["aborted"] = True
                        # Resume with the gap list — do not ask for another CONTINUE.
                        state["guard_resume_task"] = True
                        mark_silent_abort(bot)
                        try:
                            MANAGER.abort(bot)
                        except Exception:
                            pass
                        try:
                            gap = _echo_gap_instruction(bot, home=home)
                            MANAGER.steer(
                                bot,
                                "ECHO ORDER — aborted this pack: "
                                f"{skip}.\n{gap}",
                            )
                        except Exception:
                            log.exception("echo-skip steer failed for %s", bot)
                        state["settled"].set()
                        return
                # Periodic self-check: if the milestone falls mid-pack, mark it
                # due and let the current parallel/sequential lot finish — the
                # review card + gate open when in-flight tools hit zero.
                state["tools_in_flight"] = int(state.get("tools_in_flight") or 0) + 1
                if (
                    review_every > 0
                    and count % review_every == 0
                    and count < limit
                ):
                    steered = state.setdefault("reviews_steered", set())
                    # After a mid-batch gate abort, start_run rebuilds state with an
                    # empty reviews_steered — without this chat check the same
                    # milestone (e.g. 70) re-opens forever and the task stalls.
                    already = count in steered or _review_milestone_already_posted(
                        bot, count=count, home=home
                    )
                    if already:
                        steered.add(count)
                    else:
                        steered.add(count)
                        state["review_due_count"] = count
                from autonomous.services import desk as desk_svc

                desk_svc.prepare_vm_tool(bot, tool_name, home=home)
                if call_id and args:
                    state["tool_args"][call_id] = args
                if tool_name in _HIDDEN_TOOL_CARDS:
                    # Still counts toward action limit; no tool card in the thread.
                    if call_id:
                        state["tool_msgs"][call_id] = ""
                else:
                    content = _format_tool_card(tool_name, args=args, status="running")
                    meta = {
                        "kind": "tool",
                        "status": "running",
                        "tool_name": tool_name,
                        "tool_call_id": call_id,
                        "args": args,
                        "action_index": count,
                        "action_limit": limit,
                        "review_every": review_every,
                    }
                    meta.update(_pointer_fields(tool_name, args, "", None))
                    if tool_name in _POINTER_TOOLS and state.get("last_shot_id"):
                        meta["base_screenshot_id"] = state["last_shot_id"]
                        if call_id:
                            state["tool_base_shot"][call_id] = state["last_shot_id"]
                    msg = chat_svc.create_message(
                        bot,
                        content,
                        role="event",
                        meta=meta,
                        home=home,
                    )
                    if call_id:
                        state["tool_msgs"][call_id] = msg["id"]
            elif rtype == "tool_execution_end":
                call_id = str(record.get("toolCallId") or "")
                tool_name = str(record.get("toolName") or "tool")
                end_args = (
                    record.get("args") if isinstance(record.get("args"), dict) else {}
                )
                try:
                    state["tools_in_flight"] = max(
                        0, int(state.get("tools_in_flight") or 1) - 1
                    )
                except Exception:
                    state["tools_in_flight"] = 0
                # Pi often sends empty args on end — keep those from start.
                args = end_args or dict(state["tool_args"].get(call_id) or {})
                is_error = bool(record.get("isError"))
                if not is_error:
                    pending = state.setdefault("pending_images_md", [])
                    found: list[str] = []
                    # Desk captures (vm_screenshot): the model pastes share
                    # markdown into its reply — do not host-auto-embed them.
                    # Only files_share_image / MCP images are auto-embedded.
                    if tool_name == "files_share_image":
                        md = _extract_share_image_markdown(record.get("result"))
                        if md:
                            found.append(md)
                    found.extend(_mcp_image_markdowns(record.get("result")))
                    for md in found:
                        if md not in pending:
                            pending.append(md)
                    if found:
                        # Open/reuse assistant bubble so the image can appear even
                        # before the model writes surrounding text.
                        ensure_assistant()
                        flush_pending_images(persist=True)
                if (
                    tool_name in ("bot_tell", "bot_ask", "bot_delegate")
                    and not is_error
                ):
                    to = str(args.get("to") or "").strip().lstrip("@")
                    if to:
                        state.setdefault("mail_sent", []).append(
                            {"tool": tool_name, "to": to}
                        )
                # Nudge: many tiny independent shell calls → batch them.
                # First steer early; re-steer if the model keeps going turn-by-turn.
                if tool_name == "vm_terminal_exec" and not is_error:
                    cmd = str((args or {}).get("command") or "").strip()
                    _remember_done_shell(bot, cmd)
                    simple = bool(
                        cmd
                        and "\n" not in cmd
                        and ";" not in cmd
                        and "&&" not in cmd
                        and "|" not in cmd
                        and len(cmd) < 80
                    )
                    streak = int(state.get("simple_shell_streak") or 0)
                    state["simple_shell_streak"] = streak + 1 if simple else 0
                    should_steer = False
                    if simple and not state.get("throughput_steered"):
                        if state["simple_shell_streak"] >= 3:
                            state["throughput_steered"] = True
                            state["post_steer_simple"] = 0
                            should_steer = True
                    elif simple and state.get("throughput_steered"):
                        post = int(state.get("post_steer_simple") or 0) + 1
                        state["post_steer_simple"] = post
                        # Model ignored the nudge — remind every 5 more singles.
                        if post % 5 == 0:
                            should_steer = True
                    elif not simple:
                        state["post_steer_simple"] = 0
                    if should_steer:
                        try:
                            MANAGER.steer(bot, _THROUGHPUT_BATCH_STEER)
                        except Exception:
                            log.exception(
                                "throughput batch steer failed for %s", bot
                            )
                if tool_name not in _HIDDEN_TOOL_CARDS:
                    result_text = _tool_result_text(record.get("result"))
                    details = _tool_result_details(record.get("result"))
                    status = "error" if is_error else "done"
                    content = _format_tool_card(
                        tool_name, args=args, status=status, result=result_text
                    )
                    timed_out = _tool_timed_out(
                        result_text, details=details, is_error=is_error
                    )
                    meta = {
                        "kind": "tool",
                        "status": status,
                        "tool_name": tool_name,
                        "tool_call_id": call_id,
                        "args": args,
                        "is_error": is_error,
                        "duration_ms": record.get("durationMs"),
                        "timed_out": timed_out,
                    }
                    meta.update(
                        _pointer_fields(tool_name, args, result_text, details)
                    )
                    shot_meta = _screenshot_fields(tool_name, result_text, details)
                    meta.update(shot_meta)
                    base_shot = state["tool_base_shot"].pop(call_id, None) if call_id else None
                    if tool_name in _POINTER_TOOLS and base_shot:
                        meta["base_screenshot_id"] = base_shot
                    if shot_meta.get("screenshot_id") and not is_error:
                        state["last_shot_id"] = shot_meta["screenshot_id"]
                    msg_id = state["tool_msgs"].get(call_id)
                    if not msg_id and call_id:
                        # Recover card if on_event was briefly stolen by a double start.
                        msg_id = _find_running_tool_msg(
                            bot, call_id, home=home
                        ) or ""
                        if msg_id:
                            state["tool_msgs"][call_id] = msg_id
                    if msg_id:
                        chat_svc.update_message(
                            bot, msg_id, content, home=home, meta=meta
                        )
                    else:
                        chat_svc.create_message(
                            bot, content, role="event", meta=meta, home=home
                        )
            elif rtype == "agent_settled":
                state["aborted"] = bool(record.get("aborted"))
                # Pack ended the turn with a review still due (no next tool wave).
                if state.get("review_due_count") and state.get("guard_gate") != "awaiting":
                    incomplete = _echo_sequence_incomplete_reason(bot, home=home)
                    if incomplete:
                        _open_deferred_review(bot, state=state, home=home)
                    else:
                        state.pop("review_due_count", None)
                state["settled"].set()
            elif rtype == "message_end":
                message_obj = record.get("message") or {}
                if message_obj.get("role") == "assistant":
                    text = _message_text(message_obj)
                    # If the bubble was already closed on toolcall_start, do NOT
                    # open a second one with the same final text (duplicate chat).
                    if text and state["msg_id"]:
                        state["content"] = text
                        flush_pending_images(persist=True)
                    if state.get("guard_gate") == "awaiting" and text:
                        if _wants_guard_continue(text):
                            _release_guard_gate(
                                bot,
                                state=state,
                                from_continue=True,
                                home=home,
                            )
                        elif _wants_guard_stop(text):
                            incomplete = _echo_sequence_incomplete_reason(
                                bot, home=home
                            )
                            if incomplete:
                                # Premature STOP — rewrite bubble to CONTINUE so
                                # the UI never shows « l’agent s’arrête » while
                                # the run keeps going, then force the gap fill.
                                _rewrite_refused_guard_stop(
                                    bot,
                                    state=state,
                                    home=home,
                                    reason=incomplete,
                                )
                                _release_guard_gate(
                                    bot,
                                    state=state,
                                    from_continue=True,
                                    home=home,
                                )
                            else:
                                _release_guard_gate(
                                    bot, state=state, home=home
                                )
                        elif (text or "").strip() and not _wants_guard_token(text):
                            # Spoke without the mandatory token — re-steer, keep gate.
                            try:
                                MANAGER.steer(bot, _GUARD_GATE_RETRY_STEER)
                            except Exception:
                                log.exception(
                                    "guard gate retry steer failed for %s", bot
                                )
                    if text and _wants_guard_stop(text):
                        incomplete = _echo_sequence_incomplete_reason(
                            bot, home=home
                        )
                        if incomplete:
                            # STOP without an open gate (or after rewrite above):
                            # never post the stop system card / abort.
                            if not state.get("guard_stop_rewritten"):
                                _rewrite_refused_guard_stop(
                                    bot,
                                    state=state,
                                    home=home,
                                    reason=incomplete,
                                )
                        else:
                            state["aborted"] = True
                            state["error"] = (
                                "L’agent a choisi de s’arrêter (GUARD:STOP) "
                                "après la revue de progression."
                            )
                            try:
                                chat_svc.create_message(
                                    bot,
                                    f"⏹ {state['error']}",
                                    role="system",
                                    meta={
                                        "kind": "guard",
                                        "guard_stop": True,
                                        "action_count": state.get("action_count"),
                                    },
                                    home=home,
                                )
                            except Exception:
                                pass
                            try:
                                MANAGER.abort(bot)
                            except Exception:
                                pass
                            state["settled"].set()
                    err = message_obj.get("errorMessage")
                    if err and message_obj.get("stopReason") == "error":
                        state["error"] = str(err)
                        from autonomous.services import chat_attachments as attach_svc

                        limit = attach_svc.parse_provider_image_limit(str(err))
                        if limit is not None:
                            try:
                                attach_svc.note_provider_image_limit(
                                    bot, model, limit, home=home
                                )
                            except Exception:
                                log.exception(
                                    "remember vision limit failed for %s", bot
                                )
                    usage = message_obj.get("usage")
                    tokens_in = 0
                    tokens_out = 0
                    if isinstance(usage, dict):
                        tokens_in = int(usage.get("input") or 0)
                        tokens_out = int(usage.get("output") or 0)
                        try:
                            bots_svc.add_token_usage(
                                bot,
                                tokens_in,
                                tokens_out,
                                home=home,
                            )
                        except Exception:
                            log.exception("token usage update failed for %s", bot)
                    # Seal the llm_turn card opened by llm_trace (or create one).
                    try:
                        from autonomous.services import llm_turns as llm_turns_svc

                        llm_turns_svc.finalize_turn(
                            bot,
                            response=llm_turns_svc.summarize_assistant_message(
                                message_obj
                            ),
                            response_json=message_obj,
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                            stop_reason=str(message_obj.get("stopReason") or "")
                            or None,
                            error=str(err) if err else None,
                            model=str(
                                message_obj.get("responseModel")
                                or message_obj.get("model")
                                or model
                                or ""
                            )
                            or None,
                            home=home,
                        )
                        # Next provider call may open a fresh card.
                        state["llm_turn_ensured"] = False
                    except Exception:
                        log.exception("llm_turn finalize failed for %s", bot)
            elif rtype == "auto_retry_end":
                if record.get("success") is False and not state["settled"].is_set():
                    state["error"] = state["error"] or "Pi provider failed after retries"
                    state["settled"].set()

        def worker() -> None:
            try:
                session = MANAGER.ensure(
                    bot,
                    session_id=session_id,
                    model=model,
                    home=home,
                    on_event=on_event,
                )
                from autonomous.services import chat_attachments as attach_svc

                prompt_text = message
                try:
                    from autonomous.services import notebook as notebook_svc

                    prompt_text = notebook_svc.attach_prompt(
                        prompt_text, bot, home=home
                    )
                except Exception:
                    log.exception("notebook trailer failed for %s", bot)
                prompt_images = list(images or [])
                # Adapt to provider vision limits (Pi models.json, then guard fallback).
                cap = attach_svc.max_images_per_prompt(
                    home=home, bot=bot, model_ref=model
                )
                if len(prompt_images) > cap:
                    prompt_images = prompt_images[:cap]
                resp = session.prompt(
                    prompt_text, images=prompt_images or None
                )
                if not resp.get("success"):
                    err = str(resp.get("error") or "Pi rejected the prompt")
                    limit = attach_svc.parse_provider_image_limit(err)
                    if limit is not None:
                        log.warning(
                            "Vision limit %s for bot=%s — retrying with %s image(s)",
                            limit,
                            bot,
                            limit,
                        )
                        attach_svc.note_provider_image_limit(
                            bot, model, limit, home=home
                        )
                        prompt_images = prompt_images[:limit]
                        note = (
                            f"\n\n(Provider limit: at most {limit} image(s) "
                            f"per prompt — older screenshots were left out of this "
                            f"request; they stay in the chat.)"
                        )
                        resp = session.prompt(
                            prompt_text + note, images=prompt_images or None
                        )
                    if not resp.get("success"):
                        state["error"] = str(
                            resp.get("error") or err or "Pi rejected the prompt"
                        )
                        state["settled"].set()
                        return
                # Wait until Pi settles. While a vault/desk card is pending,
                # flip busy → waiting so the UI shows a user-wait (not Working).
                while not state["settled"].wait(timeout=2.0):
                    try:
                        st = (bots_svc.get_bot(bot, home=home) or {}).get("status")
                        if st == "waiting":
                            continue
                        from autonomous.db import get_db
                        from autonomous.paths import default_home as _dh

                        with get_db(home or _dh()) as conn:
                            pending_row = conn.execute(
                                "SELECT 1 FROM vault_requests "
                                "WHERE bot=? AND state='pending' LIMIT 1",
                                (bot,),
                            ).fetchone()
                        if pending_row and st == "busy":
                            bots_svc.patch_bot(
                                bot, {"status": "waiting"}, home=home
                            )
                    except Exception:
                        pass
            except PiRpcError as exc:
                # Do not kill a Pi process that is still up. A slow preflight
                # or a multi-hour turn is not a reason to stop the agent; the
                # user does that from the UI. If the process already exited,
                # record the error so the run can settle.
                session = MANAGER.get(bot)
                if session is not None and session.alive:
                    log.warning(
                        "Pi RPC error while session still alive for %s: %s",
                        bot,
                        exc,
                    )
                    while not state["settled"].wait(timeout=2.0):
                        session = MANAGER.get(bot)
                        if session is None or not session.alive:
                            state["error"] = str(exc)
                            state["settled"].set()
                            break
                else:
                    state["error"] = str(exc)
                    state["settled"].set()
            except Exception as exc:
                log.exception("Pi run failed for %s", bot)
                state["error"] = str(exc)
                state["settled"].set()
            finally:
                # Delete / reclaim already dropped this slot. Do not write into
                # the slug or drain a queue that now belongs to a new bot.
                if not _owns_run(bot, settled):
                    return
                # Snapshot before close_assistant() clears state["content"].
                final_assistant = str(state.get("content") or "")
                soft_busy = _is_already_processing_error(state.get("error"))
                if soft_busy:
                    # Don't spam chat with Pi's "already processing" when a resume
                    # raced a live turn — the original run still owns the session.
                    log.warning("soft-skip already-processing for bot=%s", bot)
                    state["error"] = None
                silent_abort = consume_silent_abort(bot)
                if silent_abort:
                    # Intentional abort (secret scrub): no « ⚠️ aborted » bubble.
                    state["error"] = None
                    state["aborted"] = True
                if state["error"] and not state["msg_id"] and not state["content"]:
                    chat_svc.create_message(
                        bot,
                        f"⚠️ {state['error']}",
                        role="assistant",
                        meta={**state["meta_base"], "error": state["error"]},
                        home=home,
                    )
                else:
                    close_assistant(error=state["error"])
                # Review gate still open at settle → dedicated follow-up that only
                # accepts GUARD:CONTINUE / GUARD:STOP (no tools until then).
                stopped_by_guard = bool(
                    state.get("aborted")
                    and state.get("error")
                    and "GUARD:STOP" in str(state.get("error") or "")
                )
                need_guard_gate = (
                    state.get("guard_gate") == "awaiting"
                    or state.get("guard_gate_violation")
                ) and not stopped_by_guard
                need_guard_resume = bool(state.get("guard_resume_task")) and not (
                    stopped_by_guard or soft_busy
                )
                if need_guard_gate and not soft_busy and not need_guard_resume:
                    _queue_pending_guard_gate(
                        bot,
                        count=int(
                            state.get("guard_gate_count")
                            or state.get("action_count")
                            or 0
                        ),
                        limit=int(state.get("action_limit") or 1000),
                        review_every=int(state.get("review_every") or 0),
                    )
                if silent_abort:
                    # Drop empty / abort placeholders left mid-stream.
                    try:
                        for msg in chat_svc.list_messages(bot, limit=12, home=home):
                            if msg.get("role") != "assistant":
                                continue
                            meta = dict(msg.get("meta") or {})
                            body = (msg.get("content") or "").strip()
                            if meta.get("hidden_prompt"):
                                continue
                            if not body or _is_abort_placeholder(body):
                                chat_svc.update_message(
                                    bot,
                                    msg["id"],
                                    "",
                                    home=home,
                                    meta={
                                        **meta,
                                        "hidden_prompt": True,
                                        "silent_abort_hidden": True,
                                        "streaming": False,
                                    },
                                )
                    except Exception:
                        log.exception("silent abort cleanup failed for %s", bot)
                try:
                    chat_svc.finalize_streaming_assistants(bot, home=home)
                except Exception:
                    pass
                try:
                    from autonomous.services import llm_turns as llm_turns_svc

                    llm_turns_svc.close_running_turns(bot, home=home)
                except Exception:
                    log.exception("close_running llm_turns failed for %s", bot)
                need_secret_fix = bool(
                    state.get("pending_secret_reformulate")
                    or _pending_secret_reformulate.get(bot)
                )
                owns = _release_run(bot, settled)
                if owns and not soft_busy:
                    # Pi can settle/abort without tool_execution_end (hang, kill,
                    # reload) — never leave tool cards stuck on "En cours".
                    try:
                        chat_svc.close_running_tools(
                            bot,
                            error=(
                                "Outil interrompu (run terminé sans résultat)."
                            ),
                            home=home,
                        )
                    except Exception:
                        log.exception(
                            "close_running_tools failed for %s", bot
                        )
                    bots_svc.patch_bot(bot, {"status": "idle"}, home=home)
                    try:
                        from autonomous.services import botmail as botmail_svc

                        botmail_svc.on_run_finished(
                            bot,
                            assistant_content=final_assistant,
                            mail_sent=list(state.get("mail_sent") or []),
                            home=home,
                        )
                    except Exception:
                        log.exception("botmail on_run_finished failed for %s", bot)
                    if need_secret_fix:
                        # Prefer reformulation over draining a queued user message.
                        threading.Thread(
                            target=_kick_secret_reformulate_run,
                            args=(bot, home),
                            name=f"secret-reform-{bot}",
                            daemon=True,
                        ).start()
                    elif need_guard_resume:
                        threading.Thread(
                            target=_kick_guard_resume_run,
                            args=(bot, home),
                            name=f"guard-resume-{bot}",
                            daemon=True,
                        ).start()
                    elif need_guard_gate:
                        threading.Thread(
                            target=_kick_guard_gate_run,
                            args=(bot, home),
                            name=f"guard-gate-{bot}",
                            daemon=True,
                        ).start()
                    else:
                        drained = False
                        try:
                            drained = bool(
                                chat_svc.drain_queued_user_messages(
                                    bot, home=home
                                )
                            )
                        except Exception:
                            log.exception(
                                "drain queued user messages failed for %s", bot
                            )
                        # RPC timeout / provider ⚠️ left idle with no queue —
                        # retry soon (scheduler is a backstop only).
                        if not drained and state.get("error"):
                            threading.Thread(
                                target=_kick_retryable_failure_run,
                                args=(bot, home),
                                name=f"retry-fail-{bot}",
                                daemon=True,
                            ).start()
                elif owns and soft_busy:
                    # Slot released but another Pi turn may still be mid-flight.
                    try:
                        bots_svc.patch_bot(bot, {"status": "busy"}, home=home)
                    except Exception:
                        pass

        threading.Thread(target=worker, name=f"pi-run-{bot}", daemon=True).start()
        return ""

    def stop_run(self, bot: str, *, home: Path | None = None) -> None:
        MANAGER.abort(bot)
        MANAGER.stop(bot)
        # Free the in-memory run slot immediately so the next send is not skipped.
        clear_active_run(bot)
        try:
            chat_svc.close_running_tools(
                bot,
                error="Outil interrompu (stop).",
                home=home,
            )
        except Exception:
            log.exception("close_running_tools failed after stop for %s", bot)
        try:
            from autonomous.services import llm_turns as llm_turns_svc

            llm_turns_svc.close_running_turns(
                bot, home=home, error="Tour LLM interrompu (stop)."
            )
        except Exception:
            log.exception("close_running llm_turns failed after stop for %s", bot)
        # Idle before cancelling cards so clarify finalize does not post a Resume card.
        try:
            bots_svc.patch_bot(bot, {"status": "idle"}, home=home)
        except Exception:
            pass
        try:
            from autonomous.services import clarifies as clarify_svc

            clarify_svc.cancel_pending_for_bot(
                bot, home=home, reason="Agent stopped."
            )
        except Exception:
            log.exception("cancel pending clarifies failed after stop for %s", bot)
        # Pi events already in flight when we stopped (e.g. a tool_execution_start
        # read just after the sweep above) would leave a card stuck on "En cours"
        # forever: sweep again once the reader thread has drained.
        _sweep_tools_later(bot, home=home)
        try:
            chat_svc.drain_queued_user_messages(bot, home=home)
        except Exception:
            log.exception("drain queued user messages failed after stop for %s", bot)


def _sweep_tools_later(bot: str, *, home: Path | None = None) -> None:
    """Close tool cards created by late Pi events after a stop (delayed, best effort)."""

    def _sweep() -> None:
        try:
            if bots_svc.get_bot(bot, home=home).get("status") in ("busy", "waiting"):
                return  # a new run owns the thread now — its own cleanup applies
            chat_svc.close_running_tools(
                bot, error="Outil interrompu (stop).", home=home
            )
            # A message queued while the run was busy must not stay stuck if the
            # immediate drain in stop_run() lost the race with the old worker.
            chat_svc.drain_queued_user_messages(bot, home=home)
        except Exception:
            pass

    for delay in (1.5, 6.0):
        t = threading.Timer(delay, _sweep)
        t.daemon = True
        t.start()


def _resolve_action_limit(bot_row: dict[str, Any], *, home: Path | None) -> int:
    """Hard stop: tools since last user/webhook/cron. bot.guard → settings → 1000."""
    guard = bot_row.get("guard") if isinstance(bot_row.get("guard"), dict) else {}
    raw = guard.get("max_actions")
    if raw is None:
        raw = settings_svc.get("guard.max_actions", home=home, default=1000)
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        limit = 1000
    return max(1, min(100_000, limit))


def _resolve_review_every(bot_row: dict[str, Any], *, home: Path | None) -> int:
    """Ask the LLM to self-check every N tools (0 = disabled). Default 100."""
    guard = bot_row.get("guard") if isinstance(bot_row.get("guard"), dict) else {}
    raw = guard.get("review_every")
    if raw is None:
        raw = settings_svc.get("guard.review_every", home=home, default=100)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 100
    return max(0, min(100_000, n))


def _wants_guard_stop(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"\bGUARD\s*:\s*STOP\b", text, flags=re.IGNORECASE))


def _wants_guard_continue(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"\bGUARD\s*:\s*CONTINUE\b", text, flags=re.IGNORECASE))


def _wants_guard_token(text: str) -> bool:
    return _wants_guard_continue(text) or _wants_guard_stop(text)


# bot → {count, limit, review_every} while a blocking review follow-up is due.
_pending_guard_gate: dict[str, dict[str, int]] = {}
# bot → info for the next start_run that must open in gate-only mode (block all tools).
_guard_gate_run_mode: dict[str, dict[str, int]] = {}
_pending_guard_gate_lock = threading.Lock()


def _queue_pending_guard_gate(
    bot: str, *, count: int, limit: int, review_every: int
) -> None:
    with _pending_guard_gate_lock:
        _pending_guard_gate[bot] = {
            "count": int(count),
            "limit": int(limit),
            "review_every": int(review_every),
        }


def _clear_pending_guard_gate(bot: str) -> None:
    with _pending_guard_gate_lock:
        _pending_guard_gate.pop(bot, None)
        _guard_gate_run_mode.pop(bot, None)


def _pop_pending_guard_gate(bot: str) -> dict[str, int] | None:
    with _pending_guard_gate_lock:
        return _pending_guard_gate.pop(bot, None)


def _take_guard_gate_run_mode(bot: str) -> dict[str, int] | None:
    with _pending_guard_gate_lock:
        return _guard_gate_run_mode.pop(bot, None)


def _arm_guard_gate_run_mode(bot: str, info: dict[str, int]) -> None:
    with _pending_guard_gate_lock:
        _guard_gate_run_mode[bot] = dict(info)


def _release_guard_gate(
    bot: str,
    *,
    state: dict[str, Any],
    from_continue: bool = False,
    home: Path | None = None,
) -> None:
    """Allow tools again after GUARD:CONTINUE / STOP (STOP still aborts separately)."""
    # CONTINUE always arms a task resume. If more tools run in this same turn,
    # tool_execution_start clears the flag. If the turn settles with no further
    # tools (common after a mid-batch gate abort), settle kicks the resume run.
    if from_continue:
        state["guard_resume_task"] = True
        # Same-turn CONTINUE never sees the separate resume prompt — steer the
        # gap list once so the model does not skip tools aborted by the gate.
        if not state.get("guard_continue_steered"):
            state["guard_continue_steered"] = True
            try:
                suffix = _guard_resume_prompt_for(bot, home=home)
                extra = suffix.replace(_GUARD_RESUME_PROMPT, "").strip()
                if extra:
                    MANAGER.steer(bot, "CONTINUE accepted.\n" + extra)
                else:
                    MANAGER.steer(
                        bot,
                        "CONTINUE accepted. Queued tools aborted by the gate DID "
                        "NOT RUN. Resume from the first step without a successful "
                        "result; do not skip; large batch_sequential packs sized "
                        "to the next review boundary.",
                    )
            except Exception:
                log.exception("guard continue gap steer failed for %s", bot)
    state["guard_gate"] = None
    state["guard_gate_count"] = None
    state["guard_tools_blocked"] = False
    state["guard_gate_violation"] = False
    _clear_pending_guard_gate(bot)


def _queue_guard_gate_followup(bot: str, *, state: dict[str, Any]) -> None:
    """Arm the CONTINUE/STOP follow-up so a settle race cannot drop it."""
    try:
        _queue_pending_guard_gate(
            bot,
            count=int(
                state.get("guard_gate_count") or state.get("action_count") or 0
            ),
            limit=int(state.get("action_limit") or 1000),
            review_every=int(state.get("review_every") or 0),
        )
    except Exception:
        log.exception("queue pending guard gate failed for %s", bot)


def _open_deferred_review(
    bot: str,
    *,
    state: dict[str, Any],
    home: Path | None,
) -> None:
    """Fire the review after the current tool pack has finished (or settled).

    Crossing ``review_every`` mid-lot only sets ``review_due_count``; the card and
    blocking gate open here so parallel siblings are not cut off, and so no tool
    cards appear between the review card and ``GUARD:CONTINUE``.
    """
    due = state.pop("review_due_count", None)
    if due is None:
        return
    if state.get("guard_gate") == "awaiting":
        return
    count = int(state.get("action_count") or due)
    limit = int(state.get("action_limit") or 1000)
    review_every = int(state.get("review_every") or 0)
    if _review_milestone_already_posted(bot, count=count, home=home):
        return
    _steer_progress_review(
        bot,
        count=count,
        limit=limit,
        review_every=review_every,
        home=home,
    )
    state["guard_gate"] = "awaiting"
    state["guard_gate_count"] = count
    state["guard_gate_violation"] = False
    state["guard_continue_steered"] = False
    state["guard_stop_rewritten"] = False
    _queue_guard_gate_followup(bot, state=state)


def _block_tools_for_guard_gate(
    bot: str,
    *,
    state: dict[str, Any],
    home: Path | None,
) -> None:
    """Abort the run when the model calls tools while the review gate is closed.

    No chat card — the review card already signals the gate; a follow-up run asks
    for GUARD:CONTINUE / STOP quietly.
    """
    # Undo the increment — the tool did not actually run.
    try:
        state["action_count"] = max(0, int(state.get("action_count") or 1) - 1)
    except Exception:
        pass
    state["guard_gate_violation"] = True
    state["aborted"] = True
    _queue_guard_gate_followup(bot, state=state)
    mark_silent_abort(bot)
    try:
        MANAGER.abort(bot)
    except Exception:
        pass
    state["settled"].set()
    del home  # reserved (cards intentionally omitted)


_GUARD_GATE_RETRY_STEER = (
    "GUARD RAIL still open. Do NOT call tools. "
    "Reply with exactly GUARD:CONTINUE (then resume the task) "
    "or GUARD:STOP (and stop). Nothing else before that token."
)

_THROUGHPUT_BATCH_STEER = (
    "THROUGHPUT — you have been issuing many independent short shell tool "
    "calls one model turn at a time. That is too slow.\n"
    "For every remaining command whose arguments you already know, emit them "
    "NOW in one response: each command is still its own vm_terminal_exec "
    "call (never invent a bash/shell tool), and include batch_sequential "
    "once so they run one after another without a model turn between each. "
    "A large pack (tens of calls when safe) is expected — not two or three. "
    "\"One command per tool call\" still means many tool calls in this same "
    "response. Fill up to the next GUARD review (or the end of the task). "
    "Do not narrate between them."
)


_GUARD_GATE_RUN_PROMPT = (
    "GUARD RAIL checkpoint — mandatory. You reached a review milestone and tried "
    "to keep calling tools without answering.\n"
    "You have used about {count} tool calls since the last user / webhook / cron "
    "(hard limit {limit}; reviews every {review_every}).\n"
    "Do NOT call any tools yet.\n"
    "Reply with exactly one of:\n"
    "GUARD:CONTINUE — you are progressing and will resume the task right after\n"
    "GUARD:STOP — you should stop now\n"
    "If you choose CONTINUE, put the token first, then immediately emit the next "
    "required tool calls in that same turn (large sequential batches with "
    "batch_sequential are fine when arguments are already known). Queued tools "
    "aborted by this gate DID NOT RUN — resume from the first missing successful "
    "result; do not skip ahead; do not STOP until the user task is truly done."
)


_MID_RUN_STEER_PREFIX = (
    "MID-TASK MESSAGE — someone wrote while you were working.\n"
    "Answer them briefly in the chat now, then continue your current task unless "
    "they clearly ask you to stop or change direction.\n\n"
    "Their message:\n"
)


def steer_mid_run(
    bot: str,
    prompt: str,
    *,
    home: Path | None = None,
) -> bool:
    """Inject a human/peer message into the live Pi turn. Returns True if steered."""
    del home  # reserved for future session routing
    text = str(prompt or "").strip()
    if not text:
        return False
    if not run_in_progress(bot):
        return False
    try:
        result = MANAGER.steer(bot, f"{_MID_RUN_STEER_PREFIX}{text}")
    except Exception:
        log.exception("mid-run steer failed for %s", bot)
        return False
    return result is not None


_SECRET_REFORMULATE_STEER = (
    "SECRET BLOCKED: a vault secret appeared in your previous reply and was "
    "removed. The user saw a short notice. Continue answering their last request "
    "normally, in their language, WITHOUT quoting, spelling, or hinting at any "
    "password/token/secret. Do not lecture, do not apologize at length, do not "
    "talk about the block. Just finish the useful answer they asked for, omitting "
    "the secret."
)

_SECRET_REFORMULATE_MAX = 2
# Per-bot counters / follow-up flags (survive across close_assistant → settle → new run).
_secret_reformulate_counts: dict[str, int] = {}
_pending_secret_reformulate: dict[str, bool] = {}


def _maybe_reformulate_secret_leak(
    bot: str,
    msg_id: str,
    content: str,
    *,
    state: dict[str, Any],
    home: Path | None,
    meta: dict[str, Any],
) -> bool:
    """If content has a vault secret: notice + hide leak + queue reformulation run."""
    try:
        from autonomous.services import vault as vault_svc

        if not vault_svc.text_contains_vault_secret(content, home=home):
            # Clean reply — reset leak counter for this bot.
            _secret_reformulate_counts.pop(bot, None)
            return False
    except Exception:
        log.exception("secret leak check failed for %s", bot)
        return False

    count = int(_secret_reformulate_counts.get(bot, 0))
    if count >= _SECRET_REFORMULATE_MAX:
        safe, _ = vault_svc.scrub_secrets(content, home=home, placeholder="")
        fallback = (
            safe.strip()
            or (
                "Je ne peux pas afficher de secret. "
                "Dis seulement si l’auth a échoué ou réussi, sans citer le secret, "
                "et propose de mettre à jour le coffre si besoin."
            )
        )
        chat_svc.finalize_assistant(bot, msg_id, fallback, home=home, meta=meta)
        _secret_reformulate_counts.pop(bot, None)
        _pending_secret_reformulate.pop(bot, None)
        state["msg_id"] = None
        state["content"] = ""
        return True

    _secret_reformulate_counts[bot] = count + 1
    # Hide the leaky assistant text from the thread.
    chat_svc.finalize_assistant(
        bot,
        msg_id,
        "",
        home=home,
        meta={
            **meta,
            "hidden_prompt": True,
            "secret_leak": True,
            "streaming": False,
        },
    )
    # Visible notice in the conversation (short — then a clean reply follows).
    try:
        chat_svc.create_message(
            bot,
            "Attention : un secret a été transmis à votre fournisseur LLM. "
            "Changez-le si besoin. Sur Autonomous, la réponse a été bloquée "
            "et n’est pas conservée telle quelle dans l’historique.",
            role="system",
            meta={"kind": "secret_provider_alert"},
            home=home,
        )
    except Exception:
        log.exception("secret leak notice failed for %s", bot)

    state["msg_id"] = None
    state["content"] = ""
    # Kick a dedicated reformulation run after this Pi turn settles.
    _pending_secret_reformulate[bot] = True
    state["pending_secret_reformulate"] = True
    return True


def _kick_secret_reformulate_run(bot: str, home: Path | None) -> None:
    """Start a follow-up Pi run that only asks for a clean reformulation."""
    import time

    time.sleep(0.35)
    try:
        if not _pending_secret_reformulate.pop(bot, None):
            return
        # Still busy / waiting → try again shortly once.
        row = bots_svc.get_bot(bot, home=home)
        if (row.get("status") or "") in ("busy", "waiting"):
            _pending_secret_reformulate[bot] = True
            time.sleep(1.0)
            if (bots_svc.get_bot(bot, home=home).get("status") or "") in (
                "busy",
                "waiting",
            ):
                log.warning(
                    "secret reformulate deferred — bot %s still busy", bot
                )
                return
            if not _pending_secret_reformulate.pop(bot, None):
                return
        get_agent(
            str(settings_svc.get("agent_backend", home=home, default="pi") or "pi"),
            home=home,
        ).start_run(bot, _SECRET_REFORMULATE_STEER, home=home)
    except Exception:
        log.exception("secret reformulate run failed for %s", bot)


def _steer_progress_review(
    bot: str,
    *,
    count: int,
    limit: int,
    review_every: int,
    home: Path | None,
) -> None:
    """Steer Pi: blocking review — no more tools until GUARD:CONTINUE|STOP."""
    remaining = max(0, limit - count)
    steer_msg = (
        f"GUARD RAIL checkpoint (BLOCKING): you have used {count} tool calls since "
        f"the last user message / webhook / cron (hard limit {limit}, "
        f"~{remaining} left). Reviews fire every {review_every} tools.\n"
        "Do NOT call any more tools until you answer.\n"
        "Any further tools still queued in this turn will be aborted and will "
        "NOT run — after CONTINUE, resume from the first step without a "
        "successful result (do not skip).\n"
        "Reply with exactly one of:\n"
        "GUARD:CONTINUE — still progressing; then take the next useful step\n"
        "GUARD:STOP — stop now, no more tools\n"
        "Nothing else before that token. After CONTINUE, resume tools in the "
        "same turn when you can (sequential batches OK if args are known; size "
        "packs to the next review boundary)."
    )
    try:
        chat_svc.create_message(
            bot,
            (
                f"🧭 Garde-fou : revue à {count} actions "
                f"(limite {limit}, depuis le dernier message user / webhook / cron)."
            ),
            role="system",
            meta={
                "kind": "guard",
                "review": True,
                "action_count": count,
                "max_actions": limit,
                "review_every": review_every,
            },
            home=home,
        )
    except Exception:
        log.exception("guard review chat card failed for %s", bot)
    try:
        MANAGER.steer(bot, steer_msg)
    except Exception:
        log.exception("guard review steer failed for %s", bot)


_GUARD_RESUME_PROMPT = (
    "GUARD:CONTINUE was accepted. The review gate aborted every tool that was "
    "still queued in that turn after the milestone — those calls DID NOT RUN "
    "(no successful result). Look only at tool results you actually received. "
    "Resume from the first step that has no successful result; do not skip "
    "ahead; do not invent completed work; do not GUARD:STOP until the user's "
    "requested sequence is fully done with real tool results. Prefer a large "
    "batch_sequential for remaining independent commands whose arguments you "
    "already know, sized to finish just before the next review milestone (or "
    "the end of the task)."
)

# bot → last successful shell command string (survives mid-batch gate abort).
_last_done_shell: dict[str, str] = {}


def _remember_done_shell(bot: str, command: str) -> None:
    cmd = str(command or "").strip()
    if cmd:
        _last_done_shell[bot] = cmd


def _echo_progress_from_chat(bot: str, *, home: Path | None) -> tuple[set[int], int]:
    """Successful ``echo N`` tool calls in chat → (set of N, max N)."""
    import re

    nums: set[int] = set()
    before: str | None = None
    for _ in range(40):
        batch = chat_svc.list_messages(bot, before=before, limit=200, home=home)
        if not batch:
            break
        for m in batch:
            meta = m.get("meta") or {}
            if meta.get("kind") != "tool":
                continue
            if (meta.get("tool_name") or "") != "vm_terminal_exec":
                continue
            if (meta.get("status") or "") not in ("done", "success", ""):
                # still count done; skip explicit errors
                if meta.get("status") == "error":
                    continue
            args = meta.get("args") if isinstance(meta.get("args"), dict) else {}
            cmd = str((args or {}).get("command") or "").strip()
            m_echo = re.fullmatch(r"echo\s+(\d+)", cmd)
            if m_echo:
                nums.add(int(m_echo.group(1)))
        oldest = min((m.get("created_at") or "") for m in batch)
        if not oldest or len(batch) < 200 or oldest == before:
            break
        before = oldest
    return nums, (max(nums) if nums else 0)


def _echo_task_target(bot: str, *, home: Path | None) -> int | None:
    """250 if the latest user turn asked for the echo-250 sequence."""
    try:
        recent = chat_svc.list_messages(bot, limit=30, home=home)
        user_blob = " ".join(
            (m.get("content") or "")
            for m in recent
            if m.get("role") == "user"
        ).lower()
        if "echo" in user_blob and "250" in user_blob:
            return 250
    except Exception:
        log.exception("echo task target scan failed for %s", bot)
    return None


def _echo_missing_list(bot: str, *, home: Path | None) -> list[int]:
    """Missing echo N values for an echo-250-style task (empty if not that task)."""
    target = _echo_task_target(bot, home=home)
    if not target:
        return []
    try:
        nums, _mx = _echo_progress_from_chat(bot, home=home)
    except Exception:
        log.exception("echo missing scan failed for %s", bot)
        return []
    return [i for i in range(1, target + 1) if i not in nums]


def _echo_gap_instruction(bot: str, *, home: Path | None, limit: int = 60) -> str:
    """Text block listing the next required echo commands (for gate/resume prompts)."""
    missing = _echo_missing_list(bot, home=home)
    if not missing:
        return ""
    chunk = missing[: max(1, limit)]
    lines = "\n".join(f"  vm_terminal_exec command=\"echo {n}\"" for n in chunk)
    more = (
        f"\n… then continue through echo {missing[-1]} "
        f"({len(missing) - len(chunk)} more after this pack)."
        if len(missing) > len(chunk)
        else ""
    )
    return (
        "ECHO SEQUENCE — required next tools (exact order, do not skip):\n"
        f"{lines}{more}\n"
        "Emit them NOW with batch_sequential (one vm_terminal_exec per echo). "
        f"The next command MUST be exactly: echo {chunk[0]}. "
        "Do not jump ahead to a higher N."
    )


def _echo_cmd_skips_required(
    bot: str,
    command: str,
    *,
    home: Path | None,
    state: dict[str, Any] | None = None,
) -> str | None:
    """Reject echo packs that jump over the next required N.

    The first echo of a wave (tools_in_flight == 0) must be exactly the lowest
    missing N. Later parallel siblings may be the following contiguous missings.
    """
    import re

    missing = _echo_missing_list(bot, home=home)
    if not missing:
        return None
    m = re.fullmatch(r"echo\s+(\d+)", str(command or "").strip())
    if not m:
        return None
    n = int(m.group(1))
    need = missing[0]
    in_flight = int((state or {}).get("tools_in_flight") or 0)
    # Contiguous missing run from the lowest gap.
    contiguous: list[int] = []
    expect = need
    for x in missing:
        if x != expect:
            break
        contiguous.append(x)
        expect += 1
    window = set(contiguous[:80])
    if in_flight <= 0:
        if n != need:
            return (
                f"echo {n} starts a pack but the next required echo is {need} "
                f"(missing {missing[:20]}{'…' if len(missing) > 20 else ''})"
            )
        return None
    if n not in window:
        return (
            f"echo {n} is outside the required contiguous pack starting at "
            f"{need} (allowed through {max(window) if window else need})"
        )
    return None


def _review_milestone_already_posted(
    bot: str, *, count: int, home: Path | None
) -> bool:
    """True if a guard review card for this action_count already exists since the last user turn."""
    try:
        msgs = chat_svc.list_messages(bot, limit=120, home=home)
        last_user_at = ""
        for m in msgs:
            if m.get("role") == "user":
                last_user_at = m.get("created_at") or last_user_at
        for m in msgs:
            if last_user_at and (m.get("created_at") or "") < last_user_at:
                continue
            meta = m.get("meta") or {}
            if (
                meta.get("kind") == "guard"
                and meta.get("review")
                and int(meta.get("action_count") or -1) == int(count)
            ):
                return True
    except Exception:
        log.exception("review milestone scan failed for %s", bot)
    return False


def _rewrite_refused_guard_stop(
    bot: str,
    *,
    state: dict[str, Any],
    home: Path | None,
    reason: str,
) -> None:
    """Refuse a premature GUARD:STOP: rewrite the bubble so the chat card stays CONTINUE."""
    import re

    if state.get("guard_stop_rewritten"):
        return
    state["guard_stop_rewritten"] = True
    raw = str(state.get("content") or "")
    rewritten = re.sub(
        r"GUARD:\s*STOP\b",
        "GUARD:CONTINUE",
        raw,
        count=1,
        flags=re.IGNORECASE,
    )
    if rewritten == raw:
        rewritten = "GUARD:CONTINUE\n"
    state["content"] = rewritten
    msg_id = state.get("msg_id")
    if msg_id:
        try:
            chat_svc.update_message(bot, msg_id, rewritten, home=home)
        except Exception:
            log.exception("rewrite refused GUARD:STOP bubble failed for %s", bot)
    try:
        MANAGER.steer(
            bot,
            "GUARD:STOP refused — the chat card was corrected to CONTINUE because "
            f"the echo sequence is not finished ({reason}). Emit the missing/"
            "remaining echo tool calls now (batch_sequential, sized to the next "
            "review boundary). Do not claim the task is done.",
        )
    except Exception:
        log.exception("steer after refused GUARD:STOP failed for %s", bot)


def _echo_sequence_incomplete_reason(
    bot: str, *, home: Path | None = None
) -> str | None:
    """If chat shows an unfinished echo-N task, return a short reason; else None."""
    try:
        nums, mx = _echo_progress_from_chat(bot, home=home)
    except Exception:
        log.exception("echo incomplete scan failed for %s", bot)
        return None
    target = None
    user_blob = ""
    try:
        recent = chat_svc.list_messages(bot, limit=30, home=home)
        user_blob = " ".join(
            (m.get("content") or "")
            for m in recent
            if m.get("role") == "user"
        ).lower()
        if "echo" in user_blob and "250" in user_blob:
            target = 250
    except Exception:
        pass
    # User asked for 250 echoes but almost none succeeded (wrong tool, etc.).
    if target and len(nums) < target:
        if len(nums) == 0:
            return (
                f"0/{target} successful vm_terminal_exec echo calls — do not STOP; "
                "use vm_terminal_exec (not bash) for each echo N"
            )
        missing = [i for i in range(1, max(mx, target) + 1) if i not in nums]
        show = missing[:25]
        more = (
            f" (+{len(missing) - len(show)} more)" if len(missing) > len(show) else ""
        )
        return (
            f"{len(nums)}/{target} successful unique echoes, highest={mx}, "
            f"missing={show}{more}"
        )
    if len(nums) < 10:
        return None
    missing = [i for i in range(1, mx + 1) if i not in nums]
    if len(missing) >= 3:
        show = missing[:25]
        more = f" (+{len(missing) - len(show)} more)" if len(missing) > len(show) else ""
        return f"echo gaps missing={show}{more}"
    return None


def _guard_resume_prompt_for(bot: str, *, home: Path | None = None) -> str:
    parts = [_GUARD_RESUME_PROMPT]
    last = _last_done_shell.get(bot) or ""
    if last:
        parts.append(
            f"Last successful shell command was: {last!r}. Continue with the next "
            "required command after that (retry it only if it has no successful "
            "result)."
        )
    gap = _echo_gap_instruction(bot, home=home)
    if gap:
        parts.append(gap)
    return "\n".join(parts)


def _kick_retryable_failure_run(bot: str, home: Path | None) -> None:
    """Auto-retry after RPC/provider failure without waiting for the scheduler."""
    import time

    time.sleep(2.0)
    try:
        if has_pending_human_wait(bot, home=home):
            return
        if run_in_progress(bot):
            return
        if not chat_svc.retryable_failed_turn(bot, home=home):
            return
        now = time.monotonic()
        with _PROGRESS_LOCK:
            last_retry = _LAST_SILENT_RETRY.get(bot, 0.0)
            if (now - last_retry) < _SILENT_BUSY_COOLDOWN_SEC:
                return
            _LAST_SILENT_RETRY[bot] = now
        out = chat_svc.retry_unprocessed(bot, home=home)
        log.warning(
            "auto-retry after failure bot=%s action=%s",
            bot,
            (out or {}).get("action"),
        )
    except Exception:
        log.exception("auto-retry after failure failed for %s", bot)


def _kick_guard_resume_run(bot: str, home: Path | None) -> None:
    """Resume the task after CONTINUE landed on an already-aborted gate turn."""
    import time

    time.sleep(0.35)
    try:
        row = bots_svc.get_bot(bot, home=home)
        if (row.get("status") or "") in ("busy", "waiting"):
            time.sleep(1.0)
            if (bots_svc.get_bot(bot, home=home).get("status") or "") in (
                "busy",
                "waiting",
            ):
                log.warning("guard resume deferred — bot %s still busy", bot)
                return
        get_agent(
            str(settings_svc.get("agent_backend", home=home, default="pi") or "pi"),
            home=home,
        ).start_run(bot, _guard_resume_prompt_for(bot, home=home), home=home)
    except Exception:
        log.exception("guard resume run failed for %s", bot)

def _kick_guard_gate_run(bot: str, home: Path | None) -> None:
    """Follow-up run that only accepts GUARD:CONTINUE / STOP before tools resume."""
    import time

    time.sleep(0.35)
    info = _pop_pending_guard_gate(bot)
    if not info:
        return
    try:
        row = bots_svc.get_bot(bot, home=home)
        if (row.get("status") or "") in ("busy", "waiting"):
            _queue_pending_guard_gate(
                bot,
                count=info["count"],
                limit=info["limit"],
                review_every=info["review_every"],
            )
            time.sleep(1.0)
            if (bots_svc.get_bot(bot, home=home).get("status") or "") in (
                "busy",
                "waiting",
            ):
                log.warning("guard gate deferred — bot %s still busy", bot)
                return
            info = _pop_pending_guard_gate(bot) or info
        # Mark the next start_run as a gate-only turn (all tools blocked until CONTINUE).
        _arm_guard_gate_run_mode(bot, info)
        prompt = _GUARD_GATE_RUN_PROMPT.format(
            count=info["count"],
            limit=info["limit"],
            review_every=info["review_every"] or "?",
        )
        gap = _echo_gap_instruction(bot, home=home)
        if gap:
            prompt = f"{prompt}\n\n{gap}"
        get_agent(
            str(settings_svc.get("agent_backend", home=home, default="pi") or "pi"),
            home=home,
        ).start_run(bot, prompt, home=home)
    except Exception:
        log.exception("guard gate run failed for %s", bot)
        _clear_pending_guard_gate(bot)


def _format_tool_card(
    tool_name: str,
    *,
    args: dict[str, Any] | None = None,
    status: str = "running",
    result: str | None = None,
) -> str:
    lines = [f"🔧 {tool_name}", f"status: {status}"]
    if args:
        try:
            args_s = json.dumps(args, ensure_ascii=False, indent=2)
        except TypeError:
            args_s = str(args)
        lines.append(args_s)
    if result:
        lines.append("---")
        lines.append(result)
    return "\n".join(lines)


def _tool_result_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif isinstance(block, str):
                    parts.append(block)
            if parts:
                return "\n".join(parts)
        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except TypeError:
            return str(result)
    try:
        return json.dumps(result, ensure_ascii=False, indent=2)
    except TypeError:
        return str(result)


def _tool_result_details(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        details = result.get("details")
        if isinstance(details, dict):
            return details
    return {}


def _tool_timed_out(
    result_text: str,
    *,
    details: dict[str, Any] | None = None,
    is_error: bool = False,
) -> bool:
    """True when the tool stopped because a timeout fired (not a normal error)."""
    del is_error  # reserved — timeout may still be reported as isError by Pi
    details = details or {}
    if details.get("timed_out") is True or details.get("timeout") is True:
        return True
    if details.get("state") == "timeout":
        return True
    # docker/subprocess convention used by vm_terminal_exec
    try:
        if int(details.get("exit_code")) == 124:
            return True
    except (TypeError, ValueError):
        pass
    low = (result_text or "").lower()
    if "[timeout after" in low:
        return True
    if "timed out waiting" in low or "timed out after" in low:
        return True
    if "desk authorization" in low and "timed out" in low:
        return True
    return False


_SHARE_IMG_MD = re.compile(
    r"!\[[^\]]*\]\(/api/v1/bots/[^/\s\)]+/files/raw\?path=[^)]+\)"
)


def _mcp_image_markdowns(result: Any) -> list[str]:
    """Chat markdown for images an MCP tool returned (details.images_md)."""
    details = _tool_result_details(result)
    raw = details.get("images_md")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        md = str(item or "").strip()
        if (
            md.startswith("![")
            and "/files/raw?path=" in md
            and md not in out
        ):
            out.append(md)
    return out


def _extract_share_image_markdown(result: Any) -> str | None:
    """Pull the exact chat markdown from a files_share_image tool result."""
    details = _tool_result_details(result)
    md = str(details.get("markdown") or "").strip()
    if md.startswith("![") and "/files/raw?path=" in md:
        return md
    text = _tool_result_text(result)
    found = _SHARE_IMG_MD.search(text or "")
    return found.group(0) if found else None


def _find_running_tool_msg(
    bot: str, call_id: str, *, home: Path | None = None
) -> str | None:
    if not call_id:
        return None
    for msg in reversed(chat_svc.list_messages(bot, limit=40, home=home)):
        meta = msg.get("meta") or {}
        if (
            meta.get("kind") == "tool"
            and meta.get("tool_call_id") == call_id
            and meta.get("status") == "running"
        ):
            return str(msg["id"])
    return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _pointer_fields(
    tool_name: str,
    args: dict[str, Any],
    result_text: str,
    details: dict[str, Any] | None,
) -> dict[str, Any]:
    """Flatten click/drag coords into message.meta for always-on chat overlays."""
    if tool_name not in _POINTER_TOOLS:
        return {}
    src: dict[str, Any] = {}
    if isinstance(details, dict):
        src.update(details)
    src.update(args or {})
    out: dict[str, Any] = {"pointer": True, "pointer_kind": tool_name}
    for key in ("x", "y", "x2", "y2", "dy"):
        n = _as_int(src.get(key))
        if n is not None:
            out[key] = n
    button = src.get("button")
    if button:
        out["button"] = str(button)

    text = result_text or ""
    if "x" not in out or "y" not in out:
        if tool_name == "vm_click":
            m = re.search(r"at\s*\((\-?\d+)\s*,\s*(\-?\d+)\)", text)
            if m:
                out["x"], out["y"] = int(m.group(1)), int(m.group(2))
            btn = re.search(r"Clicked\s+(\w+)\s+at", text, re.I)
            if btn and "button" not in out:
                out["button"] = btn.group(1).lower()
        elif tool_name == "vm_drag":
            m = re.search(
                r"\((\-?\d+)\s*,\s*(\-?\d+)\)\s*→\s*\((\-?\d+)\s*,\s*(\-?\d+)\)",
                text,
            )
            if m:
                out["x"] = int(m.group(1))
                out["y"] = int(m.group(2))
                out["x2"] = int(m.group(3))
                out["y2"] = int(m.group(4))
        elif tool_name == "vm_scroll":
            m = re.search(
                r"dy=(\-?\d+)\s+at\s*\((\-?\d+)\s*,\s*(\-?\d+)\)",
                text,
            )
            if m:
                out["dy"] = int(m.group(1))
                out["x"] = int(m.group(2))
                out["y"] = int(m.group(3))
    return out


def _screenshot_fields(
    tool_name: str,
    result_text: str,
    details: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep screenshot id/url on tool meta so the chat can nest the image under the tool."""
    if tool_name not in ("vm_screenshot", "vm_ground"):
        return {}
    out: dict[str, Any] = {}
    src = details if isinstance(details, dict) else {}
    shot_id = str(src.get("screenshot_id") or "").strip()
    url = str(src.get("url") or "").strip()
    text = result_text or ""
    if not shot_id:
        m = re.search(r"(?m)^id:\s*([0-9a-f-]{8,})\s*$", text, re.I)
        if not m:
            m = re.search(r"screenshot_id[\"\s:=]+([0-9a-f-]{8,})", text, re.I)
        if m:
            shot_id = m.group(1)
    if not url:
        m = re.search(r"(?m)^url:\s*(\S+)\s*$", text)
        if not m:
            m = re.search(r"(/api/v1/bots/\S+/screen/screenshots/[0-9a-f-]+\.png)", text)
        if m:
            url = m.group(1)
    if shot_id:
        out["screenshot_id"] = shot_id
    if url:
        out["screenshot_url"] = url
    return out


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


def _not_ready_text(info: dict[str, Any]) -> str:
    doc = info.get("doc_url") or "https://pi.dev/docs/latest/models"
    local = info.get("local_doc") or "docs/features/pi-agent.md"
    if not info.get("installed"):
        return (
            "Pi is not installed on this host. Install it, then configure a provider/model. "
            f"See {local} and {doc}"
        )
    return (
        "Pi is installed but no model is available. Configure a provider "
        f"(API key / OAuth) or a local endpoint in ~/.pi/agent/models.json. "
        f"Docs: {local} — {doc}"
    )


def get_agent(backend: str | None = None, *, home: Path | None = None) -> AgentBackend:
    name = backend
    if name is None:
        name = str(settings_svc.get("agent_backend", home=home, default="pi") or "pi")
    if name == "pi":
        return PiAgent()
    return NullAgent()
