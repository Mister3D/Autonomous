"""HTTP API for chat message search (FTS + NL)."""

from __future__ import annotations

from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow import Schema, fields, validate

from autonomous.services import search as search_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint(
    "search",
    __name__,
    url_prefix="/search",
    description="Search chat messages across bots",
)


class SearchHitSchema(Schema):
    message_id = fields.Str()
    bot = fields.Str()
    bot_label = fields.Str()
    role = fields.Str()
    created_at = fields.Str()
    snippet = fields.Str()
    score = fields.Float()
    mode = fields.Str()


class SearchResultSchema(Schema):
    query = fields.Str()
    mode = fields.Str()
    count = fields.Int()
    hits = fields.List(fields.Nested(SearchHitSchema))


class SearchNlBodySchema(Schema):
    q = fields.Str(required=True)
    bot = fields.Str(load_default=None)
    limit = fields.Int(load_default=20, validate=validate.Range(min=1, max=50))


def _handle(exc: AutonomousError):
    abort(exc.http_status, message=exc.message, error_code=exc.code)


@blp.route("/messages")
class SearchMessages(MethodView):
    @blp.response(200, SearchResultSchema)
    def get(self):
        """Lexical / auto search. Query: q, bot?, limit?, mode=auto|lexical|nl."""
        q = (request.args.get("q") or "").strip()
        bot = (request.args.get("bot") or "").strip() or None
        mode = (request.args.get("mode") or "auto").strip()
        try:
            limit = int(request.args.get("limit") or 20)
        except ValueError:
            limit = 20
        try:
            return search_svc.search_messages(
                q, bot=bot, limit=limit, mode=mode, home=g.home
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/messages/nl")
class SearchMessagesNl(MethodView):
    @blp.arguments(SearchNlBodySchema)
    @blp.response(200, SearchResultSchema)
    def post(self, body: dict):
        """Natural-language search (keyword OR + optional LLM rerank)."""
        try:
            hits = search_svc.search_nl(
                body["q"],
                bot=body.get("bot") or None,
                limit=int(body.get("limit") or 20),
                home=g.home,
            )
            return {
                "query": body["q"],
                "mode": hits[0]["mode"] if hits else "nl",
                "count": len(hits),
                "hits": hits,
            }
        except AutonomousError as exc:
            _handle(exc)
