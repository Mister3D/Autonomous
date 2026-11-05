"""HTTP API for generic user approval cards."""

from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow import Schema, fields, validate

from autonomous.services import approvals as approval_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint(
    "approvals", __name__, url_prefix="/approvals", description="User approvals"
)


class ApprovalCreateSchema(Schema):
    bot = fields.Str(required=True)
    prompt = fields.Str(required=True)
    title = fields.Str(load_default="")


class ApprovalSchema(Schema):
    id = fields.Str()
    bot = fields.Str()
    bot_id = fields.Str()
    title = fields.Str()
    prompt = fields.Str()
    state = fields.Str()
    message_id = fields.Str(allow_none=True)
    result = fields.Dict()
    created_at = fields.Str()
    resolved_at = fields.Str(allow_none=True)


class ApprovalResolveSchema(Schema):
    action = fields.Str(required=True, validate=validate.OneOf(["approve", "deny"]))


def _handle(exc: AutonomousError):
    abort(exc.http_status, message=exc.message, error_code=exc.code)


@blp.route("/requests")
class ApprovalRequests(MethodView):
    @blp.arguments(ApprovalCreateSchema)
    @blp.response(201, ApprovalSchema)
    def post(self, data):
        """Agent asks the user to Accept / Refuse (blocking poll on client)."""
        try:
            return approval_svc.create_request(
                data["bot"],
                prompt=data["prompt"],
                title=data.get("title") or "",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/requests/<string:request_id>")
class ApprovalRequestDetail(MethodView):
    @blp.response(200, ApprovalSchema)
    def get(self, request_id):
        try:
            return approval_svc.get_request(request_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/requests/<string:request_id>/resolve")
class ApprovalResolve(MethodView):
    @blp.arguments(ApprovalResolveSchema)
    @blp.response(200, ApprovalSchema)
    def post(self, data, request_id):
        try:
            return approval_svc.resolve_request(
                request_id, action=data["action"], home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)
