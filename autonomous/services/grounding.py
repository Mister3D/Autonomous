"""GUI grounding: UI-TARS proposes pixels → hollow cross → multimodal judge.

This module **never clicks**. It returns geometry for the host action layer.
See ``grounding.md`` (repo root) and ``docs/features/grounding.md``.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import uuid

from autonomous.paths import default_home, ensure_home
from autonomous.services import bots as bots_svc
from autonomous.services import chat as chat_svc
from autonomous.services import screenshot as shot_svc
from autonomous.services import settings as settings_svc
from autonomous.services.errors import AutonomousError, ValidationError
from autonomous.services.grounding_image import (
    data_url_png,
    draw_drag_connector,
    draw_hollow_cross,
    fit_size,
    read_png,
    resize_nn,
    stack_vertical,
    write_png,
    zoom_around,
)
from autonomous.services.grounding_parse import (
    GROUNDER_SYSTEM,
    STRUCTURED_REGEX,
    parse_action,
)
from autonomous.services.pi_status import pi_env

_ANSWER_RE = re.compile(
    r"ANSWER:\s*(YES|NO|UNCERTAIN)\b", re.IGNORECASE
)
_MOVE_RE = re.compile(
    r"MOVE:\s*(UP|DOWN|LEFT|RIGHT)\b", re.IGNORECASE
)
_DIST_RE = re.compile(
    r"(?:DISTANCE|DIST):\s*(NEAR|MID|FAR)\b", re.IGNORECASE
)

_DIST_PX = {"NEAR": 70, "MID": 120, "FAR": 190}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_token_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def grounder_config(home: Path | None = None, *, ignore_enabled: bool = False) -> dict[str, str]:
    """Resolve grounder URL / model / API key (never log the key).

    ``AUTONOMOUS_GROUNDING_ENABLED=0`` (env or grounder.env, set by the web
    settings toggle) switches grounding off while keeping the URL.
    """
    home = ensure_home(home)
    env = os.environ
    # Optional local override file (gitignored): KEY=VALUE
    file_vars: dict[str, str] = {}
    for candidate in (
        home / "grounder.env",
        _repo_root() / "grounder.env",
    ):
        if candidate.is_file():
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                file_vars[k.strip()] = v.strip().strip("'").strip('"')
            break

    def pick(*keys: str, default: str = "") -> str:
        for k in keys:
            if env.get(k):
                return env[k].strip()
            if file_vars.get(k):
                return file_vars[k]
        return default

    base = pick(
        "AUTONOMOUS_GROUNDER_URL",
        "GROUNDER_BASE_URL",
        default="",
    ).rstrip("/")
    model = pick(
        "AUTONOMOUS_GROUNDER_MODEL",
        "GROUNDER_MODEL",
        default="ui-tars-1.5-7b",
    )
    key = pick(
        "AUTONOMOUS_GROUNDER_TOKEN",
        "GROUNDER_API_KEY",
        "GROUNDER_TOKEN",
    )
    if not key:
        key = _read_token_file(_repo_root() / "TOKEN")
    if not key:
        key = _read_token_file(home / "TOKEN")
    # No explicit flag: enabled iff a URL is set (a fresh install stays off).
    enabled = pick("AUTONOMOUS_GROUNDING_ENABLED", default="1" if base else "0").lower()
    if not ignore_enabled and enabled in ("0", "false", "off", "no"):
        base = ""
    return {"base_url": base, "model": model, "api_key": key}


def _local_vars(home: Path | None = None) -> dict[str, str]:
    """KEY=VALUE pairs from ``AUTONOMOUS_HOME/grounder.env`` (or repo root)."""
    home = ensure_home(home)
    out: dict[str, str] = {}
    for candidate in (home / "grounder.env", _repo_root() / "grounder.env"):
        if candidate.is_file():
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip("'").strip('"')
            break
    return out


def verifier_config(home: Path | None = None) -> dict[str, str]:
    """The click verifier is the agent LLM: primary provider of ``~/.pi/agent/models.json``.

    Same base URL and key as the Pi agent; the model is the provider's first model
    that accepts images (else its first model). ``AUTONOMOUS_VERIFIER_*`` settings
    are no longer read. Empty values when no LLM is configured.
    """
    from autonomous.services import setup_config as cfg_svc

    try:
        data = cfg_svc._read_models_json()
    except AutonomousError:
        data = {}
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    for conf in providers.values():
        if not isinstance(conf, dict):
            continue
        models = [m for m in conf.get("models") or [] if isinstance(m, dict) and m.get("id")]
        pick = next((m for m in models if "image" in (m.get("input") or [])), models[0] if models else None)
        key, _ = cfg_svc.resolve_api_key(conf.get("apiKey"))
        return {
            "base_url": str(conf.get("baseUrl") or "").strip().rstrip("/"),
            "model": str(pick["id"]) if pick else "",
            "api_key": key,
        }
    return {"base_url": "", "model": "", "api_key": ""}


def is_configured(home: Path | None = None) -> bool:
    """True when a grounder URL is set (grounding is off by default)."""
    return bool(grounder_config(home)["base_url"])


def _chat_completions(
    *,
    base_url: str,
    api_key: str,
    body: dict[str, Any],
    timeout: float = 90.0,
) -> dict[str, Any]:
    if not base_url:
        raise AutonomousError(
            "Grounding endpoint missing: set the UI-TARS URL in Settings → Grounding "
            "and the LLM in Settings → LLM (it is also the click verifier).",
            code="grounder_unconfigured",
        )
    if not api_key:
        raise AutonomousError(
            "Grounder or LLM API key missing "
            "(TOKEN file, grounder.env, or AUTONOMOUS_GROUNDER_TOKEN).",
            code="grounder_unconfigured",
        )
    url = f"{base_url}/chat/completions"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:400]
        raise AutonomousError(
            f"LLM HTTP {exc.code}: {err}",
            code="grounder_http",
        ) from exc
    except urllib.error.URLError as exc:
        raise AutonomousError(
            f"LLM unreachable: {exc.reason}",
            code="grounder_unreachable",
        ) from exc


def _assistant_text(resp: dict[str, Any]) -> str:
    choices = resp.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text") or ""))
        return "\n".join(parts)
    return str(content or "")


def call_grounder(
    *,
    image_data_url: str,
    instruction: str,
    home: Path | None = None,
) -> dict[str, Any]:
    """Ask UI-TARS for one structured GUI action (temperature 0)."""
    cfg = grounder_config(home)
    # Always end with center constraint (grounding.md).
    text = (instruction or "").strip()
    if not text:
        raise ValidationError("instruction required")
    if "center" not in text.lower():
        text = text.rstrip(".") + " at the center of the element."

    body = {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": 60,
        "structured_outputs": {"regex": STRUCTURED_REGEX},
        "messages": [
            {"role": "system", "content": GROUNDER_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": text},
                ],
            },
        ],
    }
    resp = _chat_completions(
        base_url=cfg["base_url"], api_key=cfg["api_key"], body=body
    )
    raw = _assistant_text(resp)
    parsed = parse_action(raw)
    return {"raw": raw, "parsed": parsed, "model": cfg["model"]}


def _parse_yes_no(text: str) -> str:
    m = _ANSWER_RE.search(text or "")
    if not m:
        # Fallback: lone YES/NO on a line
        for line in (text or "").upper().splitlines():
            line = line.strip()
            if line in ("YES", "NO", "UNCERTAIN"):
                return line
        return "UNCERTAIN"
    return m.group(1).upper()


def call_verifier(
    *,
    sheet_data_url: str,
    instruction: str,
    mode: str = "confirm",
) -> dict[str, Any]:
    """Multimodal judge — sees hollow cross (+ zoom)."""
    cfg = verifier_config()
    if mode == "exists":
        prompt = (
            f"User wants: {instruction}\n"
            "Is that UI element visible in this screenshot right now?\n"
            "Reply with exactly two lines:\n"
            "UNDER THE CROSSHAIR: n/a\n"
            "ANSWER: YES | NO | UNCERTAIN"
        )
    elif mode == "nudge":
        prompt = (
            f"The hollow cross marks a rejected point for: {instruction}\n"
            "Look at the HOLE in the center (not the arms). "
            "Suggest one corrective move.\n"
            "Reply with exactly:\n"
            "UNDER THE CROSSHAIR: <what you see>\n"
            "ANSWER: NO\n"
            "MOVE: UP|DOWN|LEFT|RIGHT\n"
            "DISTANCE: NEAR|MID|FAR"
        )
    else:
        prompt = (
            f"The hollow cross marks the proposed click/drag point for: "
            f"{instruction}\n"
            "Look at the pixel in the HOLE at the center of the cross "
            "(ignore the arms). "
            "Is that the CENTER of the requested element?\n"
            "Reply with exactly two lines:\n"
            "UNDER THE CROSSHAIR: <brief>\n"
            "ANSWER: YES | NO | UNCERTAIN"
        )

    body = {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": 120,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": sheet_data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    resp = _chat_completions(
        base_url=cfg["base_url"], api_key=cfg["api_key"], body=body, timeout=120
    )
    raw = _assistant_text(resp)
    out: dict[str, Any] = {
        "raw": raw,
        "answer": _parse_yes_no(raw),
        "model": cfg["model"],
    }
    if mode == "nudge":
        mm = _MOVE_RE.search(raw or "")
        dd = _DIST_RE.search(raw or "")
        if mm:
            out["move"] = mm.group(1).upper()
        if dd:
            out["distance"] = dd.group(1).upper()
    return out


def _remap_point(
    x: int, y: int, *, src_w: int, src_h: int, dst_w: int, dst_h: int
) -> tuple[int, int]:
    if src_w <= 0 or src_h <= 0:
        return x, y
    rx = int(round(x * (dst_w / src_w)))
    ry = int(round(y * (dst_h / src_h)))
    rx = max(0, min(dst_w - 1, rx))
    ry = max(0, min(dst_h - 1, ry))
    return rx, ry


def _verifier_sheet(
    width: int,
    height: int,
    rgb: bytearray,
    points: list[tuple[int, int]],
) -> tuple[int, int, bytearray]:
    marked = bytearray(rgb)
    if len(points) >= 2:
        marked = draw_drag_connector(
            width, height, marked, points[0][0], points[0][1], points[1][0], points[1][1]
        )
    for i, (x, y) in enumerate(points):
        marked = draw_hollow_cross(
            width,
            height,
            marked,
            x,
            y,
            gap=5,
            radius=14 + i * 2,
            arm=22,
        )
    sheets: list[tuple[int, int, bytearray]] = [(width, height, marked)]
    for x, y in points:
        sheets.append(zoom_around(width, height, marked, x, y, crop=140, zoom=2))
    return stack_vertical(sheets)


def _apply_nudge(
    x: int, y: int, move: str, distance: str, *, w: int, h: int
) -> tuple[int, int]:
    d = _DIST_PX.get((distance or "MID").upper(), 120)
    move = (move or "").upper()
    if move == "UP":
        y -= d
    elif move == "DOWN":
        y += d
    elif move == "LEFT":
        x -= d
    elif move == "RIGHT":
        x += d
    return max(0, min(w - 1, x)), max(0, min(h - 1, y))


def resolve_max_loops(
    max_retries: int | None, *, home: Path | None = None
) -> int:
    """Clamp grounding loops from arg or settings ``grounding.max_loops``."""
    if max_retries is None:
        raw = settings_svc.get("grounding.max_loops", home=home, default=2)
        try:
            max_retries = int(raw)
        except (TypeError, ValueError):
            max_retries = 2
    return max(1, min(8, int(max_retries)))


def _chat_note(
    bot: str,
    content: str,
    *,
    home: Path | None,
    phase: str,
    loop: int | None = None,
    answer: str | None = None,
    enabled: bool = True,
) -> None:
    if not enabled:
        return
    meta: dict[str, Any] = {
        "kind": "grounding",
        "phase": phase,
        "grounding": True,
    }
    if loop is not None:
        meta["loop"] = loop
    if answer:
        meta["answer"] = answer
    chat_svc.create_message(bot, content, role="event", meta=meta, home=home)


def _chat_image(
    bot: str,
    *,
    home: Path | None,
    caption: str,
    width: int,
    height: int,
    rgb: bytes | bytearray,
    phase: str,
    loop: int | None = None,
    x: int | None = None,
    y: int | None = None,
    enabled: bool = True,
    capture_id: str | None = None,
) -> dict[str, Any] | None:
    """Persist PNG under screenshots/ and post a chat card.

    Every image gets its own immutable ``<uuid>.png``. ``capture_id`` ties it
    to the raw capture of *this* ``locate`` call (the id vm_ground returns), so
    the chat shows the crosshair of that call, not the latest one.
    """
    if not enabled:
        return None
    shot_id = str(uuid.uuid4())
    host_dir = shot_svc.screenshots_dir(bot, home=home)
    host_png = host_dir / f"{shot_id}.png"
    write_png(host_png, width, height, rgb)
    url = f"/api/v1/bots/{bot}/screen/screenshots/{shot_id}.png"
    meta: dict[str, Any] = {
        "kind": "screenshot",
        "screenshot_id": shot_id,
        "url": url,
        "width": width,
        "height": height,
        "grounding": True,
        "phase": phase,
    }
    if capture_id:
        meta["capture_id"] = str(capture_id)
    if loop is not None:
        meta["loop"] = loop
    if x is not None and y is not None:
        meta["x"] = int(x)
        meta["y"] = int(y)
        meta["target"] = True
    chat_svc.create_message(bot, caption, role="event", meta=meta, home=home)
    return {"id": shot_id, "url": url, "width": width, "height": height}


def locate(
    bot: str,
    instruction: str,
    *,
    action_hint: str | None = None,
    verify: bool = True,
    check_exists: bool = True,
    max_retries: int | None = None,
    show_in_chat: bool = True,
    show_debug: bool | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Fresh screenshot → ground → (optional) verify → geometry only.

    Never performs a click. Host must refuse to act when ``ok`` is false.
    When ``show_in_chat`` is true, every loop posts capture / cross / verdict
    cards into the bot chat.
    """
    instruction = (instruction or "").strip()
    if not instruction:
        raise ValidationError("instruction required")
    if action_hint:
        hint = str(action_hint).strip().lower()
        hint_map = {
            "click": "click",
            "left_click": "click",
            "right_click": "right_single",
            "double": "left_double",
            "drag": "drag",
            "scroll": "scroll",
        }
        mapped = hint_map.get(hint, hint)
        instruction = f"{instruction} Prefer action: {mapped}."

    # Legacy alias
    if show_debug is not None:
        show_in_chat = bool(show_debug)

    max_loops = resolve_max_loops(max_retries, home=home)
    chat = bool(show_in_chat)

    bots_svc.get_bot(bot, home=home)
    shot = shot_svc.capture(bot, show_in_chat=False, home=home)
    png_path = shot_svc.resolve_png(bot, shot["id"], home=home)

    orig_w, orig_h, orig_rgb = read_png(png_path)
    capture_url = shot.get("url") or (
        f"/api/v1/bots/{bot}/screen/screenshots/{shot['id']}.png"
    )
    _chat_image(
        bot,
        home=home,
        caption=f"Grounding · capture · « {instruction[:80]} »",
        width=orig_w,
        height=orig_h,
        rgb=orig_rgb,
        phase="capture",
        enabled=chat,
            capture_id=shot["id"],
    )

    loops: list[dict[str, Any]] = []

    if check_exists and verify:
        exists_url = data_url_png(orig_w, orig_h, orig_rgb)
        existence = call_verifier(
            sheet_data_url=exists_url,
            instruction=instruction,
            mode="exists",
        )
        _chat_note(
            bot,
            f"Grounding · existence → {existence['answer']}",
            home=home,
            phase="existence",
            answer=existence["answer"],
            enabled=chat,
        )
        if existence["answer"] == "NO":
            return {
                "ok": False,
                "status": "missing",
                "error": "Element not visible according to verifier",
                "instruction": instruction,
                "screenshot_id": shot["id"],
                "capture_url": capture_url,
                "existence": {"answer": existence["answer"]},
                "max_loops": max_loops,
                "loops": loops,
            }

    gw, gh = fit_size(orig_w, orig_h)
    ground_rgb = (
        orig_rgb if (gw, gh) == (orig_w, orig_h) else resize_nn(orig_w, orig_h, orig_rgb, gw, gh)
    )
    ground_url = data_url_png(gw, gh, ground_rgb)

    last_error = ""
    blacklist_note = ""
    for attempt in range(max_loops):
        loop_n = attempt + 1
        prompt = instruction
        if blacklist_note:
            prompt = f"{instruction} {blacklist_note}"

        _chat_note(
            bot,
            f"Grounding · boucle {loop_n}/{max_loops} · appel UI-TARS…",
            home=home,
            phase="grounder",
            loop=loop_n,
            enabled=chat,
        )

        g = call_grounder(image_data_url=ground_url, instruction=prompt, home=home)
        parsed = g["parsed"]
        action = parsed.get("action")
        loop_rec: dict[str, Any] = {
            "attempt": loop_n,
            "grounder_raw": g["raw"],
            "action": action,
        }

        if action in ("finished", "wait"):
            _chat_note(
                bot,
                f"Grounding · boucle {loop_n} · grounder → {action} (cible absente)",
                home=home,
                phase="missing",
                loop=loop_n,
                enabled=chat,
            )
            loops.append(loop_rec)
            return {
                "ok": False,
                "status": "missing",
                "error": f"Grounder returned {action}",
                "instruction": instruction,
                "screenshot_id": shot["id"],
                "capture_url": capture_url,
                "grounder_raw": g["raw"],
                "max_loops": max_loops,
                "loops": loops,
            }
        if action == "unknown" or "x" not in parsed:
            last_error = f"Unparseable grounder output: {g['raw']!r}"
            loop_rec["error"] = last_error
            loops.append(loop_rec)
            _chat_note(
                bot,
                f"Grounding · boucle {loop_n} · sortie illisible : {g['raw']!r}",
                home=home,
                phase="parse_error",
                loop=loop_n,
                enabled=chat,
            )
            continue

        x, y = _remap_point(
            int(parsed["x"]),
            int(parsed["y"]),
            src_w=gw,
            src_h=gh,
            dst_w=orig_w,
            dst_h=orig_h,
        )
        points = [(x, y)]
        x2 = y2 = None
        if action == "drag" and "x2" in parsed:
            x2, y2 = _remap_point(
                int(parsed["x2"]),
                int(parsed["y2"]),
                src_w=gw,
                src_h=gh,
                dst_w=orig_w,
                dst_h=orig_h,
            )
            # Slide captchas often get a too-short end box from the grounder —
            # stretch short nearly-horizontal drags toward the slide direction.
            # Cap stretch: Verification-slider tracks are ~250–320px, NOT 30% of 1920.
            dx, dy = x2 - x, y2 - y
            if abs(dx) >= abs(dy) and abs(dx) < 160:
                stretch = max(240, min(320, abs(dx) + 180))
                x2 = min(orig_w - 8, x + stretch) if dx >= 0 else max(8, x - stretch)
            points.append((x2, y2))

        loop_rec.update({"x": x, "y": y, "action": action})
        if x2 is not None:
            loop_rec["x2"] = x2
            loop_rec["y2"] = y2

        result: dict[str, Any] = {
            "ok": True,
            "status": "ok",
            "action": action,
            "x": x,
            "y": y,
            "instruction": instruction,
            "screenshot_id": shot["id"],
            "capture_url": capture_url,
            "image_size": {"width": orig_w, "height": orig_h},
            "grounder_size": {"width": gw, "height": gh},
            "grounder_raw": g["raw"],
            "attempt": loop_n,
            "max_loops": max_loops,
        }
        if x2 is not None:
            result["x2"] = x2
            result["y2"] = y2
        if parsed.get("direction"):
            result["direction"] = parsed["direction"]
            loop_rec["direction"] = parsed["direction"]

        if not verify:
            _chat_note(
                bot,
                f"Grounding · boucle {loop_n} · proposé ({x},{y}) — vérif désactivée",
                home=home,
                phase="unverified",
                loop=loop_n,
                enabled=chat,
            )
            loops.append(loop_rec)
            result["loops"] = loops
            return result

        sw, sh, sheet = _verifier_sheet(orig_w, orig_h, orig_rgb, points)
        sheet_pub = _chat_image(
            bot,
            home=home,
            caption=f"Grounding · boucle {loop_n}/{max_loops} · croix ({x},{y})",
            width=sw,
            height=sh,
            rgb=sheet,
            phase="crosshair",
            loop=loop_n,
            x=x,
            y=y,
            enabled=chat,
            capture_id=shot["id"],
        )
        if sheet_pub:
            loop_rec["sheet_url"] = sheet_pub["url"]

        sheet_url = data_url_png(sw, sh, sheet)
        verdict = call_verifier(
            sheet_data_url=sheet_url,
            instruction=instruction,
            mode="confirm",
        )
        result["verifier"] = {
            "answer": verdict["answer"],
            "raw": verdict["raw"],
            "model": verdict["model"],
        }
        loop_rec["verifier"] = result["verifier"]
        _chat_note(
            bot,
            f"Grounding · boucle {loop_n} · confirmation → {verdict['answer']}"
            + (f"\n{(verdict.get('raw') or '')[:280]}" if verdict.get("raw") else ""),
            home=home,
            phase="verify",
            loop=loop_n,
            answer=verdict["answer"],
            enabled=chat,
        )

        if verdict["answer"] == "YES":
            loops.append(loop_rec)
            result["loops"] = loops
            return result

        if verdict["answer"] == "UNCERTAIN":
            result["ok"] = False
            result["status"] = "rejected"
            result["error"] = "Verifier uncertain"
            loops.append(loop_rec)
            result["loops"] = loops
            return result

        # NO → optional one nudge, then re-verify; else retry grounder
        nudge = call_verifier(
            sheet_data_url=sheet_url,
            instruction=instruction,
            mode="nudge",
        )
        if nudge.get("move"):
            nx, ny = _apply_nudge(
                x,
                y,
                nudge["move"],
                nudge.get("distance") or "MID",
                w=orig_w,
                h=orig_h,
            )
            _chat_note(
                bot,
                f"Grounding · boucle {loop_n} · décalage "
                f"{nudge.get('move')} {nudge.get('distance') or 'MID'} → ({nx},{ny})",
                home=home,
                phase="nudge",
                loop=loop_n,
                enabled=chat,
            )
            n_points = [(nx, ny)]
            if x2 is not None:
                n_points.append((x2, y2))  # type: ignore[arg-type]
            nsw, nsh, nsheet = _verifier_sheet(orig_w, orig_h, orig_rgb, n_points)
            _chat_image(
                bot,
                home=home,
                caption=f"Grounding · boucle {loop_n} · croix après décalage ({nx},{ny})",
                width=nsw,
                height=nsh,
                rgb=nsheet,
                phase="crosshair_nudge",
                loop=loop_n,
                x=nx,
                y=ny,
                enabled=chat,
            capture_id=shot["id"],
            )
            n_verdict = call_verifier(
                sheet_data_url=data_url_png(nsw, nsh, nsheet),
                instruction=instruction,
                mode="confirm",
            )
            _chat_note(
                bot,
                f"Grounding · boucle {loop_n} · re-confirmation → {n_verdict['answer']}",
                home=home,
                phase="verify_nudge",
                loop=loop_n,
                answer=n_verdict["answer"],
                enabled=chat,
            )
            loop_rec["nudge"] = {
                "move": nudge.get("move"),
                "distance": nudge.get("distance"),
                "x": nx,
                "y": ny,
                "verifier": {
                    "answer": n_verdict["answer"],
                    "raw": n_verdict["raw"],
                },
            }
            if n_verdict["answer"] == "YES":
                result["x"], result["y"] = nx, ny
                result["ok"] = True
                result["status"] = "ok"
                result["nudged"] = True
                result["verifier"] = {
                    "answer": "YES",
                    "raw": n_verdict["raw"],
                    "model": n_verdict["model"],
                    "nudge": {
                        "move": nudge.get("move"),
                        "distance": nudge.get("distance"),
                    },
                }
                loops.append(loop_rec)
                result["loops"] = loops
                return result

        blacklist_note = (
            f"Previous point ({x},{y}) was wrong — choose a different point "
            "on the same element, at its center."
        )
        last_error = f"Verifier rejected point ({x},{y})"
        loops.append(loop_rec)

    _chat_note(
        bot,
        f"Grounding · échec après {max_loops} boucle(s) — {last_error or 'rejeté'}",
        home=home,
        phase="failed",
        enabled=chat,
    )
    return {
        "ok": False,
        "status": "rejected",
        "error": last_error or "Grounding failed",
        "instruction": instruction,
        "screenshot_id": shot["id"],
        "capture_url": capture_url,
        "max_loops": max_loops,
        "loops": loops,
    }


