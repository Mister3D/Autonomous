"""Public inbound webhooks (token in URL — no session)."""

from __future__ import annotations

from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from autonomous.models.schemas import HookFireResultSchema
from autonomous.services import bot_events as events_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint("hooks", __name__, url_prefix="/hooks", description="Public webhooks")


def _handle(exc: Exception):
    if isinstance(exc, AutonomousError):
        abort(exc.http_status, message=exc.message)
    raise exc


def _payload_from_request():
    if request.method == "GET":
        args = request.args.to_dict(flat=True)
        return args or None
    if request.is_json:
        body = request.get_json(silent=True)
        return body
    if request.form:
        return request.form.to_dict(flat=True) or None
    raw = (request.get_data(as_text=True) or "").strip()
    return raw or None


@blp.route("/<string:token>")
class PublicHook(MethodView):
    @blp.response(200, HookFireResultSchema)
    @blp.doc(security=[])
    def get(self, token):
        """Trigger webhook via GET (query → payload)."""
        return self._fire(token)

    @blp.response(200, HookFireResultSchema)
    @blp.doc(security=[])
    def post(self, token):
        """Trigger webhook via POST (JSON/form/body → payload)."""
        return self._fire(token)

    def _fire(self, token: str):
        from autonomous.services.ratelimit import HOOKS

        # Public URL secret: throttle per token and per client IP.
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()
        tok = (token or "")[:64]
        if not HOOKS.hit(f"hook:tok:{tok}", limit=30, window_s=60):
            abort(429, message="Webhook rate limit exceeded")
        if not HOOKS.hit(f"hook:ip:{ip}", limit=60, window_s=60):
            abort(429, message="Webhook rate limit exceeded")
        try:
            msg = events_svc.fire_webhook(
                token,
                payload=_payload_from_request(),
                home=g.home,
            )
            meta = msg.get("meta") or {}
            return {
                "ok": True,
                "message_id": msg["id"],
                "bot": msg["bot"],
                "queued": bool(meta.get("queued")),
            }
        except AutonomousError as exc:
            _handle(exc)
