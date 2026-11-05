"""HTTP API for structured clarify cards (choices / short text)."""

from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow import Schema, fields

from autonomous.services import clarifies as clarify_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint(
    "clarifies",
    __name__,
    url_prefix="/clarifies",
    description="Structured questions to the user",
)


class ClarifyCreateSchema(Schema):
    bot = fields.Str(required=True)
    prompt = fields.Str(required=True)
    title = fields.Str(load_default="")
    choices = fields.List(fields.Str(), load_default=None, allow_none=True)
    allow_text = fields.Bool(load_default=None, allow_none=True)


class ClarifySchema(Schema):
    id = fields.Str()
    bot = fields.Str()
    bot_id = fields.Str()
    title = fields.Str()
    prompt = fields.Str()
    choices = fields.List(fields.Str())
    allow_text = fields.Bool()
    state = fields.Str()
    message_id = fields.Str(allow_none=True)
    result = fields.Dict()
    created_at = fields.Str()
    resolved_at = fields.Str(allow_none=True)


class ClarifyResolveSchema(Schema):
    choice = fields.Str(load_default="")
    text = fields.Str(load_default="")


def _handle(exc: AutonomousError):
    abort(exc.http_status, message=exc.message, error_code=exc.code)


@blp.route("/requests")
class ClarifyRequests(MethodView):
    @blp.arguments(ClarifyCreateSchema)
    @blp.response(201, ClarifySchema)
    def post(self, data):
        """Agent asks a structured question (blocking poll on the client)."""
        try:
            return clarify_svc.create_request(
                data["bot"],
                prompt=data["prompt"],
                title=data.get("title") or "",
                choices=data.get("choices"),
                allow_text=data.get("allow_text"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/requests/<string:request_id>")
class ClarifyRequestDetail(MethodView):
    @blp.response(200, ClarifySchema)
    def get(self, request_id):
        try:
            return clarify_svc.get_request(request_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/requests/<string:request_id>/resolve")
class ClarifyResolve(MethodView):
    @blp.arguments(ClarifyResolveSchema)
    @blp.response(200, ClarifySchema)
    def post(self, data, request_id):
        """Answer with a choice label or a short text."""
        try:
            return clarify_svc.resolve_request(
                request_id,
                choice=data.get("choice") or "",
                text=data.get("text") or "",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)
