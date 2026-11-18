/**
 * Companion avatar engine (SVG + CSS states).
 * States: work | notify | await | wait | idle | tracking
 * - idle: no animation, eyes closed
 * - await/wait: jump (needs user action)
 * - work: busy animation
 * - notify: eyes open + occasional twitch
 * - tracking: eyes follow pointer (typically idle + hover)
 */
import { SWATCHES } from "./swatches.js";

const TWITCH = ["ear-l", "tail", "ear-r", "paw-r"];
const NOTINT = '[data-part^="foot"],[data-part="beak"],[data-id="beak"]';
const NS = "http://www.w3.org/2000/svg";

const STATE_ALIASES = { await: "wait" };

function normalizeState(st) {
  const s = String(st || "idle");
  return STATE_ALIASES[s] || s;
}

function hexToHsl(h) {
  h = h.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const mx = Math.max(r, g, b);
  const mn = Math.min(r, g, b);
  const l = (mx + mn) / 2;
  let H = 0;
  let S = 0;
  if (mx !== mn) {
    const d = mx - mn;
    S = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
    H =
      mx === r
        ? (g - b) / d + (g < b ? 6 : 0)
        : mx === g
          ? (b - r) / d + 2
          : (r - g) / d + 4;
    H *= 60;
  }
  return [H, S * 100, l * 100];
}

