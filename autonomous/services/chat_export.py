"""Export a bot discussion to PDF — same visual language as the Discussion pane."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomous.pdf_text import build_discussion_pdf
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc

# Same idea as the UI: no noisy internal tool cards in the export.
_HIDDEN_TOOLS = frozenset(
    {
        "bot_list",
        "bot_tell",
        "bot_ask",
        "bot_delegate",
        "schedule_list",
        "schedule_create",
        "schedule_update",
        "schedule_delete",
        "webhook_list",
        "webhook_create",
        "webhook_update",
        "webhook_delete",
        "files_share_image",
        "files_attach",
        "memory_propose",
        "memory_list",
        "memory_get",
        "memory_search",
        "ask_approval",
        "ask_clarify",
        "report_user_secret",
        "chat_search",
        "react",
    }
)

_MD_STRIP = re.compile(r"[*_`~#>]+")

_CARD_LABELS = {
    "vault_request": "Demande coffre",
    "memory_proposal": "Proposition mémoire",
    "approval_request": "Approbation",
    "clarify_request": "Question",
    "desk_request": "Bureau",
    "agent_interrupted": "Interrompu",
    "screenshot": "Capture d’écran",
    "grounding": "Repérage écran",
    "schedule": "Rappel / cron",
    "webhook": "Webhook",
    "botmail": "Courrier bot",
    "guard": "Garde-fou",
    "secret_provider_alert": "Alerte secret",
}


def list_all_messages(bot: str, *, home: Path | None = None) -> list[dict[str, Any]]:
    """Oldest → newest, full conversation (pages through list_messages)."""
    bots_svc.get_bot(bot, home=home)
    out: list[dict[str, Any]] = []
    before: str | None = None
    while True:
        page = chat_svc.list_messages(bot, before=before, limit=200, home=home)
        if not page:
            break
        out = page + out
        before = page[0]["created_at"]
        if len(page) < 200:
            break
    return out


def _plain(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _MD_STRIP.sub("", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[image]", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def _parse_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    except ValueError:
        return None


def _clock(iso: str | None) -> str:
    dt = _parse_dt(iso)
    return dt.strftime("%H:%M") if dt else ""


def _day_key(iso: str | None) -> str:
    dt = _parse_dt(iso)
    return dt.strftime("%Y-%m-%d") if dt else ""


def _day_label(iso: str | None, *, now: datetime | None = None) -> str:
    dt = _parse_dt(iso)
    if not dt:
        return ""
    now = now or datetime.now().astimezone()
    time = dt.strftime("%H:%M")
    d0 = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    d1 = datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo)
    diff = (d0 - d1).days
    if diff == 0:
        return f"Aujourd'hui {time}"
    if diff == 1:
        return f"Hier {time}"
    return dt.strftime("%d/%m/%Y") + f" {time}"


def _tool_name(msg: dict[str, Any]) -> str | None:
    meta = msg.get("meta") or {}
    if meta.get("kind") != "tool":
        return None
    name = str(meta.get("tool_name") or "tool")
    if name in _HIDDEN_TOOLS:
        return None
    return name


def _row_status_label(status: str) -> str:
    if status == "done":
        return "Terminé"
    if status == "error":
        return "Erreur"
    return "En cours"


def _tools_tone_and_badge(entries: list[dict[str, Any]]) -> tuple[str, str]:
    """Match ToolGroup ``groupStatus`` + ``statusSummary`` (FR, badge uppercased in PDF)."""
    tools = [
        m
        for m in entries
        if (m.get("meta") or {}).get("kind") == "tool" and _tool_name(m)
    ]
    statuses = [(m.get("meta") or {}).get("status") or "running" for m in tools]
    if any(s == "running" for s in statuses):
        return "running", "En cours"
    errors = sum(1 for s in statuses if s == "error")
    if errors:
        return "error", f"{errors} erreur(s)"
    return "done", "Terminé"


def _tools_title(count: int) -> str:
    if count <= 1:
        return "1 outil"
    return f"{count} outils"


def transcript_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build Discussion-like blocks: day / bubble / tools / card."""
    blocks: list[dict[str, Any]] = []
    tool_buf: list[dict[str, Any]] = []
    last_day = ""
    now = datetime.now().astimezone()

    def flush_tools() -> None:
        nonlocal tool_buf
        if not tool_buf:
            return
        rows: list[dict[str, Any]] = []
        for m in tool_buf:
            n = _tool_name(m)
            if not n:
                continue
            st = str((m.get("meta") or {}).get("status") or "running")
            rows.append(
                {
                    "name": n,
                    "status": _row_status_label(st),
                    "state": st,
                    "time": _clock(m.get("created_at")),
                }
            )
        if not rows:
            tool_buf = []
            return
        tone, badge = _tools_tone_and_badge(tool_buf)
        blocks.append(
            {
                "kind": "tools",
                "title": _tools_title(len(rows)),
                "badge": badge,
                "tone": tone,
                "rows": rows,
                "time": _clock(tool_buf[0].get("created_at")),
            }
        )
        tool_buf = []

    def maybe_day(msg: dict[str, Any]) -> None:
        nonlocal last_day
        key = _day_key(msg.get("created_at"))
        if key and key != last_day:
            blocks.append(
                {"kind": "day", "label": _day_label(msg.get("created_at"), now=now)}
            )
            last_day = key

    for msg in messages:
        role = msg.get("role") or ""
        meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
        kind = meta.get("kind")

        if role == "hidden_prompt":
            continue
        if meta.get("streaming") and not _plain(msg.get("content") or ""):
            continue

        if role == "event" and _tool_name(msg) is not None:
            maybe_day(msg)
            tool_buf.append(msg)
            continue
        # Screenshots folded into tool runs in the UI — skip standalone noise.
        if role == "event" and kind in ("screenshot", "grounding"):
            continue

        if role == "event":
            flush_tools()
            maybe_day(msg)
            label = _CARD_LABELS.get(str(kind or ""), "Événement")
            blocks.append({"kind": "card", "label": label})
            continue

        if role not in ("user", "assistant", "system"):
            continue

        body = _plain(msg.get("content") or "")
        atts = msg.get("attachments") or []
        if not body and not atts:
            continue

        flush_tools()
        maybe_day(msg)
        if atts and not body:
            n = len(atts)
            body = f"[{n} pièce jointe{'s' if n > 1 else ''}]"
        elif atts:
            n = len(atts)
            body = body + f"\n[{n} pièce jointe{'s' if n > 1 else ''}]"

        bubble_role = "user" if role == "user" else "assistant"
        if role == "system":
            # System notices as centered cards feel closer to the UI than a bubble.
            blocks.append({"kind": "card", "label": body[:120]})
            continue

        blocks.append(
            {
                "kind": "bubble",
                "role": bubble_role,
                "text": body,
                "time": _clock(msg.get("created_at")),
            }
        )

    flush_tools()
    return blocks


