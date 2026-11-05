/** Mentions @bot — résolution, filtre autocomplete, surlignage couleur avatar. */

import { avatarColor } from "./avatarColor";

const NAME_BODY = "[a-zA-Z0-9_-]+";
/** Fresh /g each call — avoid lastIndex reuse bugs. */
function mentionRe() {
  return new RegExp(`@(${NAME_BODY})`, "g");
}
/** @query juste avant le curseur (après début / espace / ponctuation légère). */
const QUERY_AT_CARET_RE = new RegExp(
  `(?:^|[\\s([{«"'])@([a-zA-Z0-9_-]*)$`
);

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function findBot(bots, ref) {
  const needle = String(ref || "")
    .replace(/^@/, "")
    .trim()
    .toLowerCase();
  if (!needle || !Array.isArray(bots)) return null;
  const byName = bots.find((b) => String(b.name || "").toLowerCase() === needle);
  if (byName) return byName;
  return (
    bots.find((b) => String(b.label || "").trim().toLowerCase() === needle) ||
    null
  );
}

export function mentionQueryAt(text, caret) {
  const before = String(text || "").slice(0, Math.max(0, caret));
  const m = before.match(QUERY_AT_CARET_RE);
  if (!m) return null;
  const query = m[1] || "";
  const start = before.length - query.length - 1;
  return { start, query, end: caret };
}

export function filterMentionBots(bots, query, excludeName) {
  const q = String(query || "").toLowerCase();
  const list = Array.isArray(bots) ? bots : [];
  return list.filter((b) => {
    if (!b?.name || b.name === excludeName) return false;
    if (!q) return true;
    const name = String(b.name).toLowerCase();
    const label = String(b.label || "").toLowerCase();
    return name.includes(q) || label.includes(q);
  });
}

/** Deep-link cible pour un @ dans une bulle botmail. */
export function mentionDeepLink(message, mentionedName) {
  const meta = message?.meta || {};
  if (meta.kind !== "botmail") return null;
  const name = String(mentionedName || "").toLowerCase();
  const linkBot = String(meta.link_bot || "").toLowerCase();
  if (linkBot && linkBot === name) {
    return {
      bot: meta.link_bot,
      msgId: meta.link_message_id || meta.peer_message_id || null,
    };
  }
  const toBot = String(meta.to_bot || "").toLowerCase();
  if (toBot && toBot === name) {
    return {
      bot: meta.to_bot,
      msgId: meta.link_message_id || meta.peer_message_id || null,
    };
  }
  const fromBot = String(meta.from_bot || "").toLowerCase();
  if (fromBot && fromBot === name) {
    return {
      bot: meta.from_bot,
      msgId: meta.link_message_id || meta.origin_message_id || null,
    };
  }
  return null;
}

export function mentionHref(botName, msgId) {
  const base = `/b/${encodeURIComponent(botName)}/discussion`;
  return msgId ? `${base}?msg=${encodeURIComponent(msgId)}` : base;
}

/** HTML miroir pour le compositeur (texte échappé + mentions colorées). */
export function composerHighlightHtml(text, bots) {
  const raw = String(text || "");
  const esc = escapeHtml(raw);
  const colored = esc.replace(mentionRe(), (full, name) => {
    const bot = findBot(bots, name);
    if (!bot) return full;
    const color = avatarColor(bot.name);
    return `<span class="bot-mention" style="color:${color}">@${escapeHtml(bot.name)}</span>`;
  });
  return colored.replace(/\n$/g, "\n\n").replace(/\n/g, "<br>");
}

/**
 * Colore @mentions dans du HTML marked.
 * @param {object} [opts]
 * @param {object} [opts.message] message source (meta botmail → deep link)
 */
export function colorizeMentionsInHtml(html, bots, opts = {}) {
  const message = opts.message || null;
  return String(html || "").replace(/(^|>)([^<]*)/g, (all, prefix, text) => {
    const next = text.replace(mentionRe(), (full, name) => {
      const bot = findBot(bots, name);
      if (!bot) return full;
      const color = avatarColor(bot.name);
      const n = escapeHtml(bot.name);
      const deep = mentionDeepLink(message, bot.name);
      const targetBot = deep?.bot || bot.name;
      const msgId = deep?.msgId || "";
      const href = mentionHref(targetBot, msgId || null);
      const msgAttr = msgId ? ` data-msg="${escapeHtml(msgId)}"` : "";
      return (
        `<a class="bot-mention" href="${href}" data-bot="${escapeHtml(targetBot)}"${msgAttr} ` +
        `style="color:${color}">@${n}</a>`
      );
    });
    return prefix + next;
  });
}

export { avatarColor };
