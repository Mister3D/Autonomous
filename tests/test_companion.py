"""Companion pairing, device token scope, and the tunnel mux."""

from __future__ import annotations

import socket
import threading

from autonomous.services.companion_link import CompanionSession
from autonomous.services.companion_proto import (
    OP_CLOSE,
    OP_DATA,
    OP_MCP_CALL,
    OP_MCP_RESULT,
    OP_OPEN,
    OP_OPEN_OK,
    decode_frame,
    encode_frame,
)
from autonomous.services.companion_egress import build_commands, plan


def _recvexact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        assert chunk
        buf += chunk
    return buf


def test_frame_roundtrip():
    raw = encode_frame(OP_OPEN, 7, b"example.com\n443")
    assert decode_frame(raw) == (OP_OPEN, 7, b"example.com\n443")


def test_frame_rejects_oversize():
    from autonomous.services.companion_proto import MAX_PAYLOAD

    try:
        encode_frame(OP_DATA, 1, b"x" * (MAX_PAYLOAD + 1))
    except ValueError:
        return
    raise AssertionError("oversize frame was accepted")


def test_pairing_approve_and_device_token_is_not_admin(app, client, auth_client, pairing_on):
    started = client.post(
        "/api/v1/devices/pair",
        json={"name": "Bureau", "platform": "windows"},
    )
    assert started.status_code == 200, started.data
    body = started.get_json()
    assert body["user_code"].count("-") == 1

    listed = auth_client.get("/api/v1/devices/")
    assert listed.status_code == 200
    assert listed.get_json()["pending"][0]["user_code"] == body["user_code"]

    approved = auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve")
    assert approved.status_code == 200

    polled = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    )
    assert polled.status_code == 200
    token = polled.get_json()["device_token"]
    assert token.startswith("adc_")

    again = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    )
    assert again.get_json()["device_token"] is None

    fresh = app.test_client()
    bots = fresh.get("/api/v1/bots", headers={"Authorization": f"Bearer {token}"})
    assert bots.status_code == 401

    opts = fresh.patch(
        "/api/v1/devices/me",
        json={"egress": True, "killswitch": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert opts.status_code == 200
    assert opts.get_json()["egress"] is True

    device_id = polled.get_json()["device_id"]
    gone = auth_client.delete(f"/api/v1/devices/{device_id}")
    assert gone.status_code == 200
    denied = fresh.patch(
        "/api/v1/devices/me",
        json={"egress": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 401


def test_focus_reuses_an_open_hub_tab(app, client, auth_client, pairing_on):
    from autonomous.services.events import BUS

    started = client.post(
        "/api/v1/devices/pair",
        json={"name": "Bureau-focus", "platform": "windows"},
    )
    assert started.status_code == 200, started.data
    body = started.get_json()
    assert auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve").status_code == 200
    polled = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    )
    token = polled.get_json()["device_token"]
    fresh = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        closed = fresh.post("/api/v1/devices/me/focus", json={"bot": "fnac"}, headers=headers)
        assert closed.status_code == 200, closed.data
        assert closed.get_json()["open"] is False
        bad = fresh.post("/api/v1/devices/me/focus", json={"bot": "../x"}, headers=headers)
        assert bad.status_code == 400
        q = BUS.subscribe("*")
        try:
            opened = fresh.post("/api/v1/devices/me/focus", json={"bot": "fnac"}, headers=headers)
            assert opened.status_code == 200, opened.data
            assert opened.get_json()["open"] is True
            event = q.get(timeout=1)
            assert event.name == "ui.focus"
            assert event.data["path"] == "/b/fnac/discussion"
        finally:
            BUS.unsubscribe("*", q)
    finally:
        auth_client.delete(f"/api/v1/devices/{polled.get_json()['device_id']}")


def test_socks_echo_and_mcp_call():
    session_box: dict[str, CompanionSession] = {}

    def send(op, stream_id, payload):
        session = session_box["s"]
        if op == OP_OPEN:
            session.handle_frame(OP_OPEN_OK, stream_id, b"")
        elif op == OP_DATA:
            session.handle_frame(OP_DATA, stream_id, b"echo:" + payload)
        elif op == OP_CLOSE:
            session.handle_frame(OP_CLOSE, stream_id, b"")
        elif op == OP_MCP_CALL:
            session.handle_frame(
                OP_MCP_RESULT, stream_id, b'{"ok": true, "text": "from-pc"}'
            )

    session = CompanionSession("dev", send)
    session_box["s"] = session
    session.start_listeners()
    try:
        conn = socket.create_connection(("127.0.0.1", session.socks_port), timeout=5)
        conn.sendall(b"\x05\x01\x00")
        assert _recvexact(conn, 2) == b"\x05\x00"
        host = b"example.com"
        conn.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + b"\x01\xbb")
        reply = _recvexact(conn, 10)
        assert reply[1] == 0
        conn.sendall(b"ping")
        assert _recvexact(conn, 9) == b"echo:ping"
        conn.close()
        assert session.call_mcp("files", "list", {})["text"] == "from-pc"
    finally:
        session.close()


def _pair(client, auth_client, name: str) -> tuple[str, str]:
    started = client.post(
        "/api/v1/devices/pair",
        json={"name": name, "platform": "windows"},
    )
    assert started.status_code == 200, started.data
    body = started.get_json()
    assert auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve").status_code == 200
    polled = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    )
    assert polled.status_code == 200, polled.data
    return polled.get_json()["device_id"], polled.get_json()["device_token"]


def _publish(app, token: str, servers: list[dict]) -> None:
    fresh = app.test_client()
    res = fresh.put(
        "/api/v1/devices/me/mcp",
        json={"servers": servers},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.data


def test_bot_mcp_grant_limits_calls(app, client, auth_client, home, pairing_on):
    from autonomous.services.companion_link import CompanionSession, hub_for

    created = auth_client.post("/api/v1/bots", json={"name": "Mcpbot"})
    assert created.status_code == 201, created.data
    bot = created.get_json()["name"]
    device_a, token_a = _pair(client, auth_client, "Bureau-a")
    device_b, token_b = _pair(client, auth_client, "Bureau-b")
    _publish(
        app,
        token_a,
        [
            {"name": "vectorcraft", "tools": [{"name": "export", "description": "png"}]},
            {"name": "shell", "tools": [{"name": "exec", "description": "run"}]},
        ],
    )
    _publish(
        app,
        token_b,
        [{"name": "vectorcraft", "tools": [{"name": "export", "description": "png"}]}],
    )

    def answering(label: str) -> CompanionSession:
        def send(op, stream_id, payload):
            if op == OP_MCP_CALL:
                session.handle_frame(
                    OP_MCP_RESULT, stream_id, f'{{"ok": true, "text": "{label}"}}'.encode()
                )

        session = CompanionSession(label, send)
        return session

    session_a = answering("from-a")
    session_b = answering("from-b")
    hub = hub_for(home)
    hub.attach(device_a, session_a)
    hub.attach(device_b, session_b)
    try:
        missing_bot = auth_client.get("/api/v1/devices/mcp/tools")
        assert missing_bot.status_code == 400

        before = auth_client.get(f"/api/v1/devices/mcp/tools?bot={bot}")
        assert before.status_code == 200
        assert before.get_json()["tools"] == []

        denied = auth_client.post(
            "/api/v1/devices/mcp/call",
            json={"bot": bot, "server": "shell", "tool": "exec"},
        )
        assert denied.status_code == 502
        assert "not allowed" in denied.get_json()["message"]

        listed = auth_client.get(f"/api/v1/bots/{bot}/mcp")
        assert listed.status_code == 200
        servers = {(row["device_id"], row["server"]) for row in listed.get_json()["servers"]}
        assert (device_a, "shell") in servers
        assert (device_b, "vectorcraft") in servers

        grant = auth_client.post(
            f"/api/v1/bots/{bot}/mcp",
            json={"device_id": device_a, "server": "shell"},
        )
        assert grant.status_code == 200, grant.data
        grant_id = grant.get_json()["id"]
        assert grant.get_json()["device_name"] == "Bureau-a"

        tools = auth_client.get(f"/api/v1/devices/mcp/tools?bot={bot}")
        names = {(row["server"], row["name"], row["device_name"]) for row in tools.get_json()["tools"]}
        assert names == {("shell", "exec", "Bureau-a")}

        called = auth_client.post(
            "/api/v1/devices/mcp/call",
            json={"bot": bot, "server": "shell", "tool": "exec"},
        )
        assert called.status_code == 200, called.data
        assert called.get_json()["text"] == "from-a"

        other = auth_client.post(
            f"/api/v1/bots/{bot}/mcp",
            json={"device_id": device_b, "server": "vectorcraft"},
        )
        assert other.status_code == 200
        both = auth_client.post(
            f"/api/v1/bots/{bot}/mcp",
            json={"device_id": device_a, "server": "vectorcraft"},
        )
        assert both.status_code == 200, both.data
        ambiguous = auth_client.post(
            "/api/v1/devices/mcp/call",
            json={"bot": bot, "server": "vectorcraft", "tool": "export"},
        )
        assert ambiguous.status_code == 502
        assert "Several companions" in ambiguous.get_json()["message"]
        picked = auth_client.post(
            "/api/v1/devices/mcp/call",
            json={
                "bot": bot,
                "server": "vectorcraft",
                "tool": "export",
                "companion": "Bureau-b",
            },
        )
        assert picked.status_code == 200, picked.data
        assert picked.get_json()["text"] == "from-b"

        gone = auth_client.delete(f"/api/v1/bots/{bot}/mcp/{grant_id}")
        assert gone.status_code == 200
        after = auth_client.get(f"/api/v1/devices/mcp/tools?bot={bot}")
        assert all(row["server"] != "shell" for row in after.get_json()["tools"])
    finally:
        hub.detach(device_a, session_a)
        hub.detach(device_b, session_b)
        auth_client.delete(f"/api/v1/devices/{device_a}")
        auth_client.delete(f"/api/v1/devices/{device_b}")
        auth_client.delete(f"/api/v1/bots/{bot}")


_PNG_1X1 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_mcp_call_saves_screenshot(app, client, auth_client, home, pairing_on):
    import base64
    import json
    from urllib.parse import unquote

    from autonomous.services.agent import _mcp_image_markdowns
    from autonomous.services.companion_link import CompanionSession, hub_for
    from autonomous.services import files as files_svc

    created = auth_client.post("/api/v1/bots", json={"name": "Shotbot"})
    assert created.status_code == 201, created.data
    bot = created.get_json()["name"]
    device_id, token = _pair(client, auth_client, "Atelier")
    _publish(
        app,
        token,
        [{"name": "Windows-MCP", "tools": [{"name": "Screenshot", "description": "screen"}]}],
    )
    grant = auth_client.post(
        f"/api/v1/bots/{bot}/mcp",
        json={"device_id": device_id, "server": "Windows-MCP"},
    )
    assert grant.status_code == 200, grant.data
    payload = json.dumps(
        {
            "ok": True,
            "text": "Screenshot Size: (1,1)",
            "images": [
                {"mime": "image/png", "data": _PNG_1X1},
                {"mime": "image/png", "data": "not-base64"},
            ],
        }
    ).encode()

    def send(op, stream_id, _payload):
        if op == OP_MCP_CALL:
            session.handle_frame(OP_MCP_RESULT, stream_id, payload)

    session = CompanionSession("shot", send)
    hub = hub_for(home)
    hub.attach(device_id, session)
    try:
        called = auth_client.post(
            "/api/v1/devices/mcp/call",
            json={"bot": bot, "server": "Windows-MCP", "tool": "Screenshot"},
        )
        assert called.status_code == 200, called.data
        data = called.get_json()
        assert data["text"] == "Screenshot Size: (1,1)"
        assert len(data["images"]) == 1
        image = data["images"][0]
        assert image["data"] == _PNG_1X1
        assert image["markdown"].startswith("![capture](")
        assert "/files/raw?path=" in image["markdown"]
        rel = unquote(image["url"].split("path=", 1)[1])
        assert files_svc.resolve(bot, rel, home=home).read_bytes() == base64.b64decode(_PNG_1X1)
        assert _mcp_image_markdowns({"details": {"images_md": [image["markdown"], "nope"]}}) == [
            image["markdown"]
        ]
    finally:
        hub.detach(device_id, session)
        auth_client.delete(f"/api/v1/devices/{device_id}")
        auth_client.delete(f"/api/v1/bots/{bot}")


def _insert_device(home, device_id, *, notify=1, name="Bureau"):
    from autonomous.db import get_db

    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO devices (id, name, platform, token_hash, created_at, notify)
            VALUES (?, ?, 'linux', ?, '2026-01-01T00:00:00+00:00', ?)
            """,
            (device_id, name, device_id, 1 if notify else 0),
        )


def test_notify_reaches_the_online_companion(auth_client, home):
    import json

    from autonomous.services.companion_link import hub_for
    from autonomous.services.companion_proto import OP_NOTIFY

    frames = []
    session = CompanionSession(
        "desk", lambda op, _sid, payload: frames.append((op, payload))
    )
    hub = hub_for(home)
    _insert_device(home, "desk")
    hub.attach("desk", session)
    try:
        missing = auth_client.post("/api/v1/devices/notify", json={"title": "", "body": ""})
        assert missing.status_code == 400
        sent = auth_client.post(
            "/api/v1/devices/notify",
            json={"title": "Mail", "body": "La facture est arrivée", "bot": "fnac"},
        )
        assert sent.status_code == 200, sent.data
        assert sent.get_json()["delivered"] == 1
        assert frames[0][0] == OP_NOTIFY
        payload = json.loads(frames[0][1])
        assert payload["title"] == "fnac — Mail"
        assert "facture" in payload["body"]
        assert payload["bot"] == "fnac"
    finally:
        hub.detach("desk", session)

    offline = auth_client.post(
        "/api/v1/devices/notify",
        json={"title": "Mail", "body": "trop tard"},
    )
    assert offline.status_code == 409
    cmds = build_commands(
        rules=[
            {"ip": "172.17.0.2", "mode": "redirect", "tcp_port": 41000, "dns_port": 41001},
            {"ip": "172.17.0.3", "mode": "kill", "tcp_port": 0, "dns_port": 0},
        ],
        subnets=["172.17.0.0/16"],
        filter_hook="DOCKER-USER",
    )
    flat = [" ".join(c) for c in cmds]
    assert any("REDIRECT --to-ports 41000" in line and "172.17.0.2" in line for line in flat)
    assert any("udp --dport 53" in line and "172.17.0.2" in line for line in flat)
    assert any(line.endswith("-s 172.17.0.3 -j DROP") for line in flat)
    assert not any("REDIRECT" in line and "172.17.0.3" in line for line in flat)
    assert any(line.startswith("iptables -D DOCKER-USER") for line in flat)
    off = build_commands(rules=[], subnets=[], filter_hook="DOCKER-USER")
    assert all("REDIRECT" not in " ".join(c) for c in off)


def test_notify_only_checked_companions(auth_client, home):
    from autonomous.services.companion_link import hub_for

    frames_on = []
    frames_off = []
    session_on = CompanionSession(
        "on", lambda op, _sid, payload: frames_on.append((op, payload))
    )
    session_off = CompanionSession(
        "off", lambda op, _sid, payload: frames_off.append((op, payload))
    )
    hub = hub_for(home)
    _insert_device(home, "on", notify=1, name="Salon")
    _insert_device(home, "off", notify=0, name="Bureau")
    hub.attach("on", session_on)
    hub.attach("off", session_off)
    try:
        sent = auth_client.post(
            "/api/v1/devices/notify",
            json={"title": "Test", "body": "bonjour"},
        )
        assert sent.status_code == 200, sent.data
        assert sent.get_json()["delivered"] == 1
        assert len(frames_on) == 1
        assert frames_off == []

        patched = auth_client.patch("/api/v1/devices/on", json={"notify": False})
        assert patched.status_code == 200, patched.data
        assert patched.get_json()["notify"] is False
        listed = auth_client.get("/api/v1/devices/")
        row = next(item for item in listed.get_json()["devices"] if item["id"] == "on")
        assert row["notify"] is False

        frames_on.clear()
        again = auth_client.post(
            "/api/v1/devices/notify",
            json={"title": "Test", "body": "encore"},
        )
        assert again.status_code == 409
        assert "coché" in again.get_json()["message"]
        assert frames_on == []
        assert frames_off == []

        missing = auth_client.patch("/api/v1/devices/missing", json={"notify": True})
        assert missing.status_code == 404
    finally:
        hub.detach("on", session_on)
        hub.detach("off", session_off)


def test_authorized_peer_ips_only_egress_bots_for_device(auth_client, client, home, monkeypatch, pairing_on):
    from autonomous.services import bots as bots_svc
    from autonomous.services import companion_link as link

    def _pair(name: str) -> str:
        started = client.post(
            "/api/v1/devices/pair",
            json={"name": name, "platform": "linux"},
        )
        body = started.get_json()
        assert auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve").status_code == 200
        polled = client.post(
            "/api/v1/devices/pair-poll",
            json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
        )
        return polled.get_json()["device_id"]

    pc_a = _pair("PcA")
    pc_b = _pair("PcB")
    bots_svc.create_bot("alpha", home=home)
    bots_svc.create_bot("beta", home=home)
    bots_svc.create_bot("gamma", home=home)
    bots_svc.patch_bot(
        "alpha",
        {"companion_id": pc_a, "companion_egress": True},
        home=home,
    )
    bots_svc.patch_bot(
        "beta",
        {"companion_id": pc_b, "companion_egress": True},
        home=home,
    )
    bots_svc.patch_bot(
        "gamma",
        {"companion_id": pc_a, "companion_egress": False},
        home=home,
    )
    monkeypatch.setattr(
        "autonomous.services.companion_egress.bot_endpoints",
        lambda: (
            {"alpha": "10.0.0.2", "beta": "10.0.0.3", "gamma": "10.0.0.4"},
            ["10.0.0.0/24"],
        ),
    )
    link._PEER_CACHE.clear()
    assert link._authorized_peer_ips(pc_a, home=home, force=True) == {"10.0.0.2"}
    assert link._authorized_peer_ips(pc_b, home=home, force=True) == {"10.0.0.3"}
    assert link._authorized_peer_ips("missing", home=home, force=True) == set()


def test_plan_is_per_bot():
    rules = plan(
        [
            {"name": "alpha", "companion_id": "pc-a", "egress": True, "killswitch": True},
            {"name": "beta", "companion_id": "pc-b", "egress": True, "killswitch": False},
            {"name": "gamma", "companion_id": "pc-a", "egress": False, "killswitch": True},
        ],
        ips_by_bot={"alpha": "10.0.0.2", "beta": "10.0.0.3", "gamma": "10.0.0.4"},
        sessions={"pc-a": (41000, 41001), "pc-b": None},
    )
    by_ip = {rule["ip"]: rule["mode"] for rule in rules}
    assert by_ip == {"10.0.0.2": "redirect"}
    assert rules[0]["tcp_port"] == 41000

    offline = plan(
        [{"name": "beta", "companion_id": "pc-b", "egress": True, "killswitch": True}],
        ips_by_bot={"beta": "10.0.0.3"},
        sessions={"pc-b": None},
    )
    assert offline == [{"ip": "10.0.0.3", "mode": "kill", "tcp_port": 0, "dns_port": 0}]


def test_bot_companion_route_is_per_bot(auth_client, client, pairing_on):
    started = client.post(
        "/api/v1/devices/pair",
        json={"name": "PcSalon", "platform": "windows"},
    )
    body = started.get_json()
    assert auth_client.post(f"/api/v1/devices/pair/{body['pair_id']}/approve").status_code == 200
    polled = client.post(
        "/api/v1/devices/pair-poll",
        json={"pair_id": body["pair_id"], "poll_secret": body["poll_secret"]},
    )
    device_id = polled.get_json()["device_id"]
    created = auth_client.post("/api/v1/bots", json={"name": "Routebot"})
    assert created.status_code == 201, created.data
    name = created.get_json()["name"]
    try:
        missing = auth_client.patch(
            f"/api/v1/bots/{name}",
            json={"companion_id": "nope"},
        )
        assert missing.status_code == 404

        linked = auth_client.patch(
            f"/api/v1/bots/{name}",
            json={"companion_id": device_id, "companion_egress": True, "companion_killswitch": True},
        )
        assert linked.status_code == 200, linked.data
        bot = linked.get_json()
        assert bot["companion_id"] == device_id
        assert bot["companion_name"] == "PcSalon"
        assert bot["companion_egress"] is True
        assert bot["companion_killswitch"] is True

        direct = auth_client.patch(
            f"/api/v1/bots/{name}",
            json={"companion_egress": False},
        )
        assert direct.get_json()["companion_killswitch"] is False
        assert direct.get_json()["companion_id"] == device_id

        cleared = auth_client.patch(f"/api/v1/bots/{name}", json={"companion_id": None})
        body = cleared.get_json()
        assert body["companion_id"] is None
        assert body["companion_egress"] is False
    finally:
        auth_client.delete(f"/api/v1/devices/{device_id}")
        auth_client.delete(f"/api/v1/bots/{name}")
