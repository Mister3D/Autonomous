/** Per-bot preference: show LLM step timings inside tool groups + orb phase. */

import { reactive } from "vue";

const PREFIX = "autonomous.showRunTimings:";

/** @type {Record<string, boolean>} */
const cache = reactive({});

function storageKey(bot) {
  return `${PREFIX}${String(bot || "").trim()}`;
}

function readStored(bot) {
  const name = String(bot || "").trim();
  if (!name) return false;
  try {
    return localStorage.getItem(storageKey(name)) === "1";
  } catch {
    return false;
  }
}

/** Reactive read for the current bot (hydrates from localStorage once). */
export function isShowRunTimings(bot) {
  const name = String(bot || "").trim();
  if (!name) return false;
  if (!(name in cache)) cache[name] = readStored(name);
  return !!cache[name];
}

export function setShowRunTimings(bot, on) {
  const name = String(bot || "").trim();
  if (!name) return;
  const next = !!on;
  cache[name] = next;
  try {
    localStorage.setItem(storageKey(name), next ? "1" : "0");
  } catch {
    /* private mode */
  }
}

/** Compact duration: 842ms · 12s · 1m 05s · 1h 02m (same idea as ToolGroup). */
export function formatDurationMs(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 1000) return `${Math.round(n)}ms`;
  const sec = n / 1000;
  if (sec < 60) {
    return sec < 10 ? `${sec.toFixed(1)}s` : `${Math.round(sec)}s`;
  }
  const totalSec = Math.round(sec);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) {
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }
  return s > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${m}m`;
}
