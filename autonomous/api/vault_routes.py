"""Global vault HTTP API."""

from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow import Schema, fields as mf, validate

from autonomous.services import vault as vault_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint("vault", __name__, url_prefix="/vault", description="Global vault")


class VaultFieldSchema(Schema):
    id = mf.Str(required=True)
    label = mf.Str(required=True)
    secret = mf.Bool(load_default=True)
    required = mf.Bool(load_default=True)


class VaultEntrySchema(Schema):
    id = mf.Str(required=True)
    label = mf.Str(required=True)
    kind = mf.Str(required=True)
    origin = mf.Str()
    username = mf.Str()
    fields = mf.List(mf.Nested(VaultFieldSchema))
    public = mf.Dict()
    has_secret = mf.Bool()
    created_at = mf.Str()
    updated_at = mf.Str()


class VaultEntryCreateSchema(Schema):
    label = mf.Str(required=True, validate=validate.Length(min=1))
    kind = mf.Str(
        load_default="secret",
        validate=validate.OneOf(("secret", "login", "credential")),
    )
    secret = mf.Str(required=True, validate=validate.Length(min=1), load_only=True)
    origin = mf.Str(load_default="")
    username = mf.Str(load_default="")


class VaultGrantSchema(Schema):
    bot = mf.Str(required=True)
    entry_id = mf.Str(required=True)
    granted_at = mf.Str()


class VaultGrantCreateSchema(Schema):
    bot = mf.Str(required=True)
    entry_id = mf.Str(required=True)


class VaultRequestSchema(Schema):
    id = mf.Str(required=True)
    bot = mf.Str(required=True)
    kind = mf.Str(required=True)
    entry_id = mf.Str(allow_none=True)
    label = mf.Str()
    origin = mf.Str()
    reason = mf.Str()
    fields = mf.List(mf.Nested(VaultFieldSchema))
    state = mf.Str()
    message_id = mf.Str(allow_none=True)
    result = mf.Dict()
    created_at = mf.Str()
    resolved_at = mf.Str(allow_none=True)


class VaultRequestCreateSchema(Schema):
    bot = mf.Str(required=True)
    kind = mf.Str(
        required=True,
        validate=validate.OneOf(("access", "login", "secret", "credential")),
    )
    reason = mf.Str(load_default="")
    label = mf.Str(load_default="")
    origin = mf.Str(load_default="")
    entry_id = mf.Str(load_default=None, allow_none=True)
    fields = mf.List(mf.Nested(VaultFieldSchema), load_default=None)


class VaultResolveSchema(Schema):
    action = mf.Str(required=True, validate=validate.OneOf(("approve", "deny")))
    secret = mf.Str(load_default=None, allow_none=True, load_only=True)
    username = mf.Str(load_default=None, allow_none=True)
    label = mf.Str(load_default=None, allow_none=True)
    origin = mf.Str(load_default=None, allow_none=True)
    entry_id = mf.Str(load_default=None, allow_none=True)
    values = mf.Dict(keys=mf.Str(), values=mf.Str(), load_default=None, load_only=True)


class VaultOkSchema(Schema):
    ok = mf.Bool(required=True)


def _handle(exc: Exception):
    if isinstance(exc, AutonomousError):
        abort(exc.http_status, message=exc.message)
    raise exc


@blp.route("/entries")
class VaultEntries(MethodView):
    @blp.response(200, VaultEntrySchema(many=True))
    def get(self):
        """List vault entries (metadata only — no secret values).

        Query ``bot`` → only entries granted to that bot.
        """
        from flask import request

        bot = request.args.get("bot") or None
        if bot:
            return vault_svc.list_entries_for_bot(bot, home=g.home)
        return vault_svc.list_entries(home=g.home)

    @blp.arguments(VaultEntryCreateSchema)
    @blp.response(201, VaultEntrySchema)
    def post(self, data):
        """Create a vault entry (secret stored encrypted)."""
        try:
            return vault_svc.create_entry(
                label=data["label"],
                kind=data.get("kind") or "secret",
                secret=data["secret"],
                origin=data.get("origin") or "",
                username=data.get("username") or "",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/catalog")
class VaultCatalog(MethodView):
    @blp.response(200, VaultEntrySchema(many=True))
    def get(self):
        """Global catalog (labels only) so a bot can request access by id."""
        return vault_svc.catalog_entries(home=g.home)


@blp.route("/entries/<string:entry_id>")
class VaultEntryDetail(MethodView):
    @blp.response(200, VaultOkSchema)
    def delete(self, entry_id):
        try:
            vault_svc.delete_entry(entry_id, home=g.home)
            return {"ok": True}
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/grants")
class VaultGrants(MethodView):
    @blp.response(200, VaultGrantSchema(many=True))
    def get(self):
        bot = None
        from flask import request

        bot = request.args.get("bot") or None
        return vault_svc.list_grants(bot=bot, home=g.home)

    @blp.arguments(VaultGrantCreateSchema)
    @blp.response(201, VaultGrantSchema)
    def post(self, data):
        try:
            return vault_svc.grant(data["bot"], data["entry_id"], home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/grants/<string:bot>/<string:entry_id>")
class VaultGrantDetail(MethodView):
    @blp.response(200, VaultOkSchema)
    def delete(self, bot, entry_id):
        vault_svc.revoke(bot, entry_id, home=g.home)
        return {"ok": True}


@blp.route("/requests")
class VaultRequests(MethodView):
    @blp.arguments(VaultRequestCreateSchema)
    @blp.response(201, VaultRequestSchema)
    def post(self, data):
        """Create a pending vault request (shows a form card in chat)."""
        try:
            return vault_svc.create_request(
                data["bot"],
                kind=data["kind"],
                reason=data.get("reason") or "",
                label=data.get("label") or "",
                origin=data.get("origin") or "",
                entry_id=data.get("entry_id"),
                fields=data.get("fields"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/requests/<string:req_id>")
class VaultRequestDetail(MethodView):
    @blp.response(200, VaultRequestSchema)
    def get(self, req_id):
        try:
            return vault_svc.get_request(req_id, home=g.home)
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/requests/<string:req_id>/resolve")
class VaultRequestResolve(MethodView):
    @blp.arguments(VaultResolveSchema)
    @blp.response(200, VaultRequestSchema)
    def post(self, data, req_id):
        """Approve/deny a vault request. Secrets in the body never go to the LLM."""
        try:
            return vault_svc.resolve_request(
                req_id,
                action=data["action"],
                secret=data.get("secret"),
                username=data.get("username"),
                label=data.get("label"),
                origin=data.get("origin"),
                entry_id=data.get("entry_id"),
                values=data.get("values"),
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)


class VaultUserSecretReportSchema(Schema):
    bot = mf.Str(required=True)
    reason = mf.Str(load_default="")


class VaultUserSecretReportResultSchema(Schema):
    ok = mf.Bool()
    scrubbed_message_id = mf.Str(allow_none=True)
    alert_id = mf.Str(allow_none=True)
    aborted = mf.Bool()
    message = mf.Str()


@blp.route("/report-user-secret")
class VaultReportUserSecret(MethodView):
    @blp.arguments(VaultUserSecretReportSchema)
    @blp.response(200, VaultUserSecretReportResultSchema)
    def post(self, data):
        """Agent: the user pasted a secret — scrub message, warn, abort (never send the secret)."""
        try:
            return vault_svc.report_user_secret_disclosure(
                data["bot"],
                reason=data.get("reason") or "",
                home=g.home,
            )
        except AutonomousError as exc:
            _handle(exc)
