"""Bots, chat, desk, terminal, files API."""

from __future__ import annotations

from io import BytesIO

from flask import g, request, send_file
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from autonomous.models.schemas import (
    BotCreateSchema,
    BotPackageUsageSchema,
    BotPatchSchema,
    BotSchema,
    BrowserClickSelectorSchema,
    BrowserEvalSchema,
    BrowserHtmlSchema,
    BrowserLinksSchema,
    BrowserNavigateSchema,
    BrowserResultSchema,
    BrowserScrollSchema,
    BrowserTabSchema,
    BrowserWaitLoadSchema,
    BrowserSnapshotSchema,
    BrowserTextSchema,
    CapabilitySchema,
    ChatFileAttachmentSchema,
    DeskCreateSchema,
    DeskRequestResultSchema,
    DeskRequestSchema,
    DeskResetSchema,
    DeskSchema,
    DeskClickResultSchema,
    DeskClickSchema,
    DeskDragResultSchema,
    DeskDragSchema,
    DeskKeyResultSchema,
    DeskKeySchema,
    DeskScrollResultSchema,
    DeskScrollSchema,
    DeskTypeResultSchema,
    DeskTypeSchema,
    FileContentSchema,
    FileEntrySchema,
    FileMoveSchema,
    FileWriteSchema,
    FilesQuerySchema,
    GroundLocateResultSchema,
    GroundLocateSchema,
    ScreenDescribeResultSchema,
    ScreenDescribeSchema,
    JobSchema,
    BotMailAskSchema,
    BotMailDelegateSchema,
    BotMailPeerSchema,
    BotMailSendSchema,
    HouseholdCreateSchema,
    HouseholdDeleteCreateSchema,
    HouseholdDeleteResolveSchema,
    MessageCreateSchema,
    ScheduleCreateSchema,
    SchedulePatchSchema,
    ScheduleSchema,
    WebhookCreateSchema,
    WebhookPatchSchema,
    WebhookSchema,
    MessageListQuerySchema,
    MessageSchema,
    ReactionCreateSchema,
    NovncInfoSchema,
    OkSchema,
    RetryUnprocessedSchema,
    ScreenshotCreateSchema,
    ScreenshotSchema,
    TerminalExecSchema,
    TerminalLogSchema,
    VaultInjectResultSchema,
    VaultInjectSchema,
)
from autonomous.services import bot_events as bot_events_svc
from autonomous.services import botmail as botmail_svc
from autonomous.services import bots as bots_svc
from autonomous.services import browser as browser_svc
from autonomous.services import chat as chat_svc
from autonomous.services import desk as desk_svc
from autonomous.services import desk_input as desk_input_svc
from autonomous.services import files as files_svc
from autonomous.services import grounding as ground_svc
from autonomous.services import screenshot as shot_svc
from autonomous.services import terminal as term_svc
from autonomous.services import vault_inject as vault_inject_svc
from autonomous.i18n import t
from autonomous.services.errors import AutonomousError, Forbidden, ValidationError
from autonomous.services.events import sse_response


def _abs_webhook_url(url_path: str) -> str:
    """Absolute fire URL for display / agents.

    Prefer ``AUTONOMOUS_PUBLIC_URL`` when set so we don't advertise
    ``http://127.0.0.1`` (unreachable from outside) or plain ``http://`` behind a
    TLS terminator that answers with a 301 and drops the Bearer on follow.
    """
    import os

    public = (os.environ.get("AUTONOMOUS_PUBLIC_URL") or "").strip().rstrip("/")
    root = public or (request.url_root or "").rstrip("/")
    path = url_path if str(url_path).startswith("/") else f"/{url_path}"
    return f"{root}{path}"


def _with_webhook_url(row: dict) -> dict:
    out = dict(row)
    path = out.get("url_path") or "/api/v1/hooks"
    out["url"] = _abs_webhook_url(path)
    return out

blp = Blueprint("bots", __name__, url_prefix="/bots", description="Bots")


def _handle(exc: Exception):
    if isinstance(exc, AutonomousError):
        # flask-smorest uses `code` for HTTP status — expose domain code as error_code.
        abort(exc.http_status, message=exc.message, error_code=exc.code)
    raise exc


