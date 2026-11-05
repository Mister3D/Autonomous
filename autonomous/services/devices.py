"""Paired companion devices: device-code approval, revocable token, MCP catalog."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import request

from autonomous.db import get_db
from autonomous.services.errors import Conflict, NotFound, ValidationError
from autonomous.services.events import BUS

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_PAIR_TTL = timedelta(minutes=15)
_PLATFORMS = {"windows", "linux", "macos"}
TOKEN_PREFIX = "adc_"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _user_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise ValidationError("Device name must be 1–64 characters.")
    return name


def _clean_platform(platform: str) -> str:
    platform = (platform or "").strip().lower()
    if platform not in _PLATFORMS:
        raise ValidationError("platform must be windows, linux, or macos.")
    return platform


def start_pairing(name: str, platform: str, *, home: Path | None = None) -> dict[str, Any]:
    name = _clean_name(name)
    platform = _clean_platform(platform)
    pair_id = str(uuid.uuid4())
    poll_secret = secrets.token_urlsafe(24)
    code = _user_code()
    expires = _now() + _PAIR_TTL
    with get_db(home) as conn:
        conn.execute(
            "DELETE FROM device_pairings WHERE status = 'pending' AND expires_at < ?",
            (_iso(_now()),),
        )
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM device_pairings WHERE status = 'pending'"
        ).fetchone()["n"]
        if int(pending) >= 20:
            raise ValidationError("Too many pairing requests. Approve or wait for them to expire.")
        conn.execute(
            """
            INSERT INTO device_pairings (
              id, user_code, poll_hash, name, platform, status, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (pair_id, code, _hash(poll_secret), name, platform, _iso(expires), _iso(_now())),
        )
    BUS.publish(
        "notification",
        {"kind": "device.pairing", "name": name, "code": code, "pair_id": pair_id},
    )
    return {
        "pair_id": pair_id,
        "user_code": code,
        "poll_secret": poll_secret,
        "expires_at": _iso(expires),
    }


def _expire_if_needed(row: Any, conn) -> Any:
    if row["status"] == "pending":
        try:
            exp = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            exp = _now() - timedelta(seconds=1)
        if exp <= _now():
            conn.execute(
                "UPDATE device_pairings SET status = 'expired' WHERE id = ?",
                (row["id"],),
            )
            row = conn.execute(
                "SELECT * FROM device_pairings WHERE id = ?", (row["id"],)
            ).fetchone()
    return row


def poll_pairing(pair_id: str, poll_secret: str, *, home: Path | None = None) -> dict[str, Any]:
    if not pair_id or not poll_secret:
        raise ValidationError("pair_id and poll_secret are required.")
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM device_pairings WHERE id = ?", (pair_id,)
        ).fetchone()
        if row is None or not secrets.compare_digest(row["poll_hash"], _hash(poll_secret)):
            raise NotFound("Pairing not found.")
        row = _expire_if_needed(row, conn)
        token = row["token_once"]
        if token:
            conn.execute(
                "UPDATE device_pairings SET token_once = NULL WHERE id = ?",
                (pair_id,),
            )
        out = {
            "status": row["status"],
            "device_id": row["device_id"],
            "device_token": token,
        }
    return out


