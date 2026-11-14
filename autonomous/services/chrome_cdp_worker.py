#!/usr/bin/env python3
"""Chrome CDP helper — runs inside the desk container (stdlib only).

Subcommands:
  tabs
  navigate --url URL
  wait_load [--timeout S]
  focus_info
  reset_session
  html [--max N] [--selector CSS]
  text [--max N]
  links [--max N] [--query SUBSTR]
  scroll --dy PX [--dx PX]
  snapshot [--max N] [--query SUBSTR]
  frames_snapshot [--max N] [--query SUBSTR]
  click_selector --selector CSS
  eval --js CODE
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

# Prefer sibling module when copied next to this file; else same-dir import.
try:
    from cdp_client import (  # type: ignore
        CdpError,
        connect_page,
        connect_target,
        list_targets,
    )
except ImportError:
    sys.path.insert(0, "/home/autonomous/workspace/.autonomous")
    from cdp_client import (  # type: ignore
        CdpError,
        connect_page,
        connect_target,
        list_targets,
    )


def _out(obj: dict) -> int:
    print(json.dumps(obj, ensure_ascii=False))
    return 0


def cmd_tabs(_: argparse.Namespace) -> int:
    targets = list_targets()
    pages = [
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "url": t.get("url"),
            "type": t.get("type"),
        }
        for t in targets
        if t.get("type") == "page"
    ]
    return _out({"ok": True, "pages": pages})


def _page_widgets() -> list[dict[str, Any]]:
    """Slide-to-verify widgets currently on screen (best effort, never raises).

    Only looked for when the page embeds iframes (that is where verification
    widgets live), so ordinary pages pay one cheap target listing.
    """
    try:
        if not any(t.get("type") == "iframe" for t in list_targets()):
            return []
        res = _frames_collect("", 60)
        return _slider_hints(res.get("frames") or [])
    except Exception:
        return []


def _pages() -> list[dict[str, Any]]:
    return [t for t in list_targets() if t.get("type") == "page"]


def _pick_tab(ns: argparse.Namespace) -> dict[str, Any] | None:
    pages = _pages()
    if getattr(ns, "match", None):
        needle = str(ns.match).lower()
        for t in pages:
            if needle in (str(t.get("url") or "") + " " + str(t.get("title") or "")).lower():
                return t
        return None
    idx = int(getattr(ns, "index", 0) or 0)
    return pages[idx - 1] if 1 <= idx <= len(pages) else None


def cmd_switch_tab(ns: argparse.Namespace) -> int:
    """Bring a tab to the front: every other command then acts on it."""
    import time
    import urllib.request

    t = _pick_tab(ns)
    if not t:
        return _out({"ok": False, "error": "no such tab (see browser_tabs)"})
    urllib.request.urlopen(
        f"http://127.0.0.1:9222/json/activate/{t['id']}", timeout=5
    ).read()
    time.sleep(0.4)
    return _out({"ok": True, "url": t.get("url"), "title": t.get("title"), "pages": [
        {"id": x.get("id"), "title": x.get("title"), "url": x.get("url"), "type": "page"}
        for x in _pages()
    ]})


def cmd_close_tab(ns: argparse.Namespace) -> int:
    """Close a tab (default: the active one); the next tab becomes active."""
    import time
    import urllib.request

    if not getattr(ns, "match", None) and not getattr(ns, "index", 0):
        pages = _pages()
        t = pages[0] if pages else None
    else:
        t = _pick_tab(ns)
    if not t:
        return _out({"ok": False, "error": "no such tab (see browser_tabs)"})
    if len(_pages()) <= 1:
        return _out({"ok": False, "error": "refusing to close the last tab"})
    urllib.request.urlopen(
        f"http://127.0.0.1:9222/json/close/{t['id']}", timeout=5
    ).read()
    time.sleep(0.4)
    rest = _pages()
    return _out({"ok": True, "closed": t.get("url"), "pages": [
        {"id": x.get("id"), "title": x.get("title"), "url": x.get("url"), "type": "page"}
        for x in rest
    ]})


def cmd_navigate(ns: argparse.Namespace) -> int:
    import time

    sess, target = connect_page()
    try:
        sess.call("Page.enable")
        sess.call("Page.navigate", {"url": ns.url})
        # Wait for loadEventFired (or timeout) so callers need no bash sleep.
        deadline = time.time() + 20.0
        loaded = False
        while time.time() < deadline:
            try:
                ev = sess.poll(timeout=0.5)
            except CdpError:
                break
            if not ev:
                continue
            method = ev.get("method") or ""
            if method == "Page.loadEventFired":
                loaded = True
                break
            if method == "Page.frameStoppedLoading":
                loaded = True
                break
        # Small settle for late JS / bot walls
        time.sleep(1.2)
        # Refresh target meta
        try:
            info = sess.call(
                "Runtime.evaluate",
                {
                    "expression": "({title: document.title, url: location.href})",
                    "returnByValue": True,
                },
            )
            cur = (info or {}).get("result", {}).get("value") or {}
        except Exception:
            cur = {}
        return _out(
            {
                "ok": True,
                "navigated": ns.url,
                "loaded": loaded,
                "url": cur.get("url") or ns.url,
                "title": cur.get("title"),
                "from": {"title": target.get("title"), "url": target.get("url")},
                "slider_hints": _page_widgets(),
            }
        )
    finally:
        sess.close()


def cmd_wait_load(ns: argparse.Namespace) -> int:
    """Wait until the active page finished loading — bounded, never blocks forever.

    « Loaded » = ``document.readyState == 'complete'`` on two polls ~0.3 s apart
    (a click-triggered navigation may briefly still show the old document).
    Chrome not up yet / CDP not answering is retried until the deadline.
    Pages that load forever (long-polling, trackers) simply hit the timeout:
    the page is then usually already usable, so the answer says so.
    """
    import time

    t0 = time.time()
    deadline = t0 + max(1.0, float(ns.timeout))
    time.sleep(0.4)  # let a just-fired navigation start
    stable = 0
    state = None
    cur: dict = {}
    sess = None
    while time.time() < deadline:
        try:
            if sess is None:
                sess, _ = connect_page()
            res = sess.call(
                "Runtime.evaluate",
                {
                    "expression": "({s: document.readyState, title: document.title, "
                    "url: location.href})",
                    "returnByValue": True,
                },
            )
            cur = (res or {}).get("result", {}).get("value") or {}
            state = cur.get("s")
        except Exception:
            # Chrome starting / page swapped during navigation → reconnect.
            if sess is not None:
                try:
                    sess.close()
                except Exception:
                    pass
            sess, state, stable = None, None, 0
            time.sleep(0.5)
            continue
        if state == "complete":
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        time.sleep(0.3)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
    loaded = stable >= 2
    return _out(
        {
            "ok": True,
            "loaded": loaded,
            "timed_out": not loaded,
            "ready_state": state,
            "waited_s": round(time.time() - t0, 1),
            "url": cur.get("url"),
            "title": cur.get("title"),
            "slider_hints": _page_widgets(),
        }
    )


def cmd_reset_session(_: argparse.Namespace) -> int:
    """Forget the browsing session: cookies, cache, storage of the current origin.

    Same effect as opening a brand-new private window: a site that
    flagged this session (tracking cookie, stale challenge) sees a first visit.
    The profile itself (extensions, prefs) is kept; only site data goes.
    """
    sess, target = connect_page()
    try:
        origin = ""
        try:
            r = sess.call(
                "Runtime.evaluate", {"expression": "location.origin", "returnByValue": True}
            )
            origin = str((r or {}).get("result", {}).get("value") or "")
        except Exception:
            pass
        cleared: list[str] = []
        sess.call("Network.enable")
        for method, params, label in (
            ("Network.clearBrowserCookies", {}, "cookies"),
            ("Network.clearBrowserCache", {}, "cache"),
        ):
            try:
                sess.call(method, params)
                cleared.append(label)
            except Exception:
                pass
        if origin.startswith("http"):
            try:
                sess.call(
                    "Storage.clearDataForOrigin", {"origin": origin, "storageTypes": "all"}
                )
                cleared.append("origin-storage")
            except Exception:
                pass
        return _out({"ok": True, "cleared": cleared, "origin": origin})
    finally:
        sess.close()


def cmd_focus_info(_: argparse.Namespace) -> int:
    """Which element has keyboard focus in the active page (no content, no secrets)."""
    sess, _target = connect_page()
    try:
        js = (
            "(() => { const a = document.activeElement; const hf = document.hasFocus(); "
            "if (!a) return {has_focus: hf, tag: null, editable: false}; "
            "const tag = a.tagName; const ty = (a.type || 'text').toLowerCase(); "
            "const bad = ['button','submit','checkbox','radio','image','reset','file','range','color']; "
            "const editable = !!(a.isContentEditable || tag === 'TEXTAREA' || "
            "(tag === 'INPUT' && !bad.includes(ty))); "
            "return {has_focus: hf, tag, type: a.type || null, editable}; })()"
        )
        res = sess.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
        val = (res or {}).get("result", {}).get("value") or {}
        return _out({"ok": True, **val})
    finally:
        sess.close()


def cmd_html(ns: argparse.Namespace) -> int:
    sess, target = connect_page()
    try:
        sess.call("DOM.enable")
        if ns.selector:
            js = (
                f"() => {{ const el = document.querySelector({json.dumps(ns.selector)}); "
                "return el ? el.outerHTML : null; }"
            )
        else:
            js = "() => document.documentElement.outerHTML"
        result = sess.call("Runtime.evaluate", {"expression": f"({js})()", "returnByValue": True})
        html = (result or {}).get("result", {}).get("value")
        if html is None:
            return _out({"ok": False, "error": "element not found", "url": target.get("url")})
        text = str(html)
        truncated = False
        if len(text) > ns.max:
            text = text[: ns.max]
            truncated = True
        return _out(
            {
                "ok": True,
                "url": target.get("url"),
                "title": target.get("title"),
                "html": text,
                "truncated": truncated,
                "chars": len(text),
            }
        )
    finally:
        sess.close()


def cmd_text(ns: argparse.Namespace) -> int:
    sess, target = connect_page()
    try:
        js = "() => document.body ? document.body.innerText : ''"
        result = sess.call("Runtime.evaluate", {"expression": f"({js})()", "returnByValue": True})
        text = str((result or {}).get("result", {}).get("value") or "")
        truncated = False
        if len(text) > ns.max:
            text = text[: ns.max]
            truncated = True
        return _out(
            {
                "ok": True,
                "url": target.get("url"),
                "title": target.get("title"),
                "text": text,
                "truncated": truncated,
                "chars": len(text),
            }
        )
    finally:
        sess.close()


def cmd_links(ns: argparse.Namespace) -> int:
    sess, target = connect_page()
    try:
        js = """() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
          text: (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 160),
          href: a.href
        })).filter(x => x.text && x.href && !x.href.startsWith('javascript:'))"""
        result = sess.call("Runtime.evaluate", {"expression": f"({js})()", "returnByValue": True})
        links = (result or {}).get("result", {}).get("value") or []
        if not isinstance(links, list):
            links = []
        q = (ns.query or "").strip().lower()
        if q:
            links = [
                L
                for L in links
                if q in str(L.get("text") or "").lower() or q in str(L.get("href") or "").lower()
            ]
        links = links[: max(1, ns.max)]
        return _out(
            {
                "ok": True,
                "url": target.get("url"),
                "title": target.get("title"),
                "links": links,
                "count": len(links),
            }
        )
    finally:
        sess.close()


def cmd_scroll(ns: argparse.Namespace) -> int:
    sess, _target = connect_page()
    try:
        dx, dy = int(ns.dx), int(ns.dy)
        sess.call(
            "Runtime.evaluate",
            {
                "expression": f"window.scrollBy({dx}, {dy}); JSON.stringify({{x: window.scrollX, y: window.scrollY, maxY: document.documentElement.scrollHeight}})",
                "returnByValue": True,
            },
        )
        # result is a JSON string sometimes
        result = sess.call(
            "Runtime.evaluate",
            {
                "expression": "({x: window.scrollX, y: window.scrollY, height: document.documentElement.scrollHeight, inner: window.innerHeight})",
                "returnByValue": True,
            },
        )
        pos = (result or {}).get("result", {}).get("value") or {}
        return _out({"ok": True, "scrolled": {"dx": dx, "dy": dy}, "position": pos})
    finally:
        sess.close()


def cmd_snapshot(ns: argparse.Namespace) -> int:
    """Compact interactive DOM outline — no scroll, no click (stealth-friendly read)."""
    sess, target = connect_page()
    try:
        max_n = max(1, min(int(ns.max), 120))
        query = (ns.query or "").strip().lower()
        js = f"""() => {{
          const q = {json.dumps(query)};
          const maxN = {max_n};
          const sels = [
            'a[href]', 'button', 'input', 'textarea', 'select',
            '[role="button"]', '[role="link"]', '[role="checkbox"]',
            '[role="radio"]', '[role="slider"]', '[role="textbox"]',
            '[contenteditable="true"]'
          ].join(',');
          const out = [];
          const vw = innerWidth, vh = innerHeight;
          const chromeH = Math.max(0, outerHeight - innerHeight);
          const clip = (s, n) => ((s || '') + '').trim().replace(/\\s+/g, ' ').slice(0, n);
          const describe = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
            + ((e.className && e.className.slice) ? '.' + String(e.className).trim().split(/\\s+/)[0] : '');
          const ctlSel = 'a[href],button,input,select,textarea,[role="button"],[role="checkbox"],[role="link"]';
          const shown = (e) => {{
            const s = getComputedStyle(e);
            if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
            const b = e.getBoundingClientRect();
            return b.width >= 2 && b.height >= 2;
          }};
          // Blocking layers (modals, consent banners, drawers) — visible on screen
          // instantly; a DOM-only agent must be told, or its clicks land on the layer.
          const overlays = [];
          try {{
            const cands = new Set();
            document.querySelectorAll(
              '[role="dialog"],[role="alertdialog"],[aria-modal="true"],dialog[open]'
            ).forEach(e => {{ if (shown(e)) cands.add(e); }});
            for (const [fx, fy] of [[.5,.5],[.5,.2],[.5,.8],[.2,.5],[.8,.5],[.5,.05],[.5,.95]]) {{
              const top = document.elementFromPoint(fx * vw, fy * vh);
              for (let a = top; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {{
                const s = getComputedStyle(a);
                const z = parseInt(s.zIndex, 10);
                if (s.position === 'fixed' || ((s.position === 'absolute' || s.position === 'sticky') && z > 0)) {{
                  const b = a.getBoundingClientRect();
                  if (b.width * b.height >= 0.06 * vw * vh) cands.add(a);
                }}
              }}
            }}
            const withCtl = [...cands].filter(c =>
              !c.querySelector('main, header, footer') && [...c.querySelectorAll(ctlSel)].some(shown));
            const keep = withCtl.filter(c => !withCtl.some(o => o !== c && o.contains(c)));
            for (const c of keep.slice(0, 3)) {{
              const b = c.getBoundingClientRect();
              overlays.push({{
                kind: c.getAttribute('role') || c.tagName.toLowerCase(),
                text: clip(c.innerText, 320),
                bbox: {{ x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) }},
                controls: [...c.querySelectorAll(ctlSel)].filter(shown).slice(0, 8).map(e => {{
                  const r2 = e.getBoundingClientRect();
                  return {{
                    tag: e.tagName.toLowerCase(),
                    text: clip(e.innerText || e.value || e.getAttribute('aria-label'), 60),
                    bbox: {{ x: Math.round(r2.x), y: Math.round(r2.y), w: Math.round(r2.width), h: Math.round(r2.height) }},
                    screen: {{ x: Math.round(r2.x + r2.width / 2), y: Math.round(r2.y + r2.height / 2 + chromeH) }}
                  }};
                }})
              }});
            }}
          }} catch (e) {{}}
          for (const el of document.querySelectorAll(sels)) {{
            const st = getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') continue;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            const text = ((el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '') + '')
              .trim().replace(/\\s+/g, ' ').slice(0, 100);
            const name = (el.getAttribute('name') || el.id || '').slice(0, 80);
            const href = el.href ? String(el.href).slice(0, 220) : '';
            const blob = (text + ' ' + name + ' ' + href).toLowerCase();
            if (q && !blob.includes(q)) continue;
            const inView = r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
            let occ;
            if (inView) {{
              const cx = Math.min(Math.max(r.x + r.width / 2, 0), vw - 1);
              const cy = Math.min(Math.max(r.y + r.height / 2, 0), vh - 1);
              const t = document.elementFromPoint(cx, cy);
              if (t && t !== el && !el.contains(t) && !t.contains(el)) occ = describe(t);
            }}
            const isField = el.tagName === 'INPUT' || el.tagName === 'TEXTAREA';
            out.push({{
              occluded_by: occ,
              focused: document.activeElement === el ? true : undefined,
              filled: isField && el.value ? el.value.length : undefined,
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || undefined,
              type: el.type || undefined,
              name: name || undefined,
              text: text || undefined,
              href: href || undefined,
              bbox: {{
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height)
              }},
              in_viewport: inView,
              screen: inView ? {{
                x: Math.round(r.x + r.width / 2),
                y: Math.round(r.y + r.height / 2 + chromeH)
              }} : undefined
            }});
            if (out.length >= maxN) break;
          }}
          return {{
            url: location.href,
            title: document.title,
            scrollY: Math.round(scrollY),
            innerHeight: innerHeight,
            scrollHeight: document.documentElement.scrollHeight,
            count: out.length,
            overlays: overlays,
            elements: out,
            text: clip((document.body && document.body.innerText) || '', 800)
          }};
        }}"""
        result = sess.call(
            "Runtime.evaluate",
            {"expression": f"({js})()", "returnByValue": True},
        )
        val = (result or {}).get("result", {}).get("value") or {}
        if not isinstance(val, dict):
            return _out({"ok": False, "error": str(val)})
        val["ok"] = True
        val["from"] = {"title": target.get("title"), "url": target.get("url")}
        return _out(val)
    finally:
        sess.close()


_SLIDER_HANDLE_RE = re.compile(r"(?:^|[\s_-])(slider|handle|thumb|knob|puzzle-?piece|drag(?:ger|gable)?)(?:$|[\s_-])", re.I)
_SLIDER_TRACK_RE = re.compile(r"(container|track|rail|bar|wrapper)", re.I)
_SLIDER_TARGET_RE = re.compile(r"(target|goal|end|dest)", re.I)


def _center(el: dict[str, Any]) -> tuple[int, int]:
    c = el.get("center_screen") or {}
    return int(c.get("x") or 0), int(c.get("y") or 0)


def _slider_hints(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generic « slide to verify » detection from class names / ARIA roles.

    Per frame: handle = role=slider or a slider/handle/thumb/knob element;
    destination = a target/goal element, else the right end of the track.
    """
    hints: list[dict[str, Any]] = []
    for fr in frames:
        els = fr.get("elements") or []
        sliderish = [
            e for e in els
            if e.get("role") == "slider"
            or _SLIDER_HANDLE_RE.search(str(e.get("className") or ""))
            or "slider" in str(e.get("className") or "").lower()
        ]
        if not sliderish:
            continue
        handles = [
            e for e in sliderish
            if (e.get("role") == "slider"
                or _SLIDER_HANDLE_RE.search(str(e.get("className") or "")))
            and not _SLIDER_TRACK_RE.search(str(e.get("className") or ""))
            and not _SLIDER_TARGET_RE.search(str(e.get("className") or ""))
            and "text" not in str(e.get("className") or "").lower()
            and e.get("tag") != "i"
        ]
        if not handles:
            continue
        # The real handle is the left-most, largest one.
        handle = sorted(
            handles,
            key=lambda e: (-(e["bbox_screen"]["w"] * e["bbox_screen"]["h"]), e["bbox_screen"]["x"]),
        )[0]
        hx, hy = _center(handle)
        hb = handle["bbox_screen"]
        track = None
        for e in els:
            b = e["bbox_screen"]
            if (e is not handle and _SLIDER_TRACK_RE.search(str(e.get("className") or ""))
                    and b["w"] > hb["w"] * 2 and b["h"] <= hb["h"] * 2
                    and b["x"] <= hb["x"] + hb["w"] and b["x"] + b["w"] > hb["x"] + hb["w"]
                    and abs((b["y"] + b["h"] // 2) - hy) <= max(b["h"], hb["h"])):
                if track is None or b["w"] > track["bbox_screen"]["w"]:
                    track = e
        target = next(
            (
                e for e in sliderish
                if e is not handle and e.get("tag") != "i"
                and _SLIDER_TARGET_RE.search(str(e.get("className") or ""))
                and e["bbox_screen"]["x"] > hb["x"]
            ),
            None,
        )
        if target is not None:
            x2, y2 = _center(target)
            basis = "target element"
        elif track is not None:
            tb = track["bbox_screen"]
            x2, y2 = tb["x"] + tb["w"] - hb["w"] // 2, hy
            basis = "track right end"
        else:
            continue
        if x2 - hx < 20:
            continue
        hints.append(
            {
                "frame": fr.get("type"),
                "frame_url": (fr.get("url") or "")[:120],
                "handle": {"x": hx, "y": hy},
                "to": {"x": x2, "y": y2},
                "basis": basis,
            }
        )
    return hints


def cmd_frames_snapshot(ns: argparse.Namespace) -> int:
    """Interactive controls in the page AND cross-origin iframes, with screen boxes.

    Screen coords = element viewport box + iframe offset + Chrome chrome height
    (outerHeight - innerHeight). Ready for vm_click / vm_drag.

    A ``query`` that matches nothing falls back to the full list (a filtered
    miss must never hide a widget), flagged with ``query_fallback``.
    """
    max_n = max(1, min(int(ns.max), 120))
    query = (ns.query or "").strip().lower()
    res = _frames_collect(query, max_n)
    if query and not res.get("count"):
        res = _frames_collect("", max_n)
        res["query_fallback"] = True
    res["slider_hints"] = _slider_hints(res.get("frames") or [])
    return _out(res)


def _frame_box(page_sess: Any, frame_id: str) -> dict[str, int] | None:
    """Viewport box of the <iframe> element hosting ``frame_id`` (any nesting)."""
    try:
        owner = page_sess.call("DOM.getFrameOwner", {"frameId": frame_id})
        bn = (owner or {}).get("backendNodeId")
        if not bn:
            return None
        box = page_sess.call("DOM.getBoxModel", {"backendNodeId": bn})
        q = ((box or {}).get("model") or {}).get("content") or []
        if len(q) < 8:
            return None
        xs, ys = q[0::2], q[1::2]
        return {
            "x": int(min(xs)), "y": int(min(ys)),
            "w": int(max(xs) - min(xs)), "h": int(max(ys) - min(ys)),
        }
    except Exception:
        return None


def _frames_collect(query: str, max_n: int) -> dict[str, Any]:
    page_sess, page_target = connect_page()
    try:
        meta = page_sess.call(
            "Runtime.evaluate",
            {
                "expression": (
                    "({url: location.href, title: document.title, "
                    "innerHeight, outerHeight, "
                    "chromeH: Math.max(0, outerHeight - innerHeight), "
                    "iframe: (() => { const f=document.querySelector('iframe'); "
                    "if(!f) return null; const r=f.getBoundingClientRect(); "
                    "return {x:Math.round(r.x),y:Math.round(r.y),"
                    "w:Math.round(r.width),h:Math.round(r.height)}; })() })"
                ),
                "returnByValue": True,
            },
        )
        page_meta = (meta or {}).get("result", {}).get("value") or {}
        chrome_h = int(page_meta.get("chromeH") or 0)
        iframe_off = page_meta.get("iframe") or {"x": 0, "y": 0}

        js_collect = f"""() => {{
          const q = {json.dumps(query)};
          const maxN = {max_n};
          const sels = [
            'a[href]', 'button', 'input', 'textarea', 'select',
            '[role="button"]', '[role="link"]', '[role="checkbox"]',
            '[role="slider"]', '[role="textbox"]',
            '[class*="slider"]', '[class*="Slider"]',
            '.slider', '.sliderTarget', '.sliderContainer', '.retryLink'
          ].join(',');
          const out = [];
          const seen = new Set();
          for (const el of document.querySelectorAll(sels)) {{
            const st = getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden') continue;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            const text = ((el.innerText || el.value || el.placeholder
              || el.getAttribute('aria-label') || '') + '')
              .trim().replace(/\\s+/g, ' ').slice(0, 100);
            const cls = (el.className && String(el.className).slice)
              ? String(el.className).slice(0, 120) : '';
            const name = (el.getAttribute('name') || el.id || '').slice(0, 80);
            const blob = (text + ' ' + name + ' ' + cls).toLowerCase();
            if (q && !blob.includes(q)) continue;
            const key = el.tagName + '|' + Math.round(r.x) + '|' + Math.round(r.y)
              + '|' + Math.round(r.width);
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({{
              tag: el.tagName.toLowerCase(),
              id: el.id || undefined,
              className: cls || undefined,
              role: el.getAttribute('role') || undefined,
              type: el.type || undefined,
              name: name || undefined,
              text: text || undefined,
              bbox: {{
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height)
              }}
            }});
            if (out.length >= maxN) break;
          }}
          return out;
        }}"""

        frames = []
        # Main page elements (screen = viewport + chromeH)
        try:
            main_els = page_sess.call(
                "Runtime.evaluate",
                {"expression": f"({js_collect})()", "returnByValue": True},
            )
            raw = (main_els or {}).get("result", {}).get("value") or []
        except CdpError:
            raw = []
        mapped = []
        for el in raw if isinstance(raw, list) else []:
            b = el.get("bbox") or {}
            sx = int(b.get("x") or 0)
            sy = int(b.get("y") or 0) + chrome_h
            mapped.append(
                {
                    **el,
                    "frame": "page",
                    "bbox_viewport": b,
                    "bbox_screen": {
                        "x": sx,
                        "y": sy,
                        "w": int(b.get("w") or 0),
                        "h": int(b.get("h") or 0),
                    },
                    "center_screen": {
                        "x": sx + int(b.get("w") or 0) // 2,
                        "y": sy + int(b.get("h") or 0) // 2,
                    },
                }
            )
        frames.append(
            {
                "type": "page",
                "url": page_meta.get("url") or page_target.get("url"),
                "elements": mapped,
            }
        )

        try:
            page_sess.call("DOM.enable")
            page_sess.call("DOM.getDocument", {"depth": 0})
        except Exception:
            pass
        for t in list_targets():
            if t.get("type") != "iframe":
                continue
            url = str(t.get("url") or "")
            if not url or url.startswith("chrome://"):
                continue
            # Each iframe has its own offset (several widgets may share a page).
            fbox = _frame_box(page_sess, str(t.get("id") or ""))
            ox = int((fbox or iframe_off or {}).get("x") or 0)
            oy = int((fbox or iframe_off or {}).get("y") or 0)
            try:
                fsess, _ = connect_target(t)
            except CdpError:
                continue
            try:
                els = fsess.call(
                    "Runtime.evaluate",
                    {"expression": f"({js_collect})()", "returnByValue": True},
                )
                raw = (els or {}).get("result", {}).get("value") or []
            except CdpError:
                raw = []
            finally:
                fsess.close()
            mapped_f = []
            for el in raw if isinstance(raw, list) else []:
                b = el.get("bbox") or {}
                sx = int(b.get("x") or 0) + ox
                sy = int(b.get("y") or 0) + oy + chrome_h
                mapped_f.append(
                    {
                        **el,
                        "frame": "iframe",
                        "frame_url": url[:220],
                        "bbox_viewport": b,
                        "bbox_screen": {
                            "x": sx,
                            "y": sy,
                            "w": int(b.get("w") or 0),
                            "h": int(b.get("h") or 0),
                        },
                        "center_screen": {
                            "x": sx + int(b.get("w") or 0) // 2,
                            "y": sy + int(b.get("h") or 0) // 2,
                        },
                    }
                )
            frames.append(
                {
                    "type": "iframe",
                    "url": url[:300],
                    "id": t.get("id"),
                    "box_screen": (
                        {
                            "x": fbox["x"], "y": fbox["y"] + chrome_h,
                            "w": fbox["w"], "h": fbox["h"],
                        }
                        if fbox else None
                    ),
                    "elements": mapped_f,
                }
            )

        return {
            "ok": True,
            "chrome_h": chrome_h,
            "iframe_offset": iframe_off,
            "url": page_meta.get("url"),
            "title": page_meta.get("title"),
            "frames": frames,
            "count": sum(len(f.get("elements") or []) for f in frames),
        }
    finally:
        page_sess.close()


def cmd_click_selector(ns: argparse.Namespace) -> int:
    sess, target = connect_page()
    try:
        js = f"""() => {{
          const el = document.querySelector({json.dumps(ns.selector)});
          if (!el) return {{ok:false, error:'not found'}};
          el.scrollIntoView({{block:'center', inline:'center'}});
          el.click();
          return {{ok:true, tag: el.tagName, text: (el.innerText||'').trim().slice(0,120)}};
        }}"""
        result = sess.call("Runtime.evaluate", {"expression": f"({js})()", "returnByValue": True})
        val = (result or {}).get("result", {}).get("value") or {"ok": False}
        val["url"] = target.get("url")
        return _out(val if isinstance(val, dict) else {"ok": False, "error": str(val)})
    finally:
        sess.close()


def cmd_eval(ns: argparse.Namespace) -> int:
    sess, target = connect_page()
    try:
        result = sess.call(
            "Runtime.evaluate",
            {"expression": ns.js, "returnByValue": True, "awaitPromise": True},
        )
        val = (result or {}).get("result", {})
        return _out(
            {
                "ok": True,
                "url": target.get("url"),
                "type": val.get("type"),
                "value": val.get("value"),
                "description": val.get("description"),
            }
        )
    finally:
        sess.close()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tabs")

    n = sub.add_parser("navigate")
    n.add_argument("--url", required=True)

    for nm in ("switch_tab", "close_tab"):
        sp = sub.add_parser(nm)
        sp.add_argument("--index", type=int, default=0)
        sp.add_argument("--match", default="")
    sub.add_parser("focus_info")
    sub.add_parser("reset_session")

    w = sub.add_parser("wait_load")
    w.add_argument("--timeout", type=float, default=15.0)

    h = sub.add_parser("html")
    h.add_argument("--max", type=int, default=12000)
    h.add_argument("--selector", default=None)

    t = sub.add_parser("text")
    t.add_argument("--max", type=int, default=8000)

    l = sub.add_parser("links")
    l.add_argument("--max", type=int, default=40)
    l.add_argument("--query", default=None)

    s = sub.add_parser("scroll")
    s.add_argument("--dy", type=int, default=600)
    s.add_argument("--dx", type=int, default=0)

    sn = sub.add_parser("snapshot")
    sn.add_argument("--max", type=int, default=60)
    sn.add_argument("--query", default=None)

    fs = sub.add_parser("frames_snapshot")
    fs.add_argument("--max", type=int, default=60)
    fs.add_argument("--query", default=None)

    c = sub.add_parser("click_selector")
    c.add_argument("--selector", required=True)

    e = sub.add_parser("eval")
    e.add_argument("--js", required=True)

    ns = p.parse_args(argv[1:])
    try:
        if ns.cmd == "tabs":
            return cmd_tabs(ns)
        if ns.cmd == "navigate":
            return cmd_navigate(ns)
        if ns.cmd == "reset_session":
            return cmd_reset_session(ns)
        if ns.cmd == "switch_tab":
            return cmd_switch_tab(ns)
        if ns.cmd == "close_tab":
            return cmd_close_tab(ns)
        if ns.cmd == "focus_info":
            return cmd_focus_info(ns)
        if ns.cmd == "wait_load":
            return cmd_wait_load(ns)
        if ns.cmd == "html":
            return cmd_html(ns)
        if ns.cmd == "text":
            return cmd_text(ns)
        if ns.cmd == "links":
            return cmd_links(ns)
        if ns.cmd == "scroll":
            return cmd_scroll(ns)
        if ns.cmd == "snapshot":
            return cmd_snapshot(ns)
        if ns.cmd == "frames_snapshot":
            return cmd_frames_snapshot(ns)
        if ns.cmd == "click_selector":
            return cmd_click_selector(ns)
        if ns.cmd == "eval":
            return cmd_eval(ns)
        return 2
    except CdpError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    except Exception as exc:
        # A raw traceback is cut off before the exception, so the bot invents
        # a cause. Return the error and let the next call reconnect.
        msg = f"{type(exc).__name__}: {exc}"
        print(json.dumps({"ok": False, "error": msg}))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
