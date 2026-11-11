/** Last update-check result, so the home line does not refetch on every load. */

const KEY = "autonomous-update-status";
/** Same window as the server cache in updates.py (CACHE_TTL_S). */
const TTL_S = 24 * 3600;

export function readUpdateStatus() {
  try {
    const data = JSON.parse(localStorage.getItem(KEY) || "null");
    const at = Number(data?.checked_at_epoch);
    if (!data || typeof data !== "object" || !Number.isFinite(at)) return null;
    if (Date.now() / 1000 - at >= TTL_S) return null;
    return data;
  } catch {
    return null;
  }
}

export function writeUpdateStatus(data) {
  if (!data || typeof data !== "object") return;
  try {
    localStorage.setItem(KEY, JSON.stringify(data));
  } catch {
    /* private mode / quota */
  }
}

export function forgetUpdateStatus() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
