"""Health + settings + Pi status + global SSE."""

from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from autonomous import __version__
from autonomous.models.schemas import HealthSchema, PiModelSchema, PiStatusSchema, SettingsSchema
from autonomous.services import settings as settings_svc
from autonomous.services.cronutil import user_clock
from autonomous.services.events import sse_response
from autonomous.services import pi_status as pi_status_svc

blp = Blueprint("system", __name__, url_prefix="", description="System")


class ClockSchema(Schema):
    timezone = fields.Str(required=True)
    utc_offset = fields.Str(required=True)
    now = fields.Str(required=True, metadata={"description": "Current wall time YYYY-MM-DD HH:MM"})


@blp.route("/clock")
class Clock(MethodView):
    @blp.response(200, ClockSchema)
    def get(self):
        """User timezone for cron input and the Events inspector (host clock if unset)."""
        return user_clock(home=g.home)


@blp.route("/health")
class Health(MethodView):
    @blp.response(200, HealthSchema)
    @blp.doc(security=[])
    def get(self):
        """Liveness probe (no auth)."""
        return {"ok": True, "version": __version__}


@blp.route("/pi/status")
class PiStatus(MethodView):
    @blp.response(200, PiStatusSchema)
    def get(self):
        """Pi install + readiness (models configured)."""
        return pi_status_svc.status()


@blp.route("/pi/models")
class PiModels(MethodView):
    @blp.response(200, PiModelSchema(many=True))
    def get(self):
        """List models available to the host Pi install."""
        return pi_status_svc.list_models()


@blp.route("/settings")
class Settings(MethodView):
    @blp.response(200, SettingsSchema)
    def get(self):
        """Get global settings."""
        return settings_svc.get_all(home=g.home)

    @blp.arguments(SettingsSchema)
    @blp.response(200, SettingsSchema)
    def put(self, data):
        """Update global settings (partial flat map)."""
        # Marshmallow may use data_key; accept raw JSON keys too
        raw = {k: v for k, v in data.items() if v is not None}
        # Also accept dotted keys from request
        from flask import request

        body = request.get_json(silent=True) or {}
        for key, value in body.items():
            raw[key] = value
        return settings_svc.set_many(raw, home=g.home)


@blp.route("/events")
class GlobalEvents(MethodView):
    @blp.doc(
        summary="Global SSE stream (all bots / notifications)",
        description=(
            "Server-Sent Events for cross-tab live updates. "
            "Events: ping, bot.*, message.*, desk.*, job.*, terminal.*, notification."
        ),
        produces=["text/event-stream"],
    )
    def get(self):
        """Subscribe to instance-wide events (multi-tab sync)."""
        return sse_response("*")
