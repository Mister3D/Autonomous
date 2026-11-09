"""Public inbound webhooks (POST only).

``POST /api/v1/hooks`` with ``Authorization: Bearer <token>``.
"""

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
    if request.is_json:
        body = request.get_json(silent=True)
        return body
    if request.form:
        return request.form.to_dict(flat=True) or None
    raw = (request.get_data(as_text=True) or "").strip()
    return raw or None


def _bearer_token() -> str | None:
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return None
    tok = auth[7:].strip()
    return tok or None


def _fire_hook():
    from autonomous.services.client_ip import client_ip
    from autonomous.services.ratelimit import HOOKS

    token = _bearer_token()
    if not token:
        abort(401, message="Authorization: Bearer <webhook-token> required")

    ip = client_ip(request)
    tok = token[:64]
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


@blp.route("")
class PublicHook(MethodView):
    """Fire with ``Authorization: Bearer <webhook-token>`` (token not in the URL)."""

    @blp.response(200, HookFireResultSchema)
    @blp.doc(security=[])
    def post(self):
        return _fire_hook()
