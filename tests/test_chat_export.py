"""Discussion PDF export."""

from autonomous.services import chat as chat_svc
from autonomous.services import chat_export as export_svc


def _insert_event(home, bot, content, meta):
    chat_svc.create_message(bot, content, role="event", meta=meta, home=home)


def test_transcript_tools_without_details(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "pdfbot"})
    chat_svc.create_message("pdfbot", "Bonjour café", role="user", home=home)
    _insert_event(
        home,
        "pdfbot",
        "🔧 vm_click\nstatus: done\n{\"x\": 10}",
        {
            "kind": "tool",
            "tool_name": "vm_click",
            "status": "done",
            "args": {"x": 10, "y": 20},
        },
    )
    _insert_event(
        home,
        "pdfbot",
        "hidden",
        {"kind": "tool", "tool_name": "memory_search", "status": "done", "args": {"q": "secret"}},
    )
    chat_svc.create_message(
        "pdfbot", "Réponse avec accents — été", role="assistant", home=home
    )

    lines = export_svc.transcript_lines(export_svc.list_all_messages("pdfbot", home=home))
    flat = "\n".join(t for t, _ in lines)
    assert "Bonjour café" in flat
    assert "Réponse avec accents" in flat
    assert "vm_click" in flat
    assert "memory_search" not in flat
    assert '"x": 10' not in flat
    assert "secret" not in flat


def test_export_pdf_endpoint(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "pdf2"})
    chat_svc.create_message("pdf2", "Hello PDF", role="user", home=home)
    r = auth_client.get("/api/v1/bots/pdf2/messages/export.pdf")
    assert r.status_code == 200, r.data
    assert r.headers["Content-Type"].startswith("application/pdf")
    assert r.data[:5] == b"%PDF-"
    assert b"%%EOF" in r.data
    cd = r.headers.get("Content-Disposition", "")
    assert "discussion-pdf2.pdf" in cd


def test_build_discussion_pdf_looks_like_chat():
    from autonomous.pdf_text import build_discussion_pdf

    pdf = build_discussion_pdf(
        title="Discussion",
        subtitle="Assistant · exporté le 05/11/2026 19:00",
        blocks=[
            {"kind": "day", "label": "Aujourd'hui 19:00"},
            {"kind": "bubble", "role": "user", "text": "Café crème — été", "time": "19:00"},
            {
                "kind": "tools",
                "title": "2 outils",
                "badge": "Terminé",
                "tone": "done",
                "rows": [
                    {"name": "bash", "status": "Terminé", "state": "done", "time": "19:01"},
                    {"name": "vm_click", "status": "Terminé", "state": "done", "time": "19:01"},
                ],
                "time": "19:01",
            },
            {
                "kind": "bubble",
                "role": "assistant",
                "text": "Voici la réponse.",
                "time": "19:01",
            },
        ],
    )
    assert pdf.startswith(b"%PDF-")
    assert b"FontFile2" in pdf
    # At least one coloured fill operator for bubbles / cards
    assert b"rg" in pdf


def test_transcript_blocks_mirror_ui(auth_client, home):
    auth_client.post("/api/v1/bots", json={"name": "pdfui"})
    chat_svc.create_message("pdfui", "Salut", role="user", home=home)
    _insert_event(
        home,
        "pdfui",
        "tool",
        {"kind": "tool", "tool_name": "bash", "status": "done", "args": {"cmd": "ls"}},
    )
    chat_svc.create_message("pdfui", "OK", role="assistant", home=home)
    blocks = export_svc.transcript_blocks(export_svc.list_all_messages("pdfui", home=home))
    kinds = [b["kind"] for b in blocks]
    assert "bubble" in kinds and "tools" in kinds
    tools = next(b for b in blocks if b["kind"] == "tools")
    assert tools["title"] == "1 outil"
    assert tools["badge"] == "Terminé"
    assert tools["tone"] == "done"
    assert tools["rows"] == [
        {"name": "bash", "status": "Terminé", "state": "done", "time": tools["rows"][0]["time"]}
    ]
    assert "cmd" not in tools
    assert not any("args" in r for r in tools["rows"])