def transcript_lines(messages: list[dict[str, Any]]) -> list[tuple[str, dict]]:
    """Flat text view (tests / debugging)."""
    lines: list[tuple[str, dict]] = []
    for b in transcript_blocks(messages):
        kind = b.get("kind")
        if kind == "day":
            lines.append((b.get("label") or "", {"bold": True, "size": 9}))
        elif kind == "bubble":
            role = "Vous" if b.get("role") == "user" else "Assistant"
            lines.append((role, {"bold": True, "size": 11}))
            lines.append((b.get("text") or "", {"size": 10}))
            lines.append(("", {"blank": True}))
        elif kind == "tools":
            lines.append((b.get("title") or "Outils", {"bold": True, "size": 9}))
            for row in b.get("rows") or []:
                lines.append(
                    (
                        f"  · {row.get('name')} {row.get('status')}",
                        {"size": 9},
                    )
                )
            lines.append(("", {"blank": True}))
        elif kind == "card":
            lines.append((b.get("label") or "", {"bold": True, "size": 9}))
            lines.append(("", {"blank": True}))
    return lines


def export_discussion_pdf(bot: str, *, home: Path | None = None) -> tuple[bytes, str]:
    """Return (pdf_bytes, download_filename) for the bot's main conversation."""
    row = bots_svc.get_bot(bot, home=home)
    title_name = str(row.get("title") or row.get("name") or bot)
    messages = list_all_messages(bot, home=home)
    blocks = transcript_blocks(messages)
    if not blocks:
        blocks = [{"kind": "card", "label": "Aucun message. Dites bonjour."}]
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    pdf = build_discussion_pdf(
        title="Discussion",
        subtitle=f"{title_name}  ·  exporté le {now}",
        blocks=blocks,
    )
    safe = re.sub(r"[^\w\-]+", "_", str(row.get("name") or bot), flags=re.UNICODE)
    filename = f"discussion-{safe}.pdf"
    return pdf, filename