def approve_pairing(pair_id: str, *, home: Path | None = None) -> dict[str, Any]:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    device_id = str(uuid.uuid4())
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT * FROM device_pairings WHERE id = ?", (pair_id,)
        ).fetchone()
        if row is None:
            raise NotFound("Pairing not found.")
        row = _expire_if_needed(row, conn)
        if row["status"] != "pending":
            raise ValidationError(f"Pairing is {row['status']}.")
        conn.execute(
            """
            INSERT INTO devices (id, name, platform, token_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (device_id, row["name"], row["platform"], _hash(token), _iso(_now())),
        )
        conn.execute(
            """
            UPDATE device_pairings
            SET status = 'approved', device_id = ?, token_once = ?
            WHERE id = ?
            """,
            (device_id, token, pair_id),
        )
    return {"ok": True, "device_id": device_id}


def deny_pairing(pair_id: str, *, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT status FROM device_pairings WHERE id = ?", (pair_id,)
        ).fetchone()
        if row is None:
            raise NotFound("Pairing not found.")
        if row["status"] == "pending":
            conn.execute(
                "UPDATE device_pairings SET status = 'denied' WHERE id = ?",
                (pair_id,),
            )
    return {"ok": True}


def list_devices(*, home: Path | None = None) -> dict[str, Any]:
    from autonomous.services import companion_link as link_svc

    online = set(link_svc.online_device_ids(home))
    with get_db(home) as conn:
        conn.execute(
            """
            UPDATE device_pairings SET status = 'expired'
            WHERE status = 'pending' AND expires_at < ?
            """,
            (_iso(_now()),),
        )
        pending = conn.execute(
            """
            SELECT id, user_code, name, platform, expires_at, created_at
            FROM device_pairings WHERE status = 'pending'
            ORDER BY created_at
            """
        ).fetchall()
        devices = conn.execute(
            """
            SELECT id, name, platform, created_at, last_seen_at, egress, killswitch, notify
            FROM devices WHERE revoked_at IS NULL
            ORDER BY created_at
            """
        ).fetchall()
    return {
        "pending": [dict(r) for r in pending],
        "devices": [
            {
                **dict(r),
                "online": r["id"] in online,
                "egress": bool(r["egress"]),
                "killswitch": bool(r["killswitch"]),
                "notify": bool(r["notify"]),
            }
            for r in devices
        ],
    }


def revoke_device(device_id: str, *, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        cur = conn.execute(
            "UPDATE devices SET revoked_at = ?, token_hash = NULL WHERE id = ? AND revoked_at IS NULL",
            (_iso(_now()), device_id),
        )
        if cur.rowcount == 0:
            raise NotFound("Device not found.")
        conn.execute("DELETE FROM device_mcp_tools WHERE device_id = ?", (device_id,))
        conn.execute("DELETE FROM bot_mcp_grants WHERE device_id = ?", (device_id,))
        conn.execute(
            """
            UPDATE bots
            SET companion_id = NULL,
                companion_egress = 0,
                companion_killswitch = 0
            WHERE companion_id = ?
            """,
            (device_id,),
        )
    from autonomous.services import companion_link as link_svc

    link_svc.drop_device(device_id, home=home)
    return {"ok": True}


def device_from_token(token: str, *, home: Path | None = None) -> dict[str, Any] | None:
    if not token.startswith(TOKEN_PREFIX):
        return None
    with get_db(home) as conn:
        row = conn.execute(
            """
            SELECT id, name, platform, egress, killswitch
            FROM devices
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (_hash(token),),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "platform": row["platform"],
        "egress": bool(row["egress"]),
        "killswitch": bool(row["killswitch"]),
    }


def device_from_request(home: Path | None = None) -> dict[str, Any] | None:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return device_from_token(auth[7:].strip(), home=home)


def touch(device_id: str, *, home: Path | None = None) -> None:
    with get_db(home) as conn:
        conn.execute(
            "UPDATE devices SET last_seen_at = ? WHERE id = ? AND revoked_at IS NULL",
            (_iso(_now()), device_id),
        )


