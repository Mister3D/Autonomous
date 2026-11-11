"""Public inbound webhooks (POST only).

``POST /api/v1/hooks`` with ``Authorization: Bearer <token>``.
"""

from __future__ import annotations

import json

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
    """Body of the inbound POST, kept even when it is not valid JSON.

    A mail forwarder often sets ``Content-Type: application/json`` and still
    sends the raw message. Parsing failure must not drop that text: the chat
    bubble is how the user reads it.
    """
    raw = (request.get_data(as_text=True) or "").strip()
    if request.is_json or (raw[:1] in "{["):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
    mimetype = (request.mimetype or "").lower()
    if mimetype.startswith("multipart/") or request.form or request.files:
        data = request.form.to_dict(flat=True)
        for key, storage in request.files.items():
            blob = storage.read()
            try:
                data[key] = blob.decode("utf-8")
            except UnicodeDecodeError:
                data[key] = {
                    "filename": storage.filename or key,
                    "size": len(blob),
                }
        if data:
            return data
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