def locate_from_png(
    png_path: str | Path,
    instruction: str,
    *,
    verify: bool = True,
    check_exists: bool = False,
    home: Path | None = None,
) -> dict[str, Any]:
    """Ground a local PNG (tests / CLI) without a bot desk."""
    png_path = Path(png_path)
    instruction = (instruction or "").strip()
    if not instruction:
        raise ValidationError("instruction required")
    orig_w, orig_h, orig_rgb = read_png(png_path)
    gw, gh = fit_size(orig_w, orig_h)
    ground_rgb = (
        orig_rgb if (gw, gh) == (orig_w, orig_h) else resize_nn(orig_w, orig_h, orig_rgb, gw, gh)
    )
    g = call_grounder(
        image_data_url=data_url_png(gw, gh, ground_rgb),
        instruction=instruction,
        home=home or default_home(),
    )
    parsed = g["parsed"]
    if parsed.get("action") in ("finished", "wait", "unknown") or "x" not in parsed:
        return {
            "ok": False,
            "status": "missing" if parsed.get("action") == "finished" else "error",
            "error": g["raw"],
            "grounder_raw": g["raw"],
        }
    x, y = _remap_point(
        int(parsed["x"]), int(parsed["y"]), src_w=gw, src_h=gh, dst_w=orig_w, dst_h=orig_h
    )
    result: dict[str, Any] = {
        "ok": True,
        "status": "ok",
        "action": parsed["action"],
        "x": x,
        "y": y,
        "image_size": {"width": orig_w, "height": orig_h},
        "grounder_raw": g["raw"],
    }
    if "x2" in parsed:
        x2, y2 = _remap_point(
            int(parsed["x2"]), int(parsed["y2"]), src_w=gw, src_h=gh, dst_w=orig_w, dst_h=orig_h
        )
        result["x2"], result["y2"] = x2, y2
    if not verify:
        return result
    sw, sh, sheet = _verifier_sheet(orig_w, orig_h, orig_rgb, [(x, y)])
    verdict = call_verifier(
        sheet_data_url=data_url_png(sw, sh, sheet),
        instruction=instruction,
        mode="confirm",
    )
    result["verifier"] = {"answer": verdict["answer"], "raw": verdict["raw"]}
    if verdict["answer"] != "YES":
        result["ok"] = False
        result["status"] = "rejected" if verdict["answer"] == "NO" else "rejected"
        result["error"] = f"Verifier: {verdict['answer']}"
    return result