def update_options(
    device_id: str,
    *,
    egress: bool | None = None,
    killswitch: bool | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    vals: list[Any] = []
    if egress is not None:
        fields.append("egress = ?")
        vals.append(1 if egress else 0)
    if killswitch is not None:
        fields.append("killswitch = ?")
        vals.append(1 if killswitch else 0)
    with get_db(home) as conn:
        if egress:
            conn.execute(
                "UPDATE devices SET egress = 0 WHERE id != ? AND revoked_at IS NULL",
                (device_id,),
            )
        if fields:
            vals.append(device_id)
            conn.execute(
                f"UPDATE devices SET {', '.join(fields)} WHERE id = ? AND revoked_at IS NULL",
                vals,
            )
        row = conn.execute(
            "SELECT id, egress, killswitch FROM devices WHERE id = ? AND revoked_at IS NULL",
            (device_id,),
        ).fetchone()
    if row is None:
        raise NotFound("Device not found.")
    from autonomous.services import companion_egress as egress_svc

    egress_svc.refresh(home)
    return {"ok": True, "egress": bool(row["egress"]), "killswitch": bool(row["killswitch"])}


def replace_mcp_catalog(
    device_id: str, servers: list[dict[str, Any]], *, home: Path | None = None
) -> dict[str, Any]:
    rows: list[tuple] = []
    for server in servers:
        server_name = str(server.get("name") or "").strip()
        if not server_name or len(server_name) > 80:
            raise ValidationError("Each MCP server needs a name.")
        for tool in server.get("tools") or []:
            tool_name = str(tool.get("name") or "").strip()
            if not tool_name:
                continue
            schema = tool.get("input_schema")
            if schema is None:
                schema = tool.get("inputSchema") or {}
            if not isinstance(schema, str):
                schema = json.dumps(schema, ensure_ascii=False)
            rows.append(
                (
                    str(uuid.uuid4()),
                    device_id,
                    server_name[:80],
                    tool_name[:120],
                    str(tool.get("description") or "")[:2000],
                    schema[:20000],
                )
            )
    with get_db(home) as conn:
        if conn.execute(
            "SELECT 1 FROM devices WHERE id = ? AND revoked_at IS NULL", (device_id,)
        ).fetchone() is None:
            raise NotFound("Device not found.")
        conn.execute("DELETE FROM device_mcp_tools WHERE device_id = ?", (device_id,))
        conn.executemany(
            """
            INSERT INTO device_mcp_tools (
              id, device_id, server_name, tool_name, description, input_schema
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return {"ok": True, "tools": len(rows)}


def mcp_servers(*, home: Path | None = None) -> list[dict[str, Any]]:
    """Published MCP servers, one row per companion and server name."""
    from autonomous.services import companion_link as link_svc

    online = set(link_svc.online_device_ids(home))
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT d.id AS device_id, d.name AS device_name, t.server_name
            FROM device_mcp_tools t
            JOIN devices d ON d.id = t.device_id AND d.revoked_at IS NULL
            ORDER BY d.name, t.server_name
            """
        ).fetchall()
    return [
        {
            "device_id": r["device_id"],
            "device_name": r["device_name"],
            "server": r["server_name"],
            "online": r["device_id"] in online,
        }
        for r in rows
    ]


def mcp_catalog(*, bot: str, home: Path | None = None) -> list[dict[str, Any]]:
    """Tools this bot is allowed to call. Empty until a grant exists."""
    from autonomous.services.bots import get_bot
    from autonomous.services import companion_link as link_svc

    get_bot(bot, home=home)
    online = set(link_svc.online_device_ids(home))
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT t.device_id, d.name AS device_name, t.server_name,
                   t.tool_name, t.description, t.input_schema
            FROM device_mcp_tools t
            JOIN devices d ON d.id = t.device_id AND d.revoked_at IS NULL
            JOIN bot_mcp_grants g
              ON g.device_id = t.device_id
             AND g.server_name = t.server_name
             AND g.bot = ?
            ORDER BY d.name, t.server_name, t.tool_name
            """,
            (bot,),
        ).fetchall()
    return [
        {
            "device_id": r["device_id"],
            "device_name": r["device_name"],
            "online": r["device_id"] in online,
            "server": r["server_name"],
            "name": r["tool_name"],
            "description": r["description"],
            "input_schema": r["input_schema"],
        }
        for r in rows
    ]


def list_bot_mcp(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    from autonomous.services.bots import get_bot
    from autonomous.services import companion_link as link_svc

    get_bot(bot, home=home)
    online = set(link_svc.online_device_ids(home))
    servers = mcp_servers(home=home)
    published = {(s["device_id"], s["server"]) for s in servers}
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT g.id, g.device_id, g.server_name, g.created_at,
                   d.name AS device_name
            FROM bot_mcp_grants g
            JOIN devices d ON d.id = g.device_id
            WHERE g.bot = ?
            ORDER BY d.name, g.server_name
            """,
            (bot,),
        ).fetchall()
    grants = [
        {
            "id": r["id"],
            "device_id": r["device_id"],
            "device_name": r["device_name"],
            "server": r["server_name"],
            "online": r["device_id"] in online,
            "available": (r["device_id"], r["server_name"]) in published,
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return {"grants": grants, "servers": servers}


def grant_bot_mcp(bot: str, device_id: str, server: str, *, home: Path | None = None) -> dict[str, Any]:
    from autonomous.services.bots import get_bot
    from autonomous.services.errors import Conflict, NotFound, ValidationError

    get_bot(bot, home=home)
    device_id = str(device_id or "").strip()
    server = str(server or "").strip()
    if not device_id or not server or len(server) > 80:
        raise ValidationError("device_id and server are required.")
    with get_db(home) as conn:
        device = conn.execute(
            """
            SELECT id, name FROM devices
            WHERE id = ? AND revoked_at IS NULL
            """,
            (device_id,),
        ).fetchone()
        if device is None:
            raise NotFound("Device not found.")
        published = conn.execute(
            """
            SELECT 1 FROM device_mcp_tools
            WHERE device_id = ? AND server_name = ?
            LIMIT 1
            """,
            (device_id, server),
        ).fetchone()
        if published is None:
            raise NotFound("This companion has not published that MCP server.")
        existing = conn.execute(
            """
            SELECT id FROM bot_mcp_grants
            WHERE bot = ? AND device_id = ? AND server_name = ?
            """,
            (bot, device_id, server),
        ).fetchone()
        if existing is not None:
            raise Conflict("This bot can already use that MCP server.")
        grant_id = str(uuid.uuid4())
        created = _iso(_now())
        conn.execute(
            """
            INSERT INTO bot_mcp_grants (id, bot, device_id, server_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (grant_id, bot, device_id, server, created),
        )
    listed = list_bot_mcp(bot, home=home)
    grant = next(row for row in listed["grants"] if row["id"] == grant_id)
    return grant


def revoke_bot_mcp(bot: str, grant_id: str, *, home: Path | None = None) -> dict[str, Any]:
    from autonomous.services.bots import get_bot
    from autonomous.services.errors import NotFound

    get_bot(bot, home=home)
    with get_db(home) as conn:
        cur = conn.execute(
            "DELETE FROM bot_mcp_grants WHERE id = ? AND bot = ?",
            (grant_id, bot),
        )
        if cur.rowcount == 0:
            raise NotFound("MCP grant not found.")
    return {"ok": True}


def egress_devices(*, home: Path | None = None) -> list[dict[str, Any]]:
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT id, egress, killswitch FROM devices
            WHERE revoked_at IS NULL AND egress = 1
            """
        ).fetchall()
    return [dict(r) for r in rows]


def focus_conversation(bot: str, *, home: Path | None = None) -> dict[str, Any]:
    """Ask an already open hub tab to show this bot. Does not open a browser."""
    from autonomous.services.bots import validate_name
    from autonomous.services.events import BUS

    name = validate_name(str(bot or "").strip())
    listeners = BUS.listener_count("*")
    if listeners:
        BUS.publish(
            "ui.focus",
            {"path": f"/b/{name}/discussion", "bot": name},
            bot=name,
        )
    return {"ok": True, "open": listeners > 0}


def set_notify(device_id: str, enabled: bool, *, home: Path | None = None) -> dict[str, Any]:
    with get_db(home) as conn:
        cur = conn.execute(
            """
            UPDATE devices SET notify = ?
            WHERE id = ? AND revoked_at IS NULL
            """,
            (1 if enabled else 0, device_id),
        )
        if cur.rowcount == 0:
            raise NotFound("Device not found.")
    return {"ok": True, "notify": bool(enabled)}


def _notify_device_ids(*, home: Path | None = None) -> list[str]:
    with get_db(home) as conn:
        rows = conn.execute(
            """
            SELECT id FROM devices
            WHERE revoked_at IS NULL AND notify = 1
            """
        ).fetchall()
    return [row["id"] for row in rows]


def notify_user(title: str, body: str, bot: str = "", *, home: Path | None = None) -> dict[str, Any]:
    """Push a user-facing alert to the online companions checked for notifications."""
    title = " ".join(str(title or "").split())[:80]
    body = " ".join(str(body or "").split())[:400]
    bot = " ".join(str(bot or "").split())[:40]
    if not title and not body:
        raise ValidationError("Un titre ou un message est requis")
    if bot:
        title = f"{bot} — {title}" if title else bot
    payload = json.dumps(
        {"title": title or "Autonomous", "body": body, "bot": bot},
        ensure_ascii=False,
    ).encode("utf-8")
    wanted = set(_notify_device_ids(home=home))
    if not wanted:
        raise Conflict("Aucun compagnon n'est coché pour recevoir les notifications.")
    from autonomous.services import companion_link as link_svc

    delivered = link_svc.hub_for(home).notify_all(payload, device_ids=wanted)
    if delivered == 0:
        raise Conflict("Aucun compagnon n'est connecté. Le message n'a pas été affiché.")
    return {"ok": True, "delivered": delivered}
