"""Login / logout / session status (web login page)."""

from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from autonomous import auth as auth_mod
from autonomous.i18n import t
from autonomous.models.schemas import (
    AuthStatusSchema,
    ChangePasswordSchema,
    LoginResultSchema,
    LoginSchema,
    OkSchema,
)

blp = Blueprint("auth", __name__, url_prefix="/auth", description="Authentication")


@blp.route("/status")
class AuthStatus(MethodView):
    @blp.response(200, AuthStatusSchema)
    @blp.doc(security=[])
    def get(self):
        """Whether the mono-user session is authenticated."""
        authed = auth_mod.is_authenticated(g.home)
        must = False
        if authed:
            must = auth_mod.session_needs_password_change(g.home)
        elif auth_mod.password_must_change(g.home):
            must = True
        return {
            "authenticated": authed,
            "password_set": auth_mod.password_is_set(g.home),
            "must_change_password": must,
            "mono_user": True,
        }


@blp.route("/login")
class Login(MethodView):
    @blp.arguments(LoginSchema)
    @blp.response(200, LoginResultSchema)
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
        must = auth_mod.password_must_change(g.home)
        if must:
            auth_mod.consume_initial_password(g.home)
        auth_mod.login_user(must_change=must)
        return {
            "ok": True,
            "message": t("auth.ok"),
            "must_change_password": must,
        }


@blp.route("/password")
class ChangePassword(MethodView):
    @blp.arguments(ChangePasswordSchema)
    @blp.response(200, OkSchema)
    def post(self, data):
        """Replace the login password (required after a generated install password)."""
        from flask import request

        from autonomous.services.client_ip import client_ip
        from autonomous.services.ratelimit import LOGIN

        if not auth_mod.is_authenticated(g.home):
            abort(401, message=t("auth.required"))
        # Same limiter bucket as login — slows online guessing of the current password.
        ip = client_ip(request)
        if not LOGIN.hit(f"login:{ip}", limit=10, window_s=300):
            abort(429, message=t("auth.rate_limited"))
        try:
            auth_mod.change_password(
                g.home,
                data["current_password"],
                data["new_password"],
            )
        except ValueError as exc:
            code = str(exc)
            if code == "invalid":
                abort(401, message=t("auth.invalid"))
            if code == "too_short":
                abort(400, message=t("auth.password_too_short"))
            if code == "unchanged":
                abort(400, message=t("auth.password_unchanged"))
            abort(400, message=t("auth.invalid"))
        return {"ok": True, "message": t("auth.password_changed")}


@blp.route("/logout")
class Logout(MethodView):
    @blp.response(200, OkSchema)
    def post(self):
        """Clear session cookie."""
        auth_mod.logout_user()
        return {"ok": True, "message": t("auth.logout")}
