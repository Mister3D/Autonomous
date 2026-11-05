"""Companion pairing and device-scoped options."""

from __future__ import annotations

from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow import Schema, fields

from autonomous.services import devices as devices_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint("devices", __name__, url_prefix="/devices", description="Companion devices")


class PairStartSchema(Schema):
    name = fields.Str(required=True)
    platform = fields.Str(required=True)


class PairStartResultSchema(Schema):
    pair_id = fields.Str()
    user_code = fields.Str()
    poll_secret = fields.Str()
    expires_at = fields.Str()


class PairPollSchema(Schema):
    pair_id = fields.Str(required=True)
    poll_secret = fields.Str(required=True)


class PairPollResultSchema(Schema):
    status = fields.Str()
    device_id = fields.Str(allow_none=True)
    device_token = fields.Str(allow_none=True)


class OkDeviceSchema(Schema):
    ok = fields.Bool()
    device_id = fields.Str()


class DeviceOptionsSchema(Schema):
    egress = fields.Bool(load_default=None, allow_none=True)
    killswitch = fields.Bool(load_default=None, allow_none=True)


class DeviceNotifySchema(Schema):
    notify = fields.Bool(required=True)


class McpToolSchema(Schema):
    name = fields.Str(required=True)
    description = fields.Str(load_default="")
    input_schema = fields.Raw(load_default="{}")


class McpServerSchema(Schema):
    name = fields.Str(required=True)
    tools = fields.List(fields.Nested(McpToolSchema), load_default=list)


class McpCatalogSchema(Schema):
    servers = fields.List(fields.Nested(McpServerSchema), required=True)


def _device():
    device = getattr(g, "device", None) or devices_svc.device_from_request(g.home)
    if not device:
        abort(401, message="Device authentication required")
    return device


def _handle(exc: AutonomousError):
    abort(exc.http_status, message=exc.message)


@blp.route("/pair")
class PairStart(MethodView):
    @blp.arguments(PairStartSchema)
    @blp.response(200, PairStartResultSchema)
    @blp.doc(security=[])
    def post(self, data):
        """Start a device-code pairing. The user approves the code in Settings."""
        from autonomous.services.client_ip import client_ip
        from autonomous.services.ratelimit import PAIRING

        ip = client_ip(request)
        if not PAIRING.hit(f"pair:{ip}", limit=5, window_s=60):
            abort(429, message="Too many pairing requests — try again shortly.")
        try:
            return devices_svc.start_pairing(data["name"], data["platform"], home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/pair-poll")
class PairPoll(MethodView):
    @blp.arguments(PairPollSchema)
    @blp.response(200, PairPollResultSchema)
    @blp.doc(security=[])
    def post(self, data):
        """Poll until the user approves. The device token is returned once."""
        try:
            return devices_svc.poll_pairing(
                data["pair_id"], data["poll_secret"], home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/")
class DeviceList(MethodView):
    def get(self):
        """Pending codes and paired companions (session auth)."""
        return devices_svc.list_devices(home=g.home)


@blp.route("/pair/<string:pair_id>/approve")
class PairApprove(MethodView):
    @blp.response(200, OkDeviceSchema)
    def post(self, pair_id):
        try:
            return devices_svc.approve_pairing(pair_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/pair/<string:pair_id>/deny")
class PairDeny(MethodView):
    def post(self, pair_id):
        try:
            return devices_svc.deny_pairing(pair_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/<string:device_id>")
class DeviceRevoke(MethodView):
    def delete(self, device_id):
        try:
            return devices_svc.revoke_device(device_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(DeviceNotifySchema)
    def patch(self, data, device_id):
        """Choose whether this companion receives notifications."""
        try:
            return devices_svc.set_notify(device_id, bool(data["notify"]), home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/me")
class DeviceMe(MethodView):
    @blp.arguments(DeviceOptionsSchema)
    def patch(self, data):
        """Companion pushes egress and killswitch."""
        device = _device()
        try:
            return devices_svc.update_options(
                device["id"],
                egress=data.get("egress"),
                killswitch=data.get("killswitch"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)

    def delete(self):
        """Companion forgets itself."""
        device = _device()
        try:
            return devices_svc.revoke_device(device["id"], home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/me/mcp")
class DeviceMcp(MethodView):
    @blp.arguments(McpCatalogSchema)
    def put(self, data):
        device = _device()
        try:
            return devices_svc.replace_mcp_catalog(
                device["id"], data.get("servers") or [], home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/mcp/tools")
class McpTools(MethodView):
    def get(self):
        bot = str(request.args.get("bot") or "").strip()
        if not bot:
            abort(400, message="bot is required")
        try:
            return {"tools": devices_svc.mcp_catalog(bot=bot, home=g.home)}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/mcp/call")
class McpCall(MethodView):
    def post(self):
        from autonomous.services import companion_link as link_svc

        body = request.get_json(silent=True) or {}
        bot = str(body.get("bot") or "").strip()
        server = str(body.get("server") or "").strip()
        tool = str(body.get("tool") or "").strip()
        if not bot or not server or not tool:
            abort(400, message="bot, server and tool are required")
        try:
            text = link_svc.hub_for(g.home).call_mcp(
                server,
                tool,
                body.get("arguments") or {},
                bot=bot,
                companion=str(body.get("companion") or ""),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)
        except Exception as exc:
            abort(502, message=str(exc))
        return {"ok": True, "text": text}


@blp.route("/me/focus")
class DeviceFocus(MethodView):
    def post(self):
        """Tell an open browser tab to show this bot's conversation."""
        _device()
        body = request.get_json(silent=True) or {}
        try:
            return devices_svc.focus_conversation(str(body.get("bot") or ""), home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/notify")
class DeviceNotify(MethodView):
    def post(self):
        """Ask the companion on the user's PC to show a notification."""
        body = request.get_json(silent=True) or {}
        try:
            return devices_svc.notify_user(
                str(body.get("title") or ""),
                str(body.get("body") or body.get("message") or ""),
                str(body.get("bot") or ""),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)
