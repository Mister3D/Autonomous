"""Generic slide-to-verify detection used by browser_frames_snapshot / navigate."""

from __future__ import annotations

import sys
from pathlib import Path

from autonomous.services import desk as desk_svc

# The worker runs standalone inside the desk next to cdp_client.py.
sys.path.insert(0, str(Path(desk_svc.__file__).parent))
import chrome_cdp_worker as worker  # noqa: E402


def _el(tag, cls, x, y, w, h, **extra):
    return {
        "tag": tag,
        "className": cls,
        "bbox_screen": {"x": x, "y": y, "w": w, "h": h},
        "center_screen": {"x": x + w // 2, "y": y + h // 2},
        **extra,
    }


def test_slider_with_target_element():
    frames = [
        {
            "type": "iframe",
            "url": "https://widgets.example/verify",
            "elements": [
                _el("div", "sliderText", 791, 479, 338, 60, text="Slide right"),
                _el("div", "sliderContainer", 820, 539, 280, 40),
                _el("div", "sliderTarget", 1042, 539, 63, 40),
                _el("i", "sliderTargetIcon", 1067, 554, 13, 10),
                _el("div", "slider", 820, 539, 63, 40),
                _el("i", "sliderIcon", 845, 539, 13, 40),
            ],
        }
    ]
    hints = worker._slider_hints(frames)
    assert len(hints) == 1
    assert hints[0]["handle"] == {"x": 851, "y": 559}
    assert hints[0]["to"] == {"x": 1073, "y": 559}
    assert hints[0]["basis"] == "target element"


def test_slider_falls_back_to_track_end():
    frames = [
        {
            "type": "page",
            "url": "https://site.example/",
            "elements": [
                _el("div", "range-track", 100, 300, 300, 20),
                _el("div", "range-handle", 100, 295, 30, 30),
            ],
        }
    ]
    hints = worker._slider_hints(frames)
    assert len(hints) == 1
    assert hints[0]["handle"] == {"x": 115, "y": 310}
    assert hints[0]["to"]["x"] == 100 + 300 - 15
    assert hints[0]["basis"] == "track right end"


def test_no_slider_no_hint():
    frames = [
        {
            "type": "page",
            "url": "https://site.example/",
            "elements": [_el("button", "btn primary", 10, 10, 80, 30, text="OK")],
        }
    ]
    assert worker._slider_hints(frames) == []


def test_host_port_free_detects_used_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert desk_svc._host_port_free(port) is False
    assert desk_svc._host_port_free(port) is True
