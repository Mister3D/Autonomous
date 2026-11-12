"""HTTP API for shared household memory."""

from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow import Schema, fields, validate

from autonomous.services import memory as memory_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint("memory", __name__, url_prefix="/memory", description="Shared memory")


class MemoryEntrySchema(Schema):
    id = fields.Str()
    key = fields.Str(required=True)
    label = fields.Str()
    value = fields.Str(required=True)
    tier = fields.Str(validate=validate.OneOf(["core", "browse"]))
    created_at = fields.Str()
    updated_at = fields.Str()


class MemoryEntryCreateSchema(Schema):
    key = fields.Str(required=True)
    label = fields.Str(load_default="")
    value = fields.Str(required=True)
    tier = fields.Str(load_default="browse", validate=validate.OneOf(["core", "browse"]))


class MemoryProposeSchema(Schema):
    bot = fields.Str(required=True)
    action = fields.Str(required=True, validate=validate.OneOf(["set", "delete"]))
    key = fields.Str(required=True)
    label = fields.Str(load_default="")
    value = fields.Str(load_default="")
    tier = fields.Str(load_default="browse", validate=validate.OneOf(["core", "browse"]))
    reason = fields.Str(load_default="")


class MemoryProposalSchema(Schema):
    id = fields.Str()
    bot = fields.Str()
    bot_id = fields.Str()
    action = fields.Str()
    key = fields.Str()
    label = fields.Str()
    value = fields.Str()
    tier = fields.Str()
    reason = fields.Str()
    state = fields.Str()
    message_id = fields.Str(allow_none=True)
    result = fields.Dict()
    created_at = fields.Str()
    resolved_at = fields.Str(allow_none=True)


class MemoryResolveSchema(Schema):
    action = fields.Str(required=True, validate=validate.OneOf(["approve", "deny"]))


class MemoryOkSchema(Schema):
    ok = fields.Bool()


class MemoryProposalCountSchema(Schema):
    count = fields.Int()


def _handle(exc: AutonomousError):
    abort(exc.http_status, message=exc.message, error_code=exc.code)


@blp.route("/entries")
class MemoryEntries(MethodView):
    @blp.response(200, MemoryEntrySchema(many=True))
    def get(self):
        """List shared memory. Optional ?bot= enforces that bot's memory_access."""
        from flask import request

        tier = request.args.get("tier") or None
        bot = request.args.get("bot") or None
        try:
            if bot:
                memory_svc.require_memory_access(bot, home=g.home)
            return memory_svc.list_entries(tier=tier, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.arguments(MemoryEntryCreateSchema)
    @blp.response(201, MemoryEntrySchema)
    def post(self, data):
        """Create or update a memory entry (user / settings)."""
        try:
            return memory_svc.upsert_entry(
                key=data["key"],
                value=data["value"],
                label=data.get("label") or "",
                tier=data.get("tier") or "browse",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/entries/<string:key>")
class MemoryEntryDetail(MethodView):
    @blp.response(200, MemoryEntrySchema)
    def get(self, key):
        from flask import request

        bot = request.args.get("bot") or None
        try:
            if bot:
                memory_svc.require_memory_access(bot, home=g.home)
            return memory_svc.get_entry(key, home=g.home)
        except AutonomousError as exc:
            _handle(exc)

    @blp.response(200, MemoryOkSchema)
    def delete(self, key):
        try:
            memory_svc.delete_entry(key, home=g.home)
            return {"ok": True}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/search")
class MemorySearch(MethodView):
    @blp.response(200, MemoryEntrySchema(many=True))
    def get(self):
        from flask import request

        q = request.args.get("q") or ""
        bot = request.args.get("bot") or None
        try:
            if bot:
                memory_svc.require_memory_access(bot, home=g.home)
            return memory_svc.search_entries(q, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/proposals")
class MemoryProposals(MethodView):
    @blp.arguments(MemoryProposeSchema)
    @blp.response(201, MemoryProposalSchema)
    def post(self, data):
        """Agent proposes a memory change (non-blocking card in chat)."""
        try:
            return memory_svc.propose(
                data["bot"],
                action=data["action"],
                key=data["key"],
                value=data.get("value") or "",
                label=data.get("label") or "",
                tier=data.get("tier") or "browse",
                reason=data.get("reason") or "",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/proposals/count")
class MemoryProposalCount(MethodView):
    @blp.response(200, MemoryProposalCountSchema)
    def get(self):
        """Pending memory proposals. The home hides the first-run line when this is > 0."""
        return {"count": memory_svc.count_proposals(state="pending", home=g.home)}


@blp.route("/proposals/<string:proposal_id>")
class MemoryProposalDetail(MethodView):
    @blp.response(200, MemoryProposalSchema)
    def get(self, proposal_id):
        try:
            return memory_svc.get_proposal(proposal_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/proposals/<string:proposal_id>/resolve")
class MemoryProposalResolve(MethodView):
    @blp.arguments(MemoryResolveSchema)
    @blp.response(200, MemoryProposalSchema)
    def post(self, data, proposal_id):
        try:
            return memory_svc.resolve_proposal(
                proposal_id, action=data["action"], home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)
