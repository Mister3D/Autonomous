"""Regression: each grounding call keeps its own immutable screenshot."""

from __future__ import annotations

from autonomous.services import chat as chat_svc
from autonomous.services import grounding as g_svc
from autonomous.services import bots as bots_svc


def test_two_calls_two_images(home, monkeypatch):
    monkeypatch.setattr("autonomous.services.pi_status.list_models", lambda *a, **k: [])
    bots_svc.create_bot("Shots", home=home)
    posted = []
    monkeypatch.setattr(chat_svc, "create_message", lambda bot, c, **kw: posted.append(kw["meta"]) or {"id": str(len(posted))})
    rgb1 = bytes([255, 0, 0]) * 4
    rgb2 = bytes([0, 0, 255]) * 4
    a = g_svc._chat_image("shots", home=home, caption="a", width=2, height=2, rgb=rgb1,
                          phase="crosshair", x=1, y=1, capture_id="cap-1")
    b = g_svc._chat_image("shots", home=home, caption="b", width=2, height=2, rgb=rgb2,
                          phase="crosshair", x=0, y=0, capture_id="cap-2")
    assert a["id"] != b["id"] and a["url"] != b["url"]
    from autonomous.services import screenshot as shot_svc
    d = shot_svc.screenshots_dir("shots", home=home)
    assert (d / f"{a['id']}.png").read_bytes() != (d / f"{b['id']}.png").read_bytes()
    assert posted[0]["capture_id"] == "cap-1" and posted[0]["screenshot_id"] == a["id"]
    assert posted[1]["capture_id"] == "cap-2" and posted[1]["screenshot_id"] == b["id"]
