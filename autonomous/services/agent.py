"""Agent backends — Pi RPC (streaming) + NullAgent."""

from __future__ import annotations

import json
import logging
import re
import threading
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
        "files_attach",
        # Shared memory: MemoryProposalCard only (no 🔧 dump in chat).
        "memory_propose",
        "memory_list",
        "memory_get",
        "memory_search",
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

        bots_svc.patch_bot(bot, {"status": "busy"}, home=home)
        # Keep desk awake while the agent runs (auto-sleep skips busy).
        try:
            from autonomous.services import desk as desk_svc

            desk = row.get("desk") or {}
            if desk.get("state") in ("sleeping", "running"):
                desk_svc.ensure_awake(bot, home=home)
        except Exception:
            pass

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
            "settled": settled,
            "aborted": False,
            "error": None,
            "action_count": action_count,
            "action_limit": action_limit,
            "review_every": review_every,
            "reviews_steered": set(),  # milestones already steered this process
            "pending_secret_reformulate": False,
            "meta_base": {
                "pi_session_id": session_id,
                "model": model,
            },
        }

        def flush_pending_images(*, persist: bool = False) -> None:
            """Ensure files_share_image markdown is in the assistant text (even if model forgot)."""
            pending = list(state.get("pending_images_md") or [])
            if not pending:
                return
            content = state.get("content") or ""
            extras = [md for md in pending if md and md not in content]
            if not extras:
                state["pending_images_md"] = []
                return
            merged = (content.rstrip() + "\n\n" + "\n\n".join(extras)).strip()
            state["content"] = merged
            state["pending_images_md"] = []
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
                return
            chat_svc.finalize_assistant(bot, msg_id, content, home=home, meta=meta)
            state["msg_id"] = None
            state["content"] = ""

        def on_event(record: dict[str, Any]) -> None:
            rtype = record.get("type")
            if rtype == "message_update":
                ev = record.get("assistantMessageEvent") or {}
                etype = ev.get("type")
                if etype == "text_delta":
                    delta = ev.get("delta") or ""
                    if delta:
                        msg_id = ensure_assistant()
                        state["content"] += delta
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
                    close_assistant()
            elif rtype == "tool_execution_start":
                close_assistant()
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
                # Periodic self-check: steer the LLM (not a full conversation reset).
                if (
                    review_every > 0
                    and count % review_every == 0
                    and count < limit
                ):
                    steered = state.setdefault("reviews_steered", set())
                    if count not in steered:
                        steered.add(count)
                        _steer_progress_review(
                            bot,
                            count=count,
                            limit=limit,
                            review_every=review_every,
                            home=home,
                        )
                call_id = str(record.get("toolCallId") or "")
                tool_name = str(record.get("toolName") or "tool")
                args = record.get("args") if isinstance(record.get("args"), dict) else {}
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
                # Pi often sends empty args on end — keep those from start.
                args = end_args or dict(state["tool_args"].get(call_id) or {})
                is_error = bool(record.get("isError"))
                if tool_name == "files_share_image" and not is_error:
                    md = _extract_share_image_markdown(record.get("result"))
                    if md:
                        state.setdefault("pending_images_md", []).append(md)
                        # Open/reuse assistant bubble so the image can appear even
                        # before the model writes surrounding text.
                        ensure_assistant()
                        flush_pending_images(persist=True)
                if tool_name not in _HIDDEN_TOOL_CARDS:
                    result_text = _tool_result_text(record.get("result"))
                    details = _tool_result_details(record.get("result"))
                    status = "error" if is_error else "done"
                    content = _format_tool_card(
                        tool_name, args=args, status=status, result=result_text
                    )
                    meta = {
                        "kind": "tool",
                        "status": status,
                        "tool_name": tool_name,
                        "tool_call_id": call_id,
                        "args": args,
                        "is_error": is_error,
                        "duration_ms": record.get("durationMs"),
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
                    if text and _wants_guard_stop(text):
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
                    usage = message_obj.get("usage")
                    if isinstance(usage, dict):
                        try:
                            bots_svc.add_token_usage(
                                bot,
                                int(usage.get("input") or 0),
                                int(usage.get("output") or 0),
                                home=home,
                            )
                        except Exception:
                            log.exception("token usage update failed for %s", bot)
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
                prompt_images = list(images or [])
                # Adapt to provider vision limits (some endpoints accept max 2 images).
                cap = attach_svc.max_images_per_prompt(home=home)
                if len(prompt_images) > cap:
                    prompt_images = prompt_images[:cap]
                resp = session.prompt(
                    prompt_text, images=prompt_images or None
                )
                if not resp.get("success"):
                    err = str(resp.get("error") or "Pi rejected the prompt")
                    limit = attach_svc.parse_provider_image_limit(err)
                    if limit is not None and prompt_images and len(prompt_images) > limit:
                        log.warning(
                            "Vision limit %s for bot=%s — retrying with %s image(s)",
                            limit,
                            bot,
                            limit,
                        )
                        try:
                            settings_svc.set_many(
                                {"guard.max_images_per_prompt": limit},
                                home=home,
                            )
                        except Exception:
                            pass
                        prompt_images = prompt_images[:limit]
                        note = (
                            f"\n\n(Provider limit: at most {limit} image(s) "
                            f"per prompt — truncated; continue other images later.)"
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
                state["error"] = str(exc)
                state["settled"].set()
            except Exception as exc:
                log.exception("Pi run failed for %s", bot)
                state["error"] = str(exc)
                state["settled"].set()
            finally:
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
                    else:
                        try:
                            chat_svc.drain_queued_user_messages(bot, home=home)
                        except Exception:
                            log.exception(
                                "drain queued user messages failed for %s", bot
                            )
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
            bots_svc.patch_bot(bot, {"status": "idle"}, home=home)
        except Exception:
            pass
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
    """Steer Pi: ask whether the agent is progressing and wants to continue."""
    remaining = max(0, limit - count)
    steer_msg = (
        f"GUARD RAIL checkpoint: you have used {count} tool calls since the last "
        f"user message / webhook / cron (hard limit {limit}, ~{remaining} left). "
        f"Reviews fire every {review_every} tools.\n"
        "Answer briefly:\n"
        "1) Are you still making progress toward the user's goal?\n"
        "2) Do you want to continue?\n"
        "If you should stop, reply with exactly GUARD:STOP and do not call more tools.\n"
        "If you continue, reply with exactly GUARD:CONTINUE then take the next useful step."
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


_SHARE_IMG_MD = re.compile(
    r"!\[[^\]]*\]\(/api/v1/bots/[^/\s\)]+/files/raw\?path=[^)]+\)"
)


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