_DESCRIBE_PROMPT = (
    "You are the eyes of a web-browsing agent that cannot see its screen. "
    "Describe this desktop screenshot factually and concisely (max 15 lines, same "
    "language as the on-screen text for quotes):\n"
    "1. Which site / app / page type is in front.\n"
    "2. EXACT visible text of headings, error or warning messages, banners and dialogs "
    "(quote it; do not paraphrase errors).\n"
    "3. Anything blocking or gating the page: cookie/consent layer, modal, "
    "verification widget (and its kind: checkbox / slider / puzzle / retry), "
    "'access denied / restricted / blocked' page, login wall — with the buttons it offers.\n"
    "4. Form fields: label, empty or filled (masked values: say 'filled, hidden'), "
    "validation errors.\n"
    "5. The data the page shows that matters for the task, if any.\n"
    "Never guess or invent text you cannot read."
)


def describe_screen(
    bot: str,
    question: str | None = None,
    *,
    show_in_chat: bool = False,
    home: Path | None = None,
) -> dict[str, Any]:
    """Fresh screenshot → multimodal model → plain-text description (no gesture).

    Gives a DOM-blind agent eyes (captcha iframes, canvas, block pages, overlays)
    without ever attaching the PNG to the agent LLM itself.
    """
    bots_svc.get_bot(bot, home=home)
    shot = shot_svc.capture(bot, show_in_chat=show_in_chat, home=home)
    png_path = shot_svc.resolve_png(bot, shot["id"], home=home)
    w, h, rgb = read_png(png_path)
    prompt = _DESCRIBE_PROMPT
    q = (question or "").strip()
    if q:
        prompt += f"\nSpecific question to answer first: {q}"
    cfg = verifier_config(home)
    body = {
        "model": cfg["model"],
        "temperature": 0,
        "max_tokens": 700,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url_png(w, h, rgb)}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    resp = _chat_completions(
        base_url=cfg["base_url"], api_key=cfg["api_key"], body=body, timeout=120
    )
    text = _assistant_text(resp).strip()
    return {
        "ok": bool(text),
        "text": text,
        "screenshot_id": shot["id"],
        "model": cfg["model"],
    }