@blp.route("")
class BotList(MethodView):
    @blp.response(200, BotSchema(many=True))
    def get(self):
        """List all bots."""
        return bots_svc.list_bots(home=g.home)

    @blp.arguments(BotCreateSchema)
    @blp.response(201, BotSchema)
    def post(self, data):
        """Create a bot (capability starts at none). 409 ``setup_incomplete`` until setup is ready."""
        try:
            from autonomous.services import setup as setup_svc

            setup_svc.ensure_ready(g.home)
            model = (data.get("model") or "").strip()
            if not model:
                raise ValidationError(t("bot.model_required"), code="model_required")
            return bots_svc.create_bot(
                data["name"],
                label=data.get("label"),
                slug=data.get("slug"),
                internet=data.get("internet", True),
                memory_access=data.get("memory_access", True),
                is_manager=bool(data.get("is_manager", False)),
                model=model,
                avatar=data.get("avatar"),
                avatar_color=data.get("avatar_color"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/token-usage")
class BotTokenUsageHistory(MethodView):
    def get(self):
        """Daily cumulative token series for every living bot (Settings chart)."""
        from autonomous.services import token_usage_history as usage_hist

        return usage_hist.history(home=g.home)


@blp.route("/<string:name>")
class BotDetail(MethodView):
    @blp.response(200, BotSchema)
    def get(self, name):
        """Get bot details."""
        try:
            return bots_svc.get_bot(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(BotPatchSchema)
    @blp.response(200, BotSchema)
    def patch(self, data, name):
        """Update bot fields."""
        try:
            if "model" in data and not str(data.get("model") or "").strip():
                raise ValidationError(t("bot.model_required"), code="model_required")
            return bots_svc.patch_bot(name, data, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.response(200, OkSchema)
    def delete(self, name):
        """Delete bot (and desk by default)."""
        try:
            bots_svc.delete_bot(name, home=g.home)
            return {"ok": True}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/capability")
class BotCapability(MethodView):
    @blp.arguments(CapabilitySchema)
    @blp.response(200, BotSchema)
    def post(self, data, name):
        """Set capability: none removes the VM, screen (or legacy terminal) creates it."""
        try:
            return bots_svc.set_capability(name, data["level"], home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/messages/export.pdf")
class BotMessagesExportPdf(MethodView):
    def get(self, name):
        """Download the discussion as PDF (tool names only, no args/results)."""
        from autonomous.services import chat_export as chat_export_svc

        try:
            pdf, filename = chat_export_svc.export_discussion_pdf(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)
        return send_file(
            BytesIO(pdf),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )


@blp.route("/<string:name>/messages")
class BotMessages(MethodView):
    @blp.arguments(MessageListQuerySchema, location="query")
    @blp.response(200, MessageSchema(many=True))
    def get(self, query, name):
        """List chat messages (newest page, chronological)."""
        try:
            return chat_svc.list_messages(
                name,
                before=query.get("before"),
                limit=query.get("limit", 50),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(MessageCreateSchema)
    @blp.response(201, MessageSchema)
    def post(self, data, name):
        """Send a user message; starts a Pi agent run when configured."""
        try:
            return chat_svc.send_message(
                name,
                data.get("content") or "",
                attachments=data.get("attachments") or [],
                prompt=data.get("prompt"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)

    @blp.response(200, OkSchema)
    def delete(self, name):
        """Clear chat history (also rotates the Pi session)."""
        try:
            n = chat_svc.clear_messages(name, home=g.home)
            return {"ok": True, "message": f"deleted {n}"}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/messages/<string:message_id>")
class BotMessageDetail(MethodView):
    @blp.response(200, OkSchema)
    def delete(self, name, message_id):
        """Cancel a still-queued chat message (user / webhook / schedule)."""
        try:
            return chat_svc.delete_queued_message(name, message_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/reactions")
class BotReactions(MethodView):
    @blp.arguments(ReactionCreateSchema)
    @blp.response(200, MessageSchema)
    def post(self, data, name):
        """Add one emoji reaction on a user message (does not end the agent turn)."""
        from autonomous.services import reactions as reactions_svc

        try:
            return reactions_svc.add_reaction(
                name,
                data["emoji"],
                message_id=data.get("message_id"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/chat/attachments/<string:filename>")
class ChatAttachmentFile(MethodView):
    def get(self, name, filename):
        """Serve a pasted chat image (auth required)."""
        from autonomous.services import chat_attachments as attach_svc

        try:
            path = attach_svc.resolve_file(name, filename, home=g.home)
        except AutonomousError as exc:
            _handle(exc)
            return None
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(path.suffix.lower(), "application/octet-stream")
        return send_file(path, mimetype=mime, max_age=3600)


@blp.route("/<string:name>/chat/files")
class ChatFileUpload(MethodView):
    @blp.response(201, ChatFileAttachmentSchema)
    @blp.doc(summary="Upload a chat file into ~/files/upload/<uuid>/")
    def post(self, name):
        """Multipart field ``file`` → stored under ~/files/upload/<uuid>/<name>."""
        if "file" not in request.files:
            abort(400, message="Missing file field")
        up = request.files["file"]
        if not up or not up.filename:
            abort(400, message="Empty filename")
        try:
            return files_svc.save_chat_upload(
                name,
                filename=up.filename,
                stream=up.stream,
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/mail/peers")
class BotMailPeers(MethodView):
    @blp.response(200, BotMailPeerSchema(many=True))
    def get(self, name):
        """List other bots (managers only) for orchestration."""
        try:
            return botmail_svc.list_peers(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/mail/tell")
class BotMailTell(MethodView):
    @blp.arguments(BotMailSendSchema)
    @blp.response(201, OkSchema)
    def post(self, data, name):
        """Send a one-way message to another bot (Dit à @…).

        Optional ``attachments`` copy files into the peer's mail-inbox staging.
        Managers may set ``expect_reply`` to wrap the body as an async delegation
        (same footer as ``/mail/delegate``) — one mail path for files + callback.
        """
        try:
            me = bots_svc.get_bot(name, home=g.home)
            content = data.get("content") or ""
            attachments = data.get("attachments") or None
            expect_reply = data.get("expect_reply")
            if expect_reply is not None and str(expect_reply).strip() != "":
                if not me.get("is_manager"):
                    raise Forbidden(
                        "Only a Manager bot can set expect_reply on tell.",
                        code="manager_required",
                    )
                content = botmail_svc.format_delegate_content(
                    manager_slug=name,
                    task=content,
                    expect_reply=expect_reply,
                    has_attachments=bool(attachments),
                )
            item = botmail_svc.tell(
                name,
                data["to"],
                content,
                home=g.home,
                origin="api",
                attachments=attachments,
            )
            return {"ok": True, "message": item["id"]}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/mail/delegate")
class BotMailDelegate(MethodView):
    @blp.arguments(BotMailDelegateSchema)
    @blp.response(201, OkSchema)
    def post(self, data, name):
        """Manager: assign a task without waiting; peer must Dit-à back to relaunch.

        Sugar over ``/mail/tell`` with ``expect_reply``. For files, use ``/mail/tell``
        with ``attachments`` (+ optional ``expect_reply``) — do not invent a second path.
        """
        try:
            me = bots_svc.get_bot(name, home=g.home)
            if not me.get("is_manager"):
                raise Forbidden(
                    "Only a Manager bot can delegate.",
                    code="manager_required",
                )
            content = botmail_svc.format_delegate_content(
                manager_slug=name,
                task=data["task"],
                expect_reply=data.get("expect_reply"),
                has_attachments=False,
            )
            item = botmail_svc.tell(
                name,
                data["to"],
                content,
                home=g.home,
                origin="api",
            )
            return {"ok": True, "message": item["id"]}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/household/models")
class BotHouseholdModels(MethodView):
    def get(self, name):
        """Manager: list Pi models usable when creating bots."""
        try:
            from autonomous.services import household as household_svc

            household_svc.require_manager(name, home=g.home)
            models = household_svc.list_available_models(home=g.home)
            return {
                "default_model": household_svc.default_model(home=g.home),
                "models": models,
            }
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/household/bots")
class BotHouseholdCreate(MethodView):
    @blp.arguments(HouseholdCreateSchema)
    def post(self, data, name):
        """Manager: create one or more bots (model optional → Settings default)."""
        try:
            from autonomous.services import household as household_svc

            created = household_svc.create_bots(
                name, data.get("bots") or [], home=g.home
            )
            return {"ok": True, "created": created}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/household/delete-requests")
class BotHouseholdDeleteRequests(MethodView):
    @blp.arguments(HouseholdDeleteCreateSchema)
    def post(self, data, name):
        """Manager: show a checkbox delete card and wait (tool polls)."""
        try:
            from autonomous.services import household as household_svc

            return household_svc.create_delete_request(
                name,
                bots=data.get("bots") or [],
                prompt=data.get("prompt") or "",
                title=data.get("title") or "",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/household/delete-requests/<string:request_id>")
class BotHouseholdDeleteRequestItem(MethodView):
    def get(self, name, request_id):
        """Poll a household delete request (Manager token)."""
        try:
            from autonomous.services import household as household_svc

            household_svc.require_manager(name, home=g.home)
            req = household_svc.get_delete_request(request_id, home=g.home)
            if req.get("bot") != name:
                raise Forbidden("Not your delete request", code="bot_token_forbidden")
            return req
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(HouseholdDeleteResolveSchema)
    def post(self, data, name, request_id):
        """Confirm (with checked bots) or deny a household delete card."""
        try:
            from autonomous.services import household as household_svc

            # Session / admin resolve from the UI; Manager token may also poll.
            req = household_svc.get_delete_request(request_id, home=g.home)
            if req.get("bot") != name:
                raise Forbidden("Not your delete request", code="bot_token_forbidden")
            return household_svc.resolve_delete_request(
                request_id,
                action=data.get("action") or "",
                selected=data.get("bots"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/mail/ask")
class BotMailAsk(MethodView):
    @blp.arguments(BotMailSendSchema)
    @blp.response(201, BotMailAskSchema)
    def post(self, data, name):
        """Ask another bot a question; reply will relaunch this bot when ready."""
        try:
            bots_svc.get_bot(name, home=g.home)
            return botmail_svc.ask(
                name,
                data["to"],
                data.get("content") or "",
                home=g.home,
                origin="api",
                attachments=data.get("attachments") or None,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/mail/asks/<string:ask_id>")
class BotMailAskStatus(MethodView):
    @blp.response(200, BotMailAskSchema)
    def get(self, name, ask_id):
        """Poll an inter-bot ask (pauses asker runtime while open)."""
        try:
            bots_svc.get_bot(name, home=g.home)
            ask = botmail_svc.get_ask(ask_id, home=g.home)
            if ask["from_bot"] != name and ask["to_bot"] != name:
                raise Forbidden("Ask does not involve this bot")
            return ask
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/schedules")
class BotSchedules(MethodView):
    @blp.response(200, ScheduleSchema(many=True))
    def get(self, name):
        """List scheduled tasks (cron shown in the user timezone)."""
        try:
            return bot_events_svc.list_schedules(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(ScheduleCreateSchema)
    @blp.response(201, ScheduleSchema)
    def post(self, data, name):
        """Create a scheduled task. `cron` is host-local; storage is UTC."""
        try:
            return bot_events_svc.create_schedule(
                name,
                name=data["name"],
                cron=data["cron"],
                instruction=data.get("instruction") or "",
                recurring=data.get("recurring", True),
                anchor_message_id=data.get("anchor_message_id"),
                enabled=data.get("enabled", True),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/schedules/<string:schedule_id>")
class BotScheduleItem(MethodView):
    @blp.response(200, ScheduleSchema)
    def get(self, name, schedule_id):
        try:
            return bot_events_svc.get_schedule(name, schedule_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(SchedulePatchSchema)
    @blp.response(200, ScheduleSchema)
    def patch(self, data, name, schedule_id):
        """Update schedule (toggle enabled, edit fields)."""
        try:
            return bot_events_svc.update_schedule(
                name, schedule_id, data, home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)

    @blp.response(200, OkSchema)
    def delete(self, name, schedule_id):
        try:
            bot_events_svc.delete_schedule(name, schedule_id, home=g.home)
            return {"ok": True}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/webhooks")
class BotWebhooks(MethodView):
    @blp.response(200, WebhookSchema(many=True))
    def get(self, name):
        """List inbound webhooks for this bot."""
        try:
            return [
                _with_webhook_url(w)
                for w in bot_events_svc.list_webhooks(name, home=g.home)
            ]
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(WebhookCreateSchema)
    @blp.response(201, WebhookSchema)
    def post(self, data, name):
        """Create an inbound webhook (tokenized public URL)."""
        try:
            row = bot_events_svc.create_webhook(
                name,
                name=data["name"],
                instruction=data.get("instruction") or "",
                anchor_message_id=data.get("anchor_message_id"),
                enabled=data.get("enabled", True),
                home=g.home,
            )
            return _with_webhook_url(row)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/webhooks/<string:webhook_id>")
class BotWebhookItem(MethodView):
    @blp.response(200, WebhookSchema)
    def get(self, name, webhook_id):
        try:
            return _with_webhook_url(
                bot_events_svc.get_webhook(name, webhook_id, home=g.home)
            )
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(WebhookPatchSchema)
    @blp.response(200, WebhookSchema)
    def patch(self, data, name, webhook_id):
        try:
            return _with_webhook_url(
                bot_events_svc.update_webhook(
                    name, webhook_id, data, home=g.home
                )
            )
        except AutonomousError as exc:
            _handle(exc)

    @blp.response(200, OkSchema)
    def delete(self, name, webhook_id):
        try:
            bot_events_svc.delete_webhook(name, webhook_id, home=g.home)
            return {"ok": True}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/stop")
class BotStop(MethodView):
    @blp.response(200, OkSchema)
    def post(self, name):
        """Abort the current Pi agent run for this bot."""
        try:
            chat_svc.stop_run(name, home=g.home)
            return {"ok": True}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/resume")
class BotResume(MethodView):
    @blp.response(200, OkSchema)
    def post(self, name):
        """Resume the agent after an interrupted wait (vault/desk approval)."""
        try:
            return chat_svc.resume_run(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/retry")
class BotRetryUnprocessed(MethodView):
    @blp.response(200, RetryUnprocessedSchema)
    def post(self, name):
        """Relaunch queued / unfinished work after an LLM outage (keeps chat + Pi session)."""
        try:
            return chat_svc.retry_unprocessed(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/events")
class BotEvents(MethodView):
    @blp.doc(
        summary="Per-bot SSE stream",
        produces=["text/event-stream"],
    )
    def get(self, name):
        """Subscribe to events for one bot."""
        try:
            bots_svc.get_bot(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

        return sse_response(name)


@blp.route("/<string:name>/package")
class BotPackage(MethodView):
    @blp.response(200, BotPackageUsageSchema)
    def get(self, name):
        """Disk footprint for this bot (VM layer + ~/files + chat + Pi session)."""
        from autonomous.services import bot_package as package_svc

        try:
            return package_svc.package_usage(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk")
class BotDesk(MethodView):
    @blp.response(200, DeskSchema)
    def get(self, name):
        """Desktop / VM status (empty object when absent)."""
        try:
            desk = desk_svc.status(name, home=g.home)
            return desk or {"state": "absent"}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/request")
class DeskRequest(MethodView):
    @blp.arguments(DeskRequestSchema)
    @blp.response(200, DeskRequestResultSchema)
    def post(self, data, name):
        """Ask the user to authorize a desk (chat card + UI modal)."""
        try:
            return desk_svc.request_authorization(
                name,
                reason=data.get("reason") or "",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/request/resolve")
class DeskRequestResolve(MethodView):
    @blp.response(200, OkSchema)
    def post(self, name):
        """Resolve pending desk_request cards (deny from UI). Body: {action: deny}."""
        body = request.get_json(silent=True) or {}
        action = (body.get("action") or "deny").strip().lower()
        if action not in ("deny", "denied"):
            abort(400, message="Only action=deny is supported here (approve via desk/create)")
        try:
            desk_svc.resolve_desk_requests(name, state="denied", home=g.home)
            # Unblock waiting agent poll (vm_request_desk) — same as vault deny.
            try:
                row = bots_svc.get_bot(name, home=g.home)
                if (row.get("status") or "") == "waiting":
                    bots_svc.patch_bot(name, {"status": "idle"}, home=g.home)
            except Exception:
                pass
            return {"ok": True}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/create")
class DeskCreate(MethodView):
    @blp.arguments(DeskCreateSchema)
    @blp.response(202, JobSchema)
    def post(self, data, name):
        """Create the VM (shell + desktop). Optional internet on/off."""
        try:
            return desk_svc.create(
                name,
                home=g.home,
                internet=data.get("internet", True),
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/destroy")
class DeskDestroy(MethodView):
    @blp.response(202, JobSchema)
    def post(self, name):
        """Destroy desktop container (async job)."""
        try:
            return desk_svc.destroy(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/activity")
class DeskActivity(MethodView):
    @blp.response(200, DeskSchema)
    def post(self, name):
        """Reset the auto-sleep clock. Does not wake a sleeping desk."""
        try:
            bot = bots_svc.get_bot(name, home=g.home)
            desk = dict(bot.get("desk") or {"state": "absent"})
            if desk.get("state") == "running":
                desk_svc.touch_activity(name, home=g.home)
            return desk
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/wake")
class DeskWake(MethodView):
    @blp.response(200, DeskSchema)
    def post(self, name):
        """Wake a sleeping desk (or touch activity if already running)."""
        try:
            return desk_svc.ensure_awake(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/restart")
class DeskRestart(MethodView):
    @blp.response(200, DeskSchema)
    def post(self, name):
        """Restart desktop (data kept)."""
        try:
            return desk_svc.restart(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/reset")
class DeskReset(MethodView):
    @blp.arguments(DeskResetSchema)
    @blp.response(202, JobSchema)
    def post(self, data, name):
        """Wipe home volume and recreate desktop."""
        try:
            return desk_svc.reset(name, confirm=bool(data.get("confirm")), home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/desk/novnc")
class DeskNovnc(MethodView):
    @blp.response(200, NovncInfoSchema)
    def get(self, name):
        """noVNC connection info for the UI."""
        try:
            return desk_svc.novnc_info(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/screenshot")
class ScreenScreenshot(MethodView):
    @blp.arguments(ScreenshotCreateSchema)
    @blp.response(201, ScreenshotSchema)
    def post(self, data, name):
        """Capture the bot desktop (X11). Works without any browser open."""
        try:
            return shot_svc.capture(
                name,
                show_in_chat=bool(data.get("show_in_chat", True)),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/screenshots/<string:shot_id>")
class ScreenScreenshotFile(MethodView):
    def get(self, name, shot_id):
        """Serve a captured PNG (auth required)."""
        try:
            path = shot_svc.resolve_png(name, shot_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)
            return None
        return send_file(path, mimetype="image/png", max_age=3600)


@blp.route("/<string:name>/terminal")
class BotTerminal(MethodView):
    @blp.response(200, TerminalLogSchema(many=True))
    def get(self, name):
        """Terminal command history."""
        try:
            return term_svc.list_logs(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/terminal/exec")
class TerminalExec(MethodView):
    @blp.arguments(TerminalExecSchema)
    @blp.response(200, TerminalLogSchema)
    def post(self, data, name):
        """Run a command inside the bot container (VM — not host shell)."""
        try:
            return term_svc.exec_command(
                name,
                data["command"],
                timeout=data.get("timeout") or 30,
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/tools/cancel")
class ToolCancel(MethodView):
    @blp.response(200, OkSchema)
    def post(self, name):
        """Stop the VM command in flight. Does not stop the Pi agent."""
        try:
            bots_svc.get_bot(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)
        cancelled = term_svc.cancel_running_command(name)
        return {
            "ok": True,
            "message": "cancelled" if cancelled else "idle",
        }


@blp.route("/<string:name>/vault/inject")
class BotVaultInject(MethodView):
    @blp.arguments(VaultInjectSchema)
    @blp.response(200, VaultInjectResultSchema)
    def post(self, data, name):
        """Type/paste a granted vault secret into the focused desk window.

        Cleartext goes host→VNC keystrokes only — never returned in the body
        and never meant for the LLM.
        """
        try:
            return vault_inject_svc.inject(
                name,
                entry_id=data["entry_id"],
                field=data.get("field"),
                method=data.get("method") or "type",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/click")
class ScreenClick(MethodView):
    @blp.arguments(DeskClickSchema)
    @blp.response(200, DeskClickResultSchema)
    def post(self, data, name):
        """Click at desktop pixels via VNC (after vm_ground)."""
        try:
            return desk_input_svc.click(
                name,
                data["x"],
                data["y"],
                button=data.get("button") or "left",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/type")
class ScreenType(MethodView):
    @blp.arguments(DeskTypeSchema)
    @blp.response(200, DeskTypeResultSchema)
    def post(self, data, name):
        """Type or paste text into the focused desk window via VNC."""
        try:
            return desk_input_svc.type_text(
                name,
                data["text"],
                method=data.get("method") or "type",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/scroll")
class ScreenScroll(MethodView):
    @blp.arguments(DeskScrollSchema)
    @blp.response(200, DeskScrollResultSchema)
    def post(self, data, name):
        """Scroll the desk via VNC mouse wheel. dy>0 = content down."""
        try:
            return desk_input_svc.scroll(
                name,
                data["dy"],
                x=int(data.get("x") or 0),
                y=int(data.get("y") or 0),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/key")
class ScreenKey(MethodView):
    @blp.arguments(DeskKeySchema)
    @blp.response(200, DeskKeyResultSchema)
    def post(self, data, name):
        """Press a named key on the desk (Return, Tab, Escape, Page_Down, …)."""
        try:
            return desk_input_svc.key(
                name,
                data["key"],
                repeats=int(data.get("repeats") or 1),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/drag")
class ScreenDrag(MethodView):
    @blp.arguments(DeskDragSchema)
    @blp.response(200, DeskDragResultSchema)
    def post(self, data, name):
        """Drag left button from (x,y) to (x2,y2) via VNC (sliders, etc.)."""
        try:
            return desk_input_svc.drag(
                name,
                data["x"],
                data["y"],
                data["x2"],
                data["y2"],
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/tabs")
class BrowserTabs(MethodView):
    @blp.response(200, BrowserResultSchema)
    def get(self, name):
        """List Chrome page targets via CDP (desk must be running)."""
        try:
            return browser_svc.tabs(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/navigate")
class BrowserNavigate(MethodView):
    @blp.arguments(BrowserNavigateSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Navigate the active Chrome tab (CDP)."""
        try:
            return browser_svc.navigate(name, data["url"], home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/html")
class BrowserHtml(MethodView):
    @blp.arguments(BrowserHtmlSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Read page HTML (truncated). Optional CSS selector."""
        try:
            return browser_svc.html(
                name,
                max_chars=int(data.get("max_chars") or 12000),
                selector=data.get("selector"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/text")
class BrowserText(MethodView):
    @blp.arguments(BrowserTextSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Read visible page text (innerText, truncated)."""
        try:
            return browser_svc.text(
                name,
                max_chars=int(data.get("max_chars") or 8000),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/links")
class BrowserLinks(MethodView):
    @blp.arguments(BrowserLinksSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """List links on the page; optional substring filter on text/href."""
        try:
            return browser_svc.links(
                name,
                query=data.get("query"),
                max_links=int(data.get("max_links") or 40),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/reset_session")
class BrowserResetSession(MethodView):
    @blp.response(200, BrowserResultSchema)
    def post(self, name):
        """Clear cookies, cache and current-origin storage (fresh-visitor state)."""
        try:
            return browser_svc.reset_session(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/wait_load")
class BrowserWaitLoad(MethodView):
    @blp.arguments(BrowserWaitLoadSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Wait (bounded, default 15 s) until the active page finished loading."""
        try:
            return browser_svc.wait_load(
                name, timeout=float(data.get("timeout") or 15.0), home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/switch_tab")
class BrowserSwitchTab(MethodView):
    @blp.arguments(BrowserTabSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Bring a tab to the front (all browser tools then act on it)."""
        try:
            return browser_svc.switch_tab(
                name, index=data.get("index") or 0, match=data.get("match") or "", home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/close_tab")
class BrowserCloseTab(MethodView):
    @blp.arguments(BrowserTabSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Close a tab (default: the active one; the last tab is kept)."""
        try:
            return browser_svc.close_tab(
                name, index=data.get("index") or 0, match=data.get("match") or "", home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/scroll")
class BrowserScroll(MethodView):
    @blp.arguments(BrowserScrollSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Scroll the page via CDP (window.scrollBy). Prefer screen/scroll for a real wheel event."""
        try:
            return browser_svc.scroll(
                name,
                dy=int(data.get("dy") if data.get("dy") is not None else 600),
                dx=int(data.get("dx") or 0),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/snapshot")
class BrowserSnapshot(MethodView):
    @blp.arguments(BrowserSnapshotSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Compact interactive DOM (no scroll/click) — plan before grounding."""
        try:
            return browser_svc.snapshot(
                name,
                max_elements=int(data.get("max_elements") or 60),
                query=data.get("query"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/frames_snapshot")
class BrowserFramesSnapshot(MethodView):
    @blp.arguments(BrowserSnapshotSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Page + iframe controls with screen coords (for VNC click/drag)."""
        try:
            return browser_svc.frames_snapshot(
                name,
                max_elements=int(data.get("max_elements") or 60),
                query=data.get("query"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/click_selector")
class BrowserClickSelector(MethodView):
    @blp.arguments(BrowserClickSelectorSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Click by CSS via CDP (scrollIntoView). Prefer VNC ground+click on anti-bot pages."""
        try:
            return browser_svc.click_selector(name, data["selector"], home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/browser/eval")
class BrowserEval(MethodView):
    @blp.arguments(BrowserEvalSchema)
    @blp.response(200, BrowserResultSchema)
    def post(self, data, name):
        """Evaluate a short JS expression in the page (returnByValue)."""
        try:
            return browser_svc.evaluate(name, data["js"], home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/ground")
class ScreenGround(MethodView):
    @blp.arguments(GroundLocateSchema)
    @blp.response(200, GroundLocateResultSchema)
    def post(self, data, name):
        """Locate a UI element on a fresh desk screenshot (no click).

        UI-TARS proposes coordinates; optional multimodal judge confirms via
        hollow cross. Host must not act when ``ok`` is false.
        """
        try:
            return ground_svc.locate(
                name,
                data["instruction"],
                action_hint=data.get("action_hint"),
                verify=bool(data.get("verify", True)),
                check_exists=bool(data.get("check_exists", True)),
                max_retries=data.get("max_retries"),
                show_in_chat=bool(data.get("show_in_chat", True)),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/screen/describe")
class ScreenDescribe(MethodView):
    @blp.arguments(ScreenDescribeSchema)
    @blp.response(200, ScreenDescribeResultSchema)
    def post(self, data, name):
        """Describe the desktop in text (multimodal model) — eyes for a DOM-blind agent."""
        try:
            return ground_svc.describe_screen(
                name,
                data.get("question"),
                show_in_chat=bool(data.get("show_in_chat", False)),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files")
class BotFiles(MethodView):
    @blp.arguments(FilesQuerySchema, location="query")
    @blp.response(200, FileEntrySchema(many=True))
    def get(self, query, name):
        """List files under the bot ~/files directory."""
        try:
            return files_svc.list_dir(name, query.get("path") or ".", home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(FilesQuerySchema, location="query")
    @blp.response(200, OkSchema)
    def delete(self, query, name):
        """Delete a file or directory under ~/files."""
        try:
            files_svc.delete_path(name, query.get("path") or "", home=g.home)
            return {"ok": True}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/mkdir")
class BotFileMkdir(MethodView):
    @blp.response(200, FileEntrySchema)
    @blp.doc(summary="Create a directory under ~/files")
    def post(self, name):
        """Create a directory. JSON body: ``{ "path": ".", "name": "dossier" }``."""
        body = request.get_json(silent=True) or {}
        parent = body.get("path") or request.args.get("path") or "."
        dirname = (body.get("name") or "").strip()
        if not dirname:
            abort(400, message="Missing name")
        try:
            return files_svc.mkdir(name, parent, dirname, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/move")
class BotFileMove(MethodView):
    @blp.arguments(FileMoveSchema)
    @blp.response(200, FileEntrySchema)
    @blp.doc(summary="Move a file or folder within ~/files")
    def post(self, body, name):
        """Move ``src`` into directory ``dest`` (basename preserved)."""
        try:
            return files_svc.move_path(
                name,
                body.get("src") or "",
                body.get("dest") or ".",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/upload")
class BotFileUpload(MethodView):
    @blp.arguments(FilesQuerySchema, location="query")
    @blp.response(200, FileEntrySchema)
    @blp.doc(summary="Upload a file into ~/files")
    def post(self, query, name):
        """Upload a multipart file into the given directory (default: ~/files root)."""
        if "file" not in request.files:
            abort(400, message="Missing file field")
        up = request.files["file"]
        if not up or not up.filename:
            abort(400, message="Empty filename")
        try:
            return files_svc.save_upload(
                name,
                query.get("path") or ".",
                filename=up.filename,
                stream=up.stream,
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/download")
class BotFileDownload(MethodView):
    @blp.arguments(FilesQuerySchema, location="query")
    @blp.doc(summary="Download a file from ~/files")
    def get(self, query, name):
        """Download a single file."""
        try:
            path = files_svc.resolve(name, query.get("path") or "", home=g.home)
            if not path.is_file():
                abort(404, message="Not a file")
            return send_file(path, as_attachment=True, download_name=path.name)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/raw")
class BotFileRaw(MethodView):
    @blp.arguments(FilesQuerySchema, location="query")
    @blp.doc(summary="Serve a ~/files file inline (images in chat)")
    def get(self, query, name):
        """Inline file bytes (no Content-Disposition attachment)."""
        try:
            path = files_svc.resolve(name, query.get("path") or "", home=g.home)
            if not path.is_file():
                abort(404, message="Not a file")
            mime = files_svc.image_mime(path) or "application/octet-stream"
            return send_file(path, mimetype=mime, max_age=3600, conditional=True)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/share")
class BotFileShare(MethodView):
    @blp.response(200)
    @blp.doc(summary="Build markdown to embed a ~/files image in the assistant reply")
    def post(self, name):
        """JSON ``{path, caption?}`` → ``{markdown, url, …}`` (agent pastes markdown in text)."""
        body = request.get_json(silent=True) or {}
        path = (body.get("path") or "").strip()
        if not path:
            abort(400, message="Missing path")
        try:
            return files_svc.share_image(
                name,
                path,
                caption=body.get("caption"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/attach")
class BotFileAttach(MethodView):
    @blp.response(200)
    @blp.doc(summary="Attach a non-image ~/files file to the assistant reply")
    def post(self, name):
        """JSON ``{path}`` → download card on the assistant bubble (PDF, zip, … — not images)."""
        body = request.get_json(silent=True) or {}
        path = (body.get("path") or "").strip()
        if not path:
            abort(400, message="Missing path")
        try:
            return files_svc.attach_file(name, path, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/claim-mail")
class BotFileClaimMail(MethodView):
    @blp.response(200, FileEntrySchema)
    @blp.doc(summary="Move a staged inter-bot mail attachment into ~/files")
    def post(self, name):
        """JSON ``{path, dest}`` — ``path`` under ``.autonomous/mail-inbox/…``."""
        body = request.get_json(silent=True) or {}
        path = (body.get("path") or "").strip()
        dest = (body.get("dest") or "").strip()
        if not path or not dest:
            abort(400, message="Missing path or dest")
        try:
            return files_svc.claim_mail_attachment(
                name, path, dest, home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/files/content")
class BotFileContent(MethodView):
    @blp.arguments(FilesQuerySchema, location="query")
    @blp.response(200, FileContentSchema)
    @blp.doc(summary="Read a UTF-8 text file under ~/files (agent)")
    def get(self, query, name):
        """Return text content of a file (no host shell needed)."""
        try:
            return files_svc.read_text(name, query.get("path") or "", home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(FileWriteSchema)
    @blp.response(200, FileEntrySchema)
    @blp.doc(summary="Write a UTF-8 text file under ~/files (agent)")
    def put(self, body, name):
        """Create or overwrite a text file. JSON: ``{path, content}``."""
        try:
            return files_svc.write_text(
                name,
                body.get("path") or "",
                body.get("content") if body.get("content") is not None else "",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/mcp")
class BotMcpGrants(MethodView):
    @blp.doc(summary="MCP servers this bot may use, plus every published server")
    def get(self, name):
        from autonomous.services import devices as devices_svc

        try:
            return devices_svc.list_bot_mcp(name, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.doc(summary="Allow this bot to use one companion MCP server")
    def post(self, name):
        from autonomous.services import devices as devices_svc

        body = request.get_json(silent=True) or {}
        try:
            return devices_svc.grant_bot_mcp(
                name,
                str(body.get("device_id") or ""),
                str(body.get("server") or ""),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:name>/mcp/<string:grant_id>")
class BotMcpGrantDelete(MethodView):
    @blp.doc(summary="Remove one companion MCP grant from this bot")
    def delete(self, name, grant_id):
        from autonomous.services import devices as devices_svc

        try:
            return devices_svc.revoke_bot_mcp(name, grant_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)
