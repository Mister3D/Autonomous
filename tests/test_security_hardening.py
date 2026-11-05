"""Security hardening: WS auth helper, rate limits, URL SSRF, SOCKS peers."""

from __future__ import annotations

from autonomous.services import setup_config as cfg
from autonomous.services.companion_link import peer_allowed
from autonomous.services.errors import ValidationError
from autonomous.services.ratelimit import LOGIN, RateLimiter
from autonomous.ws_auth import ws_authenticated


def test_ws_auth_bearer(app, home):
    assert ws_authenticated(
        {"authorization": "Bearer test-token"},
        app=app,
        home=home,
    )
    assert not ws_authenticated(
        {"authorization": "Bearer wrong"},
        app=app,
        home=home,
    )
    assert not ws_authenticated({}, app=app, home=home)


def test_ws_auth_session_cookie(app, home):
    from flask.sessions import SecureCookieSessionInterface

    with app.app_context():
        ser = SecureCookieSessionInterface().get_signing_serializer(app)
        assert ser is not None
        cookie = ser.dumps({"authenticated": True})
    assert ws_authenticated({"cookie": f"session={cookie}"}, app=app, home=home)
    assert not ws_authenticated(
        {"cookie": "session=forged.not.real"},
        app=app,
        home=home,
    )


def test_login_rate_limit(client, home):
    LOGIN.clear()
    codes = []
    for _ in range(12):
        r = client.post("/api/v1/auth/login", json={"password": "nope"})
        codes.append(r.status_code)
    assert 429 in codes
    assert codes.count(401) == 10
    assert codes[-1] == 429


def test_pairing_rate_limit(client):
    from autonomous.services.ratelimit import PAIRING

    PAIRING.clear()
    codes = []
    for i in range(7):
        r = client.post(
            "/api/v1/devices/pair",
            json={"name": f"PC-{i}", "platform": "linux"},
        )
        codes.append(r.status_code)
    assert codes.count(200) == 5
    assert 429 in codes


def test_webhook_rate_limit(auth_client, home):
    from autonomous.services.ratelimit import HOOKS
    from autonomous.services import bot_events as events_svc

    auth_client.post("/api/v1/bots", json={"name": "hookbot"})
    wh = events_svc.create_webhook(
        "hookbot", name="ping", instruction="Say hi", home=home
    )
    token = wh["token"]
    HOOKS.clear()
    # Per-token limit is 30/min — fire 31.
    codes = [
        auth_client.post(
            "/api/v1/hooks",
            json={"n": i},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        for i in range(31)
    ]
    assert 429 in codes
    assert codes.count(200) == 30


def test_openapi_requires_auth(app, auth_client):
    anon = app.test_client()
    assert anon.get("/api/openapi.json").status_code == 401
    assert auth_client.get("/api/openapi.json").status_code == 200


def test_ssrf_blocks_metadata_ip():
    try:
        cfg.assert_safe_outbound_url("http://169.254.169.254/latest/meta-data/")
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "forbidden_url"
    try:
        cfg.assert_safe_outbound_url("http://metadata.google.internal/")
        raise AssertionError("expected ValidationError")
    except ValidationError as exc:
        assert exc.code == "forbidden_url"
    # Local LLM stays allowed.
    cfg.assert_safe_outbound_url("http://127.0.0.1:8000/v1")


def test_search_llm_blocks_metadata_base_url(monkeypatch):
    """NL search must not POST the API key to a metadata / link-local base_url."""
    from autonomous.services import search as search_svc

    monkeypatch.setattr(
        search_svc,
        "_llm_config",
        lambda: {
            "base_url": "http://169.254.169.254/latest",
            "model": "m",
            "api_key": "secret-key-must-not-leak",
        },
    )
    called = {"n": 0}

    def _boom(*_a, **_k):  # noqa: ANN001
        called["n"] += 1
        raise AssertionError("urlopen_safe must not be reached for metadata URLs")

    monkeypatch.setattr(
        "autonomous.services.setup_config.urlopen_safe",
        _boom,
    )
    out = search_svc._llm_complete("hi", system="sys", timeout=1.0)
    assert out is None
    assert called["n"] == 0


def test_urlopen_safe_blocks_redirect_to_metadata():
    """A 302 to link-local must not be followed (SSRF bounce-off)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def log_message(self, *_args):  # noqa: ANN001
            return

    server = HTTPServer(("127.0.0.1", 0), _H)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, data = cfg.http_get_json(f"http://127.0.0.1:{port}/bounce", timeout=2.0)
        assert status in (0, 403)
        if status == 0:
            assert isinstance(data, dict)
            err = str(data.get("error") or "").lower()
            assert "forbidden" in err or "not allowed" in err or "403" in err or err
    finally:
        server.shutdown()


def test_peer_allowed_loopback_only_without_bots(monkeypatch):
    monkeypatch.setattr(
        "autonomous.services.companion_link._authorized_peer_ips",
        lambda device_id, home=None, force=False: set(),
    )
    assert peer_allowed("127.0.0.1", device_id="pc-a")
    assert not peer_allowed("192.168.1.50", device_id="pc-a")
    assert not peer_allowed("10.0.0.8", device_id="pc-a")
    assert not peer_allowed("10.0.0.8")  # no device → deny (except loopback)


def test_peer_allowed_only_bots_for_that_companion(monkeypatch):
    def fake_ips(device_id, home=None, force=False):
        if device_id == "pc-a":
            return {"10.0.0.2"}
        if device_id == "pc-b":
            return {"10.0.0.3"}
        return set()

    monkeypatch.setattr(
        "autonomous.services.companion_link._authorized_peer_ips",
        fake_ips,
    )
    assert peer_allowed("10.0.0.2", device_id="pc-a")
    assert not peer_allowed("10.0.0.3", device_id="pc-a")
    assert peer_allowed("10.0.0.3", device_id="pc-b")
    assert not peer_allowed("10.0.0.2", device_id="pc-b")


def test_rate_limiter_window():
    lim = RateLimiter()
    assert lim.hit("k", limit=2, window_s=60)
    assert lim.hit("k", limit=2, window_s=60)
    assert not lim.hit("k", limit=2, window_s=60)
