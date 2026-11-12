/**
 * Chrome CDP tools for Pi (generic web nav — no site-specific logic).
 *
 * Find controls in the DOM (screen=x,y). Act only with VNC (vm_click / vm_drag /
 * vm_scroll) so the pointer moves like a hand. Never CDP-click.
 * Reveal off-screen targets with vm_scroll (VNC wheel), not CDP jump.
 * Never attach screenshots here.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Json = Record<string, unknown>;

function env(name: string): string {
  return (process.env[name] || "").trim();
}

function apiConfig(): { base: string; token: string; bot: string } | null {
  const base = env("AUTONOMOUS_API_BASE").replace(/\/$/, "");
  const token = env("AUTONOMOUS_TOKEN");
  const bot = env("AUTONOMOUS_BOT");
  if (!base || !token || !bot) return null;
  return { base, token, bot };
}

async function api(
  method: string,
  path: string,
  body?: Json,
): Promise<{ ok: boolean; status: number; data: any }> {
  const cfg = apiConfig();
  if (!cfg) {
    return {
      ok: false,
      status: 0,
      data: {
        error:
          "Autonomous API not configured (AUTONOMOUS_API_BASE / TOKEN / BOT).",
      },
    };
  }
  const res = await fetch(`${cfg.base}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${cfg.token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data: any = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  } else {
    data = { message: await res.text() };
  }
  return { ok: res.ok, status: res.status, data };
}

function textResult(text: string, details: Json = {}) {
  return {
    content: [{ type: "text" as const, text }],
    details,
  };
}

function errMessage(data: any, status: number): string {
  return data?.message || data?.error || `HTTP ${status}`;
}

function botPath(suffix: string): string {
  const cfg = apiConfig();
  return `/bots/${encodeURIComponent(cfg!.bot)}${suffix}`;
}

function sliderNote(hints: any): string {
  const list = Array.isArray(hints) ? hints : [];
  return list
    .map(
      (h: any) =>
        `\nSLIDE-TO-VERIFY WIDGET on screen: do ONE ` +
        `vm_drag(x=${h.handle?.x}, y=${h.handle?.y}, x2=${h.to?.x}, y2=${h.to?.y}) ` +
        `now (exact coordinates from the DOM — do not vm_ground it), then browser_wait_load.`,
    )
    .join("");
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "browser_tabs",
    label: "Browser tabs",
    description:
      "List open Chrome page tabs via CDP in the bot desk. Chrome must be running " +
      "(e.g. bot-chrome URL). Use before browser_navigate / browser_text.",
    parameters: Type.Object({}),
    execute: async () => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const res = await api("GET", botPath("/browser/tabs"));
      if (!res.ok) {
        return textResult(`browser_tabs failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const pages = res.data?.pages || [];
      const lines = pages.map(
        (p: any, i: number) =>
          `${i + 1}. ${p.title || "(no title)"} — ${p.url || ""}`,
      );
      return textResult(
        lines.length ? `Chrome pages:\n${lines.join("\n")}` : "No Chrome page targets.",
        { ok: true, pages },
      );
    },
  });

  pi.registerTool({
    name: "browser_switch_tab",
    label: "Browser switch tab",
    description:
      "Bring another Chrome tab to the front (e.g. after a click opened a new tab or " +
      "window): every browser_* tool then acts on that tab. Pick it by 1-based index " +
      "from browser_tabs, or by a substring of its URL / title.",
    parameters: Type.Object({
      index: Type.Optional(Type.Number({ description: "1-based tab number (browser_tabs order)" })),
      match: Type.Optional(Type.String({ description: "Substring of the tab URL or title" })),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const res = await api("POST", botPath("/browser/switch_tab"), {
        index: params.index != null ? Number(params.index) : 0,
        match: params.match ? String(params.match) : "",
      });
      if (!res.ok || res.data?.ok === false) {
        return textResult(
          `browser_switch_tab failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      return textResult(
        `Active tab is now: ${res.data?.title || "(no title)"} — ${res.data?.url || ""}`,
        { ok: true },
      );
    },
  });

  pi.registerTool({
    name: "browser_close_tab",
    label: "Browser close tab",
    description:
      "Close a Chrome tab (default: the active one) — e.g. a popup you are done with. " +
      "The last tab is never closed. Afterwards browser_tabs shows what remains.",
    parameters: Type.Object({
      index: Type.Optional(Type.Number({ description: "1-based tab number (default: active tab)" })),
      match: Type.Optional(Type.String({ description: "Substring of the tab URL or title" })),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const res = await api("POST", botPath("/browser/close_tab"), {
        index: params.index != null ? Number(params.index) : 0,
        match: params.match ? String(params.match) : "",
      });
      if (!res.ok || res.data?.ok === false) {
        return textResult(
          `browser_close_tab failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const pages = Array.isArray(res.data?.pages) ? res.data.pages : [];
      return textResult(
        `Closed ${res.data?.closed || "tab"}. Remaining tabs:\n` +
          pages.map((p: any, i: number) => `${i + 1}. ${p.title || "(no title)"} — ${p.url || ""}`).join("\n"),
        { ok: true },
      );
    },
  });

  pi.registerTool({
    name: "browser_navigate",
    label: "Browser navigate",
    description:
      "FIRST OPEN ONLY. The server refuses this as soon as a page is already " +
      "open (code=url_change), including a reload or a link you can see. " +
      "The first URL must be one the user wrote, or that site's homepage — " +
      "a guessed path is refused (code=invented_url). After the open: click " +
      "what you see (shortest path). Google search: click the address bar, " +
      "type the query, Enter. Reload: click the refresh icon. Never type a " +
      "site URL into the address bar.",
    parameters: Type.Object({
      url: Type.String({ description: "Absolute URL, e.g. https://example.com" }),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const res = await api("POST", botPath("/browser/navigate"), {
        url: String(params.url || "").trim(),
      });
      if (!res.ok) {
        return textResult(
          `browser_navigate failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const page = res.data?.page ? "\n\n" + res.data.page : "";
      return textResult(
        `Navigated to ${res.data?.navigated || params.url}.` +
          `${sliderNote(res.data?.slider_hints)}` +
          page,
        { ok: true, navigated: res.data?.navigated },
      );
    },
  });

  pi.registerTool({
    name: "browser_wait_load",
    label: "Browser wait load",
    description:
      "Wait until the active page finished loading (document.readyState complete), " +
      "bounded by a timeout. vm_click, vm_drag and Return already wait and " +
      "return the new page — do not call this after them. Use it only after " +
      "the first browser_navigate if that result has no page. Never blocks " +
      "forever: timed_out=true means the page is usually already usable.",
    parameters: Type.Object({
      timeout: Type.Optional(
        Type.Number({ description: "Max seconds to wait (default 15, max 30)" }),
      ),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {};
      if (params.timeout != null) body.timeout = Number(params.timeout);
      const res = await api("POST", botPath("/browser/wait_load"), body);
      if (!res.ok) {
        return textResult(
          `browser_wait_load failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const d = res.data || {};
      const head = d.loaded
        ? `Page loaded after ${d.waited_s}s.`
        : `Timeout after ${d.waited_s}s (readyState=${d.ready_state ?? "unreachable"}) — ` +
          "page still loading; it may already be usable, continue with " +
          "browser_snapshot / vm_look.";
      return textResult(`${head}\nurl: ${d.url || "?"}\ntitle: ${d.title || "?"}${sliderNote(d.slider_hints)}`, {
        ok: true,
        loaded: d.loaded,
        timed_out: d.timed_out,
      });
    },
  });

  pi.registerTool({
    name: "browser_reset_session",
    label: "Browser reset session",
    description:
      "Forget this browsing session: cookies, cache and storage of the current site " +
      "(like opening a brand-new private window). Use it ONLY when vm_look confirms a " +
      "page that just says access is restricted / blocked with nothing to act on: " +
      "such a block is tied to the session state, not to you. NOT for a login page, " +
      "a verification widget you can still act on, or a slow page. " +
      "Then click the refresh icon and start over from what you see (fresh visit). " +
      "Do not browser_navigate to another URL. " +
      "You will be logged out of that site; log in again afterwards. At most 2 resets " +
      "per site, then report to the user.",
    parameters: Type.Object({}),
    execute: async () => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const res = await api("POST", botPath("/browser/reset_session"), {});
      if (!res.ok) {
        return textResult(
          `browser_reset_session failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const d = res.data || {};
      return textResult(
        `Session cleared for ${d.origin || "current site"} (${(d.cleared || []).join(", ")}). ` +
          "Now click the refresh icon and begin again from what you see. Do not browser_navigate.",
        { ok: true, cleared: d.cleared },
      );
    },
  });

  pi.registerTool({
    name: "browser_text",
    label: "Browser text",
    description:
      "Read visible text of the active Chrome page (innerText, truncated). " +
      "vm_click and browser_snapshot already include an excerpt: call this " +
      "only when that excerpt is missing the fact you need. Prefer over dumping HTML.",
    parameters: Type.Object({
      max_chars: Type.Optional(
        Type.Number({ description: "Max characters (default 8000)" }),
      ),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {};
      if (params.max_chars != null) body.max_chars = Number(params.max_chars);
      const res = await api("POST", botPath("/browser/text"), body);
      if (!res.ok) {
        return textResult(`browser_text failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const d = res.data || {};
      const header = `url: ${d.url || "?"}\ntitle: ${d.title || "?"}\nchars: ${d.chars || 0}` +
        (d.truncated ? " (truncated)" : "");
      return textResult(`${header}\n\n${d.text || "(empty)"}`, {
        ok: true,
        url: d.url,
        truncated: d.truncated,
      });
    },
  });

  pi.registerTool({
    name: "browser_links",
    label: "Browser links",
    description:
      "List links (text + href) on the page. Optional query filters by substring " +
      "on text/href (case-insensitive). Useful to find a product/result without vision.",
    parameters: Type.Object({
      query: Type.Optional(
        Type.String({ description: "Substring filter on link text or href" }),
      ),
      max_links: Type.Optional(
        Type.Number({ description: "Max links (default 40)" }),
      ),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {};
      if (params.query) body.query = String(params.query);
      if (params.max_links != null) body.max_links = Number(params.max_links);
      const res = await api("POST", botPath("/browser/links"), body);
      if (!res.ok) {
        return textResult(`browser_links failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const links = res.data?.links || [];
      const lines = links.map(
        (L: any, i: number) => `${i + 1}. ${L.text || ""} → ${L.href || ""}`,
      );
      return textResult(
        `url: ${res.data?.url || "?"}\n${links.length} link(s):\n${lines.join("\n") || "(none)"}`,
        { ok: true, links, count: links.length },
      );
    },
  });

  pi.registerTool({
    name: "browser_html",
    label: "Browser HTML",
    description:
      "Read page HTML (truncated) or a CSS selector's outerHTML. Heavy — prefer " +
      "browser_text / browser_links first.",
    parameters: Type.Object({
      selector: Type.Optional(
        Type.String({ description: "Optional CSS selector" }),
      ),
      max_chars: Type.Optional(
        Type.Number({ description: "Max characters (default 12000)" }),
      ),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {};
      if (params.selector) body.selector = String(params.selector);
      if (params.max_chars != null) body.max_chars = Number(params.max_chars);
      const res = await api("POST", botPath("/browser/html"), body);
      if (!res.ok) {
        return textResult(`browser_html failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const d = res.data || {};
      return textResult(
        `url: ${d.url || "?"}\nchars: ${d.chars || 0}` +
          (d.truncated ? " (truncated)" : "") +
          `\n\n${d.html || "(empty)"}`,
        { ok: true, truncated: d.truncated },
      );
    },
  });

  pi.registerTool({
    name: "browser_scroll",
    label: "Browser scroll (CDP)",
    description:
      "CDP window.scrollBy — detectable jump. Prefer vm_scroll (VNC wheel) on " +
      "anti-bot pages. dy>0 scrolls content down.",
    parameters: Type.Object({
      dy: Type.Optional(Type.Number({ description: "Vertical pixels (default 600)" })),
      dx: Type.Optional(Type.Number({ description: "Horizontal pixels (default 0)" })),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const res = await api("POST", botPath("/browser/scroll"), {
        dy: params.dy != null ? Number(params.dy) : 600,
        dx: params.dx != null ? Number(params.dx) : 0,
      });
      if (!res.ok) {
        return textResult(
          `browser_scroll failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const pos = res.data?.position || {};
      return textResult(
        `Scrolled. position y=${pos.y ?? "?"} height=${pos.height ?? "?"}.`,
        { ok: true, position: pos },
      );
    },
  });

  pi.registerTool({
    name: "browser_snapshot",
    label: "Browser DOM snapshot",
    description:
      "Read interactive controls WITHOUT scrolling or clicking. Each in-view " +
      "control has screen=x,y = desk pixels for vm_click (real mouse — never " +
      "browser_click_selector). Skip [COVERED] controls until the overlay is " +
      "gone. Off-screen: vm_scroll first. Optional query filters text/name/href. " +
      "vm_ground only if the control is absent here.",
    parameters: Type.Object({
      max_elements: Type.Optional(
        Type.Number({ description: "Max controls to return (default 60, max 120)" }),
      ),
      query: Type.Optional(
        Type.String({ description: "Substring filter on text/name/href" }),
      ),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {
        max_elements:
          params.max_elements != null ? Number(params.max_elements) : 60,
      };
      if (params.query) body.query = String(params.query);
      const res = await api("POST", botPath("/browser/snapshot"), body);
      if (!res.ok || res.data?.ok === false) {
        return textResult(
          `browser_snapshot failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const d = res.data || {};
      const els = Array.isArray(d.elements) ? d.elements : [];
      const lines = [
        "Click with vm_click at screen= (real mouse). Never browser_click_selector.",
        `url: ${d.url || "?"}`,
        `title: ${d.title || "?"}`,
        `scrollY: ${d.scrollY ?? "?"} / height: ${d.scrollHeight ?? "?"} (viewport ${d.innerHeight ?? "?"})`,
        `controls: ${d.count ?? els.length}`,
        "",
      ];
      const overlays = Array.isArray(d.overlays) ? d.overlays : [];
      if (overlays.length) {
        lines.push(
          "!! BLOCKING OVERLAY — vm_click its screen= point first (real mouse), then snapshot again:",
        );
        for (const ov of overlays) {
          lines.push(`   [${ov.kind}] "${String(ov.text || "").slice(0, 200)}"`);
          for (const c of Array.isArray(ov.controls) ? ov.controls : []) {
            const s = c.screen || {};
            lines.push(
              `   - ${c.tag} "${String(c.text || "").slice(0, 60)}" screen=${s.x},${s.y}`,
            );
          }
        }
        lines.push("");
      }
      for (const el of els) {
        const bits = [
          el.in_viewport === false ? "[offscreen]" : "[in-view]",
          el.occluded_by ? `[COVERED by ${el.occluded_by}]` : "",
          el.focused ? "[FOCUSED]" : "",
          typeof el.filled === "number" ? `[filled ${el.filled} chars]` : "",
          el.tag || "?",
          el.type ? `type=${el.type}` : "",
          el.role ? `role=${el.role}` : "",
          el.text ? `"${String(el.text).slice(0, 80)}"` : "",
          el.name ? `name=${el.name}` : "",
          el.href ? `→ ${String(el.href).slice(0, 100)}` : "",
          el.screen ? `screen=${el.screen.x},${el.screen.y}` : "",
        ].filter(Boolean);
        lines.push("- " + bits.join(" "));
      }
      if (!els.length) {
        lines.push(
          "(no control in the top document. If a form or widget is visible, " +
            "call browser_frames_snapshot. If it is only drawn, vm_ground it. " +
            "Do not invent a coordinate.)",
        );
      }
      if (d.text) {
        lines.push("", "Visible text:", String(d.text).slice(0, 800));
      }
      return textResult(lines.join("\n"), {
        ok: true,
        count: d.count,
        scrollY: d.scrollY,
      });
    },
  });

  pi.registerTool({
    name: "browser_frames_snapshot",
    label: "Browser frames snapshot",
    description:
      "Like browser_snapshot, and also walks cross-origin iframes. screen= points " +
      "are for vm_click / vm_drag (real mouse), not a CDP click. A « SLIDER WIDGET » " +
      "line is one vm_drag at those coordinates. Prefer calling it WITHOUT query. " +
      "A drawn widget with no controls: vm_ground inside the box, do not click its center.",
    parameters: Type.Object({
      max_elements: Type.Optional(
        Type.Number({ description: "Max controls per frame (default 60)" }),
      ),
      query: Type.Optional(
        Type.String({ description: "Substring filter on text/class/id" }),
      ),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {
        max_elements:
          params.max_elements != null ? Number(params.max_elements) : 60,
      };
      if (params.query) body.query = String(params.query);
      const res = await api("POST", botPath("/browser/frames_snapshot"), body);
      if (!res.ok || res.data?.ok === false) {
        return textResult(
          `browser_frames_snapshot failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const d = res.data || {};
      const lines = [
        `url: ${d.url || "?"}`,
        `chrome_h: ${d.chrome_h ?? "?"}`,
        `controls: ${d.count ?? 0}`,
      ];
      if (d.query_fallback) {
        lines.push(
          "NOTE: nothing matched your query — showing ALL controls instead " +
            "(a widget is often not named what you expect; run this tool WITHOUT query).",
        );
      }
      for (const h of Array.isArray(d.slider_hints) ? d.slider_hints : []) {
        lines.push(
          `SLIDER WIDGET detected (${h.frame}): drag the handle with ONE ` +
            `vm_drag(x=${h.handle?.x}, y=${h.handle?.y}, x2=${h.to?.x}, y2=${h.to?.y}) ` +
            `[end = ${h.basis}]`,
        );
      }
      lines.push("");
      for (const fr of Array.isArray(d.frames) ? d.frames : []) {
        const fb = fr.box_screen;
        lines.push(
          `## ${fr.type || "frame"} ${(fr.url || "").toString().slice(0, 100)}`,
        );
        if (fr.type === "iframe" && !(fr.elements || []).length && fb && fb.w > 40 && fb.h > 20) {
          lines.push(
            "- (no readable controls: the widget is drawn inside the iframe — " +
              "vm_look, then vm_ground its checkbox or button. Do not click the box center.)",
          );
        }
        for (const el of Array.isArray(fr.elements) ? fr.elements : []) {
          const c = el.center_screen || {};
          const bits = [
            el.tag || "?",
            el.className ? `class=${String(el.className).slice(0, 60)}` : "",
            el.id ? `id=${el.id}` : "",
            el.text ? `"${String(el.text).slice(0, 60)}"` : "",
            c.x != null ? `screen=${c.x},${c.y}` : "",
          ].filter(Boolean);
          lines.push("- " + bits.join(" "));
        }
        lines.push("");
      }
      return textResult(lines.join("\n"), {
        ok: true,
        count: d.count,
        chrome_h: d.chrome_h,
      });
    },
  });

  pi.registerTool({
    name: "browser_click_selector",
    label: "Browser click selector",
    description:
      "CDP click + scrollIntoView. Do not use it: anti-bot systems flag a click " +
      "with no real pointer. Use vm_click / vm_drag at the snapshot screen= point.",
    parameters: Type.Object({
      selector: Type.String({ description: "CSS selector" }),
    }),
    execute: async (_id, params) => {
      if (!apiConfig()) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const res = await api("POST", botPath("/browser/click_selector"), {
        selector: String(params.selector || ""),
      });
      if (!res.ok || res.data?.ok === false) {
        return textResult(
          `browser_click_selector failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const d = res.data || {};
      return textResult(
        `Clicked ${d.tag || "element"}: ${(d.text || "").slice(0, 80)}`,
        { ok: true, tag: d.tag },
      );
    },
  });
}
