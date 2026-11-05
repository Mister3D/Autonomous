"""Login / logout / session status (web login page)."""

from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from autonomous import auth as auth_mod
from autonomous.i18n import t
from autonomous.models.schemas import AuthStatusSchema, LoginSchema, OkSchema

blp = Blueprint("auth", __name__, url_prefix="/auth", description="Authentication")


@blp.route("/status")
class AuthStatus(MethodView):
    @blp.response(200, AuthStatusSchema)
    @blp.doc(security=[])
    def get(self):
        """Whether the mono-user session is authenticated."""
        return {
            "authenticated": auth_mod.is_authenticated(g.home),
            "password_set": auth_mod.password_is_set(g.home),
            "mono_user": True,
        }


@blp.route("/login")
class Login(MethodView):
    @blp.arguments(LoginSchema)
    @blp.response(200, OkSchema)
    @blp.doc(security=[])
    def post(self, data):
        """Log in with the instance password (web UI)."""
        from flask import request

        from autonomous.services.client_ip import client_ip
        from autonomous.services.ratelimit import LOGIN

        # 10 tries / 5 min per client IP (mono-user; slows offline hash brute-force).
        ip = client_ip(request)
        if not LOGIN.hit(f"login:{ip}", limit=10, window_s=300):
            abort(429, message=t("auth.rate_limited"))
        if not auth_mod.verify_password(g.home, data["password"]):
            abort(401, message=t("auth.invalid"))
        auth_mod.login_user()
        return {"ok": True, "message": t("auth.ok")}


@blp.route("/logout")
class Logout(MethodView):
    @blp.response(200, OkSchema)
    def post(self):
        """Clear session cookie."""
        auth_mod.logout_user()
        return {"ok": True, "message": t("auth.logout")}
