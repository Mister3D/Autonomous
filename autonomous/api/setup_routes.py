"""First-run setup: readiness checks, web config (LLM, grounding), install jobs."""

from __future__ import annotations

from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from autonomous.services import setup as setup_svc
from autonomous.services import setup_config as cfg_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint("setup", __name__, url_prefix="/setup", description="First-run setup")


def _handle(exc: AutonomousError):
    abort(exc.http_status, message=exc.message, error_code=exc.code)


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@blp.route("/status")
class SetupStatus(MethodView):
    def get(self):
        """Checks (required / optional) and the overall ``ready`` flag (cached 10 s; ?force=1)."""
        force = request.args.get("force") in ("1", "true", "yes")
        return setup_svc.status(g.home, force=force)


@blp.route("/jobs/<string:kind>")
class SetupJob(MethodView):
    def post(self, kind):
        """Start a whitelisted install job (pi_install, desk_image, companion, docker_install)."""
        try:
            return setup_svc.start_job(kind, g.home), 202
        except AutonomousError as exc:
            _handle(exc)


@blp.route("/llm")
class SetupLlm(MethodView):
    def get(self):
        """Pi providers from models.json (API keys masked)."""
        try:
            return cfg_svc.llm_view()
        except AutonomousError as exc:
            _handle(exc)

    def put(self):
        """Save one provider (empty api_key = keep current)."""
        try:
            out = cfg_svc.save_llm(_body())
        except AutonomousError as exc:
            _handle(exc)
        setup_svc.invalidate()
        return out


@blp.route("/llm/test")
class SetupLlmTest(MethodView):
    def post(self):
        """GET <base_url>/models with the typed or stored key → model ids."""
        return cfg_svc.test_llm(_body())


@blp.route("/llm/models")
class SetupLlmModels(MethodView):
    def post(self):
        """{base_url, api_key?} → {models: [ids]} (stored key when empty or masked)."""
        status, out = cfg_svc.llm_models(_body())
        return out, status


@blp.route("/grounding")
class SetupGrounding(MethodView):
    def get(self):
        """Grounding (UI-TARS) config (token masked, env values read-only)."""
        return cfg_svc.grounding_view(g.home)

    def put(self):
        """Save grounder.env (empty token = keep current)."""
        try:
            out = cfg_svc.save_grounding(_body(), g.home)
        except AutonomousError as exc:
            _handle(exc)
        setup_svc.invalidate()
        return out


@blp.route("/grounding/test")
class SetupGroundingTest(MethodView):
    def post(self):
        """Reach UI-TARS (/models)."""
        return cfg_svc.test_grounding(_body(), g.home)


@blp.route("/grounding/models")
class SetupGroundingModels(MethodView):
    def post(self):
        """{kind: grounder, url?, token?} → {models: [ids]}."""
        status, out = cfg_svc.grounding_models(_body(), g.home)
        return out, status
