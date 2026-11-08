/**
 * Per-bot composer drafts for the current browser tab.
 *
 * sessionStorage (not localStorage): drafts survive bot switches and reloads
 * in this tab, but two tabs/windows keep independent drafts for the same bot.
 */

const TEXT_KEY = "autonomous.composerDrafts.v1";

/** SPA-only pending attachments (File / dataUrl) — not persisted across reload. */
const pendingByBot = new Map();

function readAll() {
  try {
    const raw = sessionStorage.getItem(TEXT_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeAll(all) {
  try {
    sessionStorage.setItem(TEXT_KEY, JSON.stringify(all));
  } catch {
    /* quota / private mode */
  }
}

export function getComposerDraft(bot) {
  const name = String(bot || "").trim();
  if (!name) return "";
  return String(readAll()[name] || "");
}

export function setComposerDraft(bot, text) {
  const name = String(bot || "").trim();
  if (!name) return;
  const all = readAll();
  const value = String(text || "");
  if (!value.trim()) delete all[name];
  else all[name] = value;
  writeAll(all);
}

export function clearComposerDraft(bot) {
  setComposerDraft(bot, "");
}

export function getComposerPending(bot) {
  const name = String(bot || "").trim();
  if (!name) return [];
  return pendingByBot.get(name) || [];
}

export function setComposerPending(bot, items) {
  const name = String(bot || "").trim();
  if (!name) return;
  if (!items || !items.length) pendingByBot.delete(name);
  else pendingByBot.set(name, items);
}

export function clearComposerPending(bot) {
  setComposerPending(bot, []);
}
