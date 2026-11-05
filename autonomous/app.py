"""Flask application factory — OpenAPI via flask-smorest."""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_smorest import Api

from autonomous import __version__, auth as auth_mod
from autonomous.db import migrate
from autonomous.paths import default_home, ensure_home
from autonomous.services import settings as settings_svc
from autonomous.services.errors import AutonomousError

_OPEN_EXACT = {
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/status",
    "/api/v1/devices/pair",
    "/api/v1/devices/pair-poll",
    # Webhook fire with Authorization: Bearer <webhook-token> (no session).
    "/api/v1/hooks",
}
# Reachable with a session that still must change a generated password.
_PASSWORD_CHANGE_EXACT = {
    "/api/v1/auth/status",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/password",
    "/api/v1/health",
}
# OpenAPI /docs require a session (or Bearer) — not listed here.
_OPEN_PREFIXES = (
    "/static/",
)


def create_app(home: Path | None = None) -> Flask:
    home = ensure_home(home or default_home())
    migrate(home)
    settings_svc.ensure_defaults(home)
    try:
        from autonomous.services import search as search_svc

        search_svc.ensure_fts(home)
    except Exception:
        pass

    app = Flask(
        __name__,
        static_folder=str(Path(__file__).resolve().parent / "static"),
        static_url_path="/static",
    )
    testing = bool(os.environ.get("AUTONOMOUS_TESTING")) or os.environ.get("PYTEST_CURRENT_TEST")
    allow_insecure = os.environ.get("AUTONOMOUS_ALLOW_INSECURE", "").strip() in ("1", "true", "yes")
    api_token = auth_mod.read_token(home)
    if not api_token and not (testing or allow_insecure):
        raise RuntimeError(
            "No API token — run `autonomous init` before serve "
            "(or set AUTONOMOUS_ALLOW_INSECURE=1 for a throwaway local session)."
        )
    # Session cookie signing key — must NOT equal the admin Bearer (`data/token`).
    secret = (os.environ.get("AUTONOMOUS_SECRET") or "").strip() or None
    if not secret:
        if testing or allow_insecure:
            secret = auth_mod.read_session_secret(home) or "dev-insecure"
        else:
            secret = auth_mod.ensure_session_secret(home)
    # Guard: refuse to run if an operator pointed AUTONOMOUS_SECRET at the API token.
    if api_token and secret == api_token:
        raise RuntimeError(
            "AUTONOMOUS_SECRET must not equal the API Bearer (data/token). "
            "Unset AUTONOMOUS_SECRET or use a distinct value; session key lives in data/secret."
        )
    cookie_secure = os.environ.get("AUTONOMOUS_COOKIE_SECURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not cookie_secure:
        public = (os.environ.get("AUTONOMOUS_PUBLIC_URL") or "").strip().lower()
        if public.startswith("https://"):
            cookie_secure = True
    app.config.update(
        AUTONOMOUS_HOME=str(home),
        SECRET_KEY=secret,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=cookie_secure,
        API_TITLE="Autonomous API",
        API_VERSION="v1",
        OPENAPI_VERSION="3.0.3",
        OPENAPI_URL_PREFIX="/api",
        OPENAPI_SWAGGER_UI_PATH="/docs",
        OPENAPI_SWAGGER_UI_URL="https://cdn.jsdelivr.net/npm/swagger-ui-dist/",
        OPENAPI_REDOC_PATH="/redoc",
        OPENAPI_REDOC_URL="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
        API_SPEC_OPTIONS={
            "info": {
                "description": (
                    "Mono-user bot hub. Authenticate with the web login page "
                    "(session cookie) or `Authorization: Bearer <admin-token>` "
                    "(from `autonomous init`). Pi agent sessions use a separate "
                    "bot-scoped `abt_…` Bearer."
                ),
            },
            "components": {
                "securitySchemes": {
                    "BearerAuth": {"type": "http", "scheme": "bearer"},
                }
            },
            "security": [{"BearerAuth": []}],
        },
    )

    CORS(
        app,
        supports_credentials=True,
        origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8787",
            "http://localhost:8787",
        ],
    )

    api = Api(app)

    from autonomous.api.auth_routes import blp as auth_blp
    from autonomous.api.bots import blp as bots_blp
    from autonomous.api.hooks import blp as hooks_blp
    from autonomous.api.jobs import blp as jobs_blp
    from autonomous.api.system import blp as system_blp
    from autonomous.api.vault_routes import blp as vault_blp
    from autonomous.api.memory_routes import blp as memory_blp
    from autonomous.api.approval_routes import blp as approval_blp
    from autonomous.api.clarify_routes import blp as clarify_blp
    from autonomous.api.search_routes import blp as search_blp
    from autonomous.api.devices import blp as devices_blp
    from autonomous.api.companion_routes import blp as companion_blp
    from autonomous.api.setup_routes import blp as setup_blp

    for blp in (
        system_blp,
        auth_blp,
        bots_blp,
        jobs_blp,
        vault_blp,
        memory_blp,
        approval_blp,
        clarify_blp,
        search_blp,
        hooks_blp,
        devices_blp,
        companion_blp,
        setup_blp,
    ):
        # Ensure all live under /api/v1
        prefix = blp.url_prefix or ""
        if not prefix.startswith("/api/v1"):
            blp.url_prefix = "/api/v1" + prefix
        api.register_blueprint(blp)

    @app.before_request
    def _bind_home():
        g.home = Path(app.config["AUTONOMOUS_HOME"])

    @app.before_request
    def _auth_gate():
        if request.method == "OPTIONS":
            return None
        path = request.path
        if path in _OPEN_EXACT or any(path.startswith(p) for p in _OPEN_PREFIXES):
            return None
        # SPA assets / pages are public; API data is protected
        if not path.startswith("/api/") and not path.startswith("/novnc/"):
            return None
        if path.startswith("/api/v1/devices/me"):
            from autonomous.services import devices as devices_svc

            device = devices_svc.device_from_request(g.home)
            if device:
                g.device = device
                return None
            return jsonify({"error": "Authentication required", "code": "auth_required"}), 401

        # Bot-scoped Bearer (Pi) — not full admin access.
        bot_name = auth_mod.bot_from_bearer(g.home)
        if bot_name:
            g.auth_bot = bot_name
            denied = auth_mod.bot_token_access_error(bot_name, g.home)
            if denied:
                body, status = denied
                return jsonify(body), status
            return None
        g.auth_bot = None

        if not auth_mod.is_authenticated(g.home):
            return jsonify({"error": "Authentication required", "code": "auth_required"}), 401
        # Generated install password: session may only hit auth/password until replaced.
        # Admin / bot Bearers are not gated (CLI and Pi keep working).
        if auth_mod.session_needs_password_change(g.home) and path not in _PASSWORD_CHANGE_EXACT:
            return jsonify(
                {
                    "error": "Password change required",
                    "code": "password_change_required",
                }
            ), 403
        return None

    @app.errorhandler(AutonomousError)
    def _domain_error(exc: AutonomousError):
        return jsonify({"error": exc.message, "code": exc.code}), exc.http_status

    @app.route("/novnc/<string:bot>/", defaults={"rest": ""})
    @app.route("/novnc/<string:bot>/<path:rest>")
    def novnc_proxy(bot: str, rest: str):
        from autonomous.services import desk as desk_svc

        info = desk_svc.novnc_info(bot, home=g.home)
        port = info.get("vnc_port")
        if not port:
            return jsonify({"error": "Desktop not available"}), 404
        # Default document: minimal viewer without the gray control bar
        if not rest or rest == "vnc.html":
            rest = "vnc_lite.html"
        target = f"http://127.0.0.1:{port}/{rest}"
        qs = request.query_string.decode() if request.query_string else ""
        if qs:
            target = f"{target}?{qs}"
        # Retry briefly: after reboot/create, websockify can reset the first connections.
        last_exc: Exception | None = None
        data = b""
        ctype = "application/octet-stream"
        for attempt in range(8):
            try:
                req = urllib.request.Request(target, method="GET")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                    ctype = resp.headers.get("Content-Type", "application/octet-stream")
                last_exc = None
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
                last_exc = exc
                time.sleep(0.35 * (attempt + 1))
        if last_exc is not None:
            return jsonify({"error": str(last_exc), "code": "novnc_unavailable"}), 502
        # Strip noVNC chrome. Do NOT override canvas CSS — that breaks mouse input.
        if "text/html" in (ctype or "") or rest.endswith(".html"):
            inject = (
                b"<style>"
                b"#top_bar,#status,#sendCtrlAltDelButton,"
                b"#noVNC_control_bar_anchor,#noVNC_control_bar,"
                b"#noVNC_status,#noVNC_control_bar_handle,"
                b".noVNC_status_bar{display:none!important;height:0!important;"
                b"overflow:hidden!important;padding:0!important;margin:0!important}"
                b"html,body{margin:0!important;padding:0!important;"
                b"background:#e8e8ed!important;height:100%!important;"
                b"width:100%!important;overflow:hidden!important}"
                b"#screen{flex:1!important;width:100%!important;height:100%!important;"
                b"margin:0!important;padding:0!important;background:#e8e8ed!important;"
                b"overflow:hidden!important}"
                b"</style>"
            )
            if b"</head>" in data:
                data = data.replace(b"</head>", inject + b"</head>", 1)
            else:
                data = inject + data
            # Coerce query booleans: view_only=0 must NOT be truthy (JS string "0" is).
            data = data.replace(
                b"rfb.viewOnly = readQueryVariable('view_only', false);",
                b"rfb.viewOnly = ['1','true','yes'].includes(String("
                b"readQueryVariable('view_only', '0')).toLowerCase());",
                1,
            )
            # scale=true → fit iframe (mouse coords remapped). Never resizeSession
            # (remote stays 1920×1200 for grounding / screenshots).
            # Clipboard bridge: OS ↔ VNC (vnc_lite has no clipboard UI).
            data = data.replace(
                b"rfb.scaleViewport = readQueryVariable('scale', false);",
                b"rfb.scaleViewport = ['1','true','yes'].includes(String("
                b"readQueryVariable('scale', 'true')).toLowerCase());\n"
                b"        rfb.resizeSession = false;\n"
                b"        rfb.clipViewport = false;\n"
                b"        rfb.focusOnClick = true;\n"
                b"""
        // --- Autonomous: clipboard OS <-> VNC ---
        function _autoWriteLocalClipboard(text) {
            if (text == null || text === '') return;
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).catch(function () {
                    _autoFallbackCopy(text);
                });
            } else {
                _autoFallbackCopy(text);
            }
        }
        function _autoFallbackCopy(text) {
            try {
                var ta = document.createElement('textarea');
                ta.value = text;
                ta.setAttribute('readonly', '');
                ta.style.cssText = 'position:fixed;left:-9999px;top:0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            } catch (err) { /* ignore */ }
        }
        function _autoSendCtrlV() {
            // XK_Control_L=0xffe3, XK_v=0x0076
            rfb.sendKey(0xffe3, 'ControlLeft', true);
            rfb.sendKey(0x0076, 'KeyV', true);
            rfb.sendKey(0x0076, 'KeyV', false);
            rfb.sendKey(0xffe3, 'ControlLeft', false);
        }
        rfb.addEventListener('clipboard', function (e) {
            _autoWriteLocalClipboard(e.detail && e.detail.text);
        });
        // Parent SPA: connection state (status bar is hidden above).
        function _autoPostNovnc(state, extra) {
            try {
                var bot = (location.pathname.match(/\\/novnc\\/([^\\/]+)/) || [])[1] || '';
                parent.postMessage(Object.assign({
                    source: 'autonomous-novnc',
                    bot: bot,
                    state: state
                }, extra || {}), '*');
            } catch (err) { /* ignore */ }
        }
        rfb.addEventListener('connect', function () {
            _autoPostNovnc('connected');
        });
        rfb.addEventListener('disconnect', function (e) {
            _autoPostNovnc('disconnected', {
                clean: !!(e.detail && e.detail.clean)
            });
        });
        // Block noVNC from forwarding Ctrl+V with a stale remote clipboard;
        // the paste handler updates ClientCutText then synthesizes Ctrl+V.
        window.addEventListener('keydown', function (e) {
            if (!rfb || rfb.viewOnly) return;
            if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
            if (e.key !== 'v' && e.key !== 'V') return;
            e.stopPropagation();
        }, true);
        window.addEventListener('paste', function (e) {
            if (!rfb || rfb.viewOnly) return;
            var text = (e.clipboardData && e.clipboardData.getData('text/plain')) || '';
            if (!text) return;
            e.preventDefault();
            e.stopPropagation();
            rfb.clipboardPasteFrom(text);
            setTimeout(_autoSendCtrlV, 40);
        }, true);
""",
                1,
            )
        return Response(data, content_type=ctype)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def spa(path: str):
        if path.startswith("api/") or path.startswith("novnc/"):
            return jsonify({"error": "Not found"}), 404
        static = Path(app.static_folder or "")
        if path:
            candidate = static / path
            if candidate.is_file():
                resp = send_from_directory(static, path)
                # Hashed Vite assets can be cached; HTML/entry must revalidate.
                if path.startswith("assets/"):
                    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                else:
                    resp.headers["Cache-Control"] = "no-cache"
                return resp
        index = static / "index.html"
        if index.exists():
            resp = send_from_directory(static, "index.html")
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            return resp
        return jsonify(
            {
                "ok": True,
                "version": __version__,
                "message": "UI not built yet — open /api/docs",
                "docs": "/api/docs",
                "openapi": "/api/openapi.json",
            }
        )

    app.extensions["autonomous_home"] = home
    return app