function prepareTint(svg, rig) {
  if (rig && rig.tintFills) {
    svg.querySelectorAll("[fill]").forEach((el) => {
      const f = (el.getAttribute("fill") || "").toLowerCase();
      if (!rig.tintFills.includes(f) || el.closest(rig.tintKeep)) return;
      const [H, S, L] = hexToHsl(f);
      el.dataset.hsl = [H, S, L].map((v) => v.toFixed(1)).join(",");
      el.classList.add("tint", "mono");
    });
    return;
  }
  if (rig && Array.isArray(rig.mono)) {
    svg.querySelectorAll("[fill]").forEach((el) => {
      const f = el.getAttribute("fill");
      if (!/^#/.test(f)) return;
      const [H, S, L] = hexToHsl(f);
      const p = el.closest("[data-part]");
      const n = p && p.dataset.part;
      const hoof =
        Array.isArray(rig.hoofParts) &&
        rig.hoofParts.includes(n) &&
        H > 270 &&
        H < 330 &&
        L < 85;
      if (!(rig.mono.includes(n) && L >= 30 && L <= 93) && !hoof) return;
      el.dataset.hsl = [H, S, L].map((v) => v.toFixed(1)).join(",");
      el.classList.add("tint", "mono");
    });
    return;
  }
  svg.querySelectorAll("[fill]").forEach((el) => {
    const f = el.getAttribute("fill");
    if (!/^#/.test(f)) return;
    if (el.closest(NOTINT)) return;
    const [H, S, L] = hexToHsl(f);
    if (L < 30 || L > 85) return;
    if ((H > 330 || H < 15) && L > 72) return;
    el.dataset.hsl = [H, S, L].map((v) => v.toFixed(1)).join(",");
    el.classList.add("tint");
  });
}

function baseColor(svg) {
  let best = null;
  let area = 0;
  svg.querySelectorAll(".tint").forEach((el) => {
    const b = el.getBBox();
    const a = b.width * b.height;
    if (a > area) {
      area = a;
      best = el;
    }
  });
  return best ? best.dataset.hsl.split(",").map(Number) : [0, 50, 50];
}

function partBox(svg, name) {
  const g = svg.querySelector(`[data-part="${name}"]`);
  return g ? { g, b: g.getBBox() } : null;
}

function setPivots(svg, rig) {
  const body = partBox(svg, "body");
  const bc = body
    ? { x: body.b.x + body.b.width / 2, y: body.b.y + body.b.height / 2 }
    : null;
  const set = (n, o) => {
    const p = partBox(svg, n);
    if (p) p.g.style.transformOrigin = o;
  };
  set("ear-l", "50% 95%");
  set("ear-r", "50% 95%");
  set("paw-l", "50% 8%");
  set("paw-r", "50% 8%");
  set("leg-back-l", "50% 10%");
  set("leg-back-r", "50% 10%");
  const t = partBox(svg, "tail");
  if (t && bc) {
    const cl = (v) => Math.max(0, Math.min(100, v));
    const px = cl(((bc.x - t.b.x) / t.b.width) * 100);
    const py = cl(((bc.y - t.b.y) / t.b.height) * 100);
    t.g.style.transformOrigin = `${px.toFixed(0)}% ${Math.max(py, 60).toFixed(0)}%`;
  }
  if (rig && rig.pivots) {
    Object.entries(rig.pivots).forEach(([n, o]) => {
      if (typeof o === "string") set(n, o);
    });
    if (rig.pivots.absPivots) {
      Object.entries(rig.pivots.absPivots).forEach(([n, [x, y]]) => {
        const p = partBox(svg, n);
        if (p) {
          p.g.style.transformOrigin = `${(((x - p.b.x) / p.b.width) * 100).toFixed(2)}% ${(((y - p.b.y) / p.b.height) * 100).toFixed(2)}%`;
        }
      });
    }
  }
}

function rigEyes(svg) {
  const g = svg.querySelector('[data-part="eyes-open"]');
  if (!g) return;
  const kids = [...g.children];
  const bx = kids.map((k) => {
    const b = k.getBBox();
    return b.x + b.width / 2;
  });
  const mid = (Math.min(...bx) + Math.max(...bx)) / 2;
  ["l", "r"].forEach((s) => {
    const side = document.createElementNS(NS, "g");
    side.setAttribute("class", `eye-side eye-${s}`);
    kids.forEach((k, i) => {
      if (bx[i] < mid === (s === "l")) side.appendChild(k);
    });
    const gl = document.createElementNS(NS, "g");
    gl.setAttribute("class", "glints");
    [...side.children].forEach((k) => {
      if ((k.getAttribute("fill") || "").toLowerCase() === "#ffffff") gl.appendChild(k);
    });
    side.appendChild(gl);
    g.appendChild(side);
  });
}

/**
 * Tight square crop so the companion fills the badge.
 * fill < 1 zooms in (replaces a CSS scale on the root <svg>, which Firefox
 * Android does not paint inside a <button>).
 * A 0×0 bbox (getBBox before layout, common on Firefox Android) must not
 * replace the authored viewBox with "0 0 0 0".
 */
function fitViewBox(svg, fill = 0.94) {
  const rig = svg.querySelector(".rig");
  if (!rig) return false;
  let b;
  try {
    b = rig.getBBox();
  } catch {
    return false;
  }
  if (!b || !(b.width > 0) || !(b.height > 0)) return false;
  const pad = Math.max(b.width, b.height) * 0.01;
  const w = Math.max(b.width, b.height) * fill;
  if (!(w > 0)) return false;
  svg.setAttribute(
    "viewBox",
    `${(b.x + b.width / 2 - w / 2).toFixed(0)} ${(b.y + b.height - w + pad).toFixed(0)} ${w.toFixed(0)} ${w.toFixed(0)}`
  );
  return true;
}

export class Avatar {
  /**
   * @param {string} key character id
   * @param {HTMLElement} host mount node
   * @param {{ svg: string, rig?: object|null }} character catalog entry
   */
  constructor(key, host, character) {
    this.key = key;
    this.host = host;
    this.rig = (character && character.rig) || null;
    this.logicalState = "idle";
    this.displayState = "idle";
    this._trackBound = false;
    this._onEnter = null;
    this._onLeave = null;
    this._onMove = null;
    this._trackZone = null;

    host.classList.add("av");
    host.innerHTML = character.svg;
    const svg = (this.svg = host.querySelector("svg"));
    if (!svg) throw new Error(`Avatar ${key}: missing <svg>`);
    const wrap = document.createElementNS(NS, "g");
    wrap.setAttribute("class", "rig");
    [...svg.childNodes].forEach((n) => wrap.appendChild(n));
    svg.appendChild(wrap);

    prepareTint(svg, this.rig);
    this.base = baseColor(svg);
    setPivots(svg, this.rig);
    host.dataset.av = key;
    rigEyes(svg);
    if (!fitViewBox(svg)) {
      requestAnimationFrame(() => {
        if (this.svg === svg) fitViewBox(svg);
      });
    }
    this.timer = null;
    this.setState("idle");
  }

  destroy() {
    clearInterval(this.timer);
    this.timer = null;
    this.unbindTracking();
    this.host.innerHTML = "";
    this.host.classList.remove("av");
    delete this.host.dataset.av;
    delete this.host.dataset.state;
    delete this.host.dataset.eyes;
  }

  setColor(i) {
    this.colorIndex = i;
    const sw = SWATCHES[i];
    const base = this.base;
    this.svg.querySelectorAll(".tint").forEach((el) => {
      if (!sw || sw[1] == null) {
        el.style.fill = "";
        return;
      }
      const [H, S, L] = el.dataset.hsl.split(",").map(Number);
      if (el.classList.contains("mono")) {
        const l = Math.max(25, Math.min(90, L * (1 + sw[3] * 0.6)));
        el.style.fill = `hsl(${sw[1]} ${Math.min(sw[2], 80).toFixed(0)}% ${l.toFixed(0)}%)`;
        return;
      }
      const h = (sw[1] + (H - base[0]) + 360) % 360;
      const s2 = sw[2] * Math.max(0.5, Math.min(1.3, S / base[1]));
      const l = Math.max(12, Math.min(92, L * (1 + sw[3])));
      el.style.fill = `hsl(${h.toFixed(0)} ${s2.toFixed(0)}% ${l.toFixed(0)}%)`;
    });
  }

  eyes(open) {
    this.host.dataset.eyes = open ? "open" : "closed";
    if (!open) this.look(0, 0);
  }

  setState(st) {
    const logical = String(st || "idle");
    this.logicalState = logical === "await" ? "await" : logical;
    const css = normalizeState(logical === "await" ? "await" : logical);
    this.displayState = css;
    // Keep data-state as await when requested (CSS aliases it); idle/tracking/work/notify as-is.
    this.host.dataset.state = logical === "await" ? "await" : css;
    clearInterval(this.timer);
    this.timer = null;
    this.eyes(css === "notify");
    if (css === "notify") {
      let i = 0;
      const L = (this.rig && this.rig.twitch) || TWITCH;
      const go = () => this.twitch(L[i++ % L.length]);
      setTimeout(go, 600);
      this.timer = setInterval(go, 5000);
    }
    if (css === "tracking") this.eyes(true);
    if (css === "idle") this.eyes(false);
  }

  twitch(n) {
    let p = this.svg.querySelector(`[data-part="${n}"]`);
    if (!p) {
      n = "tail";
      p = this.svg.querySelector('[data-part="tail"]');
    }
    if (!p) return;
    const ln = ((this.rig && this.rig.links) || {})[n] || [];
    const ps = [
      p,
      ...ln.map((m) => this.svg.querySelector(`[data-part="${m}"]`)).filter(Boolean),
    ];
    ps.forEach((q) => q.classList.remove("twitch-" + n));
    void p.getBBox();
    ps.forEach((q) => q.classList.add("twitch-" + n));
    setTimeout(() => ps.forEach((q) => q.classList.remove("twitch-" + n)), 1000);
  }

  look(dx, dy) {
    this.svg.querySelectorAll(".eye-side").forEach((s) => {
      s.style.transform = `translate(${dx * 9}px,${dy * 7}px)`;
      const gl = s.querySelector(".glints");
      if (gl) gl.style.transform = `translate(${dx * 7}px,${dy * 6}px)`;
    });
  }

  /**
   * Idle hover → tracking (eyes follow). Other states ignore pointer.
   * @param {HTMLElement} zone
   */
  bindIdleTracking(zone) {
    this.unbindTracking();
    if (!zone) return;
    this._trackZone = zone;
    this._onEnter = () => {
      if (this.logicalState !== "idle") return;
      this.host.dataset.state = "tracking";
      this.displayState = "tracking";
      this.eyes(true);
    };
    this._onLeave = () => {
      if (this.logicalState !== "idle") return;
      this.host.dataset.state = "idle";
      this.displayState = "idle";
      this.eyes(false);
    };
    this._onMove = (e) => {
      if (this.logicalState !== "idle") return;
      if (this.displayState !== "tracking") return;
      const r = this.host.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height * 0.45;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const d = Math.hypot(dx, dy) || 1;
      const k = Math.min(1, d / 120);
      this.look((dx / d) * k, (dy / d) * k);
    };
    zone.addEventListener("pointerenter", this._onEnter);
    zone.addEventListener("pointerleave", this._onLeave);
    zone.addEventListener("pointermove", this._onMove);
    this._trackBound = true;
  }

  unbindTracking() {
    if (!this._trackBound || !this._trackZone) return;
    this._trackZone.removeEventListener("pointerenter", this._onEnter);
    this._trackZone.removeEventListener("pointerleave", this._onLeave);
    this._trackZone.removeEventListener("pointermove", this._onMove);
    this._trackBound = false;
    this._trackZone = null;
  }
}

export { normalizeState, SWATCHES };
