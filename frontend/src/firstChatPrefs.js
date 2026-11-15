/** After the onboarding language clarify, send the prefs script in that locale. */

import { api } from "./api";
import { i18n, setLocale } from "./i18n";
import { dropOptimisticDupes, state } from "./store";

function normalizeLang(answer) {
  return String(answer || "")
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}

/**
 * Read a locale string without vue-i18n pluralization.
 * Scripts contain `|` between clarify choices; `t()` would treat that as plurals
 * and send only one fragment to the agent (e.g. a single choice line).
 */
export function rawMessage(key, locale, vars = null) {
  const bag = i18n.global.getLocaleMessage(locale) || {};
  let text = bag[key];
  if (typeof text !== "string") {
    text = String(i18n.global.t(key, vars || {}, { locale }));
  } else if (vars && typeof vars === "object") {
    text = text.replace(/\{(\w+)\}/g, (_, name) =>
      vars[name] != null ? String(vars[name]) : `{${name}}`
    );
  }
  return text;
}

/**
 * Map a language answer to UI locale + agent speak label.
 * Returns null only for empty answers.
 * @returns {{ ui: 'fr'|'en', script: 'fr'|'en'|'other', speak: string } | null}
 */
export function resolveOnboardingLang(answer) {
  const raw = String(answer || "").trim();
  const a = normalizeLang(raw);
  if (!a) return null;
  if (
    /^(francais|french|fr)$/.test(a) ||
    a.includes("francais") ||
    a.includes("french")
  ) {
    return { ui: "fr", script: "fr", speak: "Français" };
  }
  if (
    /^(english|anglais|en)$/.test(a) ||
    a.includes("english") ||
    a.includes("anglais")
  ) {
    return { ui: "en", script: "en", speak: "English" };
  }
  if (
    /^(deutsch|deutch|german|allemand|de)$/.test(a) ||
    a.includes("deutsch") ||
    a.includes("deutch") ||
    a.includes("german") ||
    a.includes("allemand")
  ) {
    return { ui: "en", script: "other", speak: "German" };
  }
  // Any other typed language (Spanish, Italian, …) while onboarding is pending.
  return { ui: "en", script: "other", speak: raw };
}

/** @deprecated use resolveOnboardingLang */
export function detectOnboardingLang(answer) {
  const resolved = resolveOnboardingLang(answer);
  if (!resolved) return null;
  return resolved.script === "other" ? null : resolved.script;
}

function rememberMessage(botName, saved) {
  if (!saved?.id) return;
  if (!state.messages[botName]) state.messages[botName] = [];
  dropOptimisticDupes(botName, saved);
  if (!state.messages[botName].some((m) => m.id === saved.id)) {
    state.messages[botName].push(saved);
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function turnIsLive(name) {
  const row = (state.bots || []).find((b) => b.name === name);
  const status = String(row?.status || "");
  if (status === "busy" || status === "waiting") return true;
  const msgs = state.messages[name] || [];
  return msgs.some(
    (m) =>
      m?.meta?.streaming ||
      (m?.meta?.kind === "tool" && m?.meta?.status === "running") ||
      (m?.role === "assistant" && m?.meta?.status === "running")
  );
}

/**
 * The language answer resumes the same run. Posting the next user message
 * while that run is live parks it in the queue, where Send now and Stop both
 * abort the turn. Wait until the bot is idle.
 */
async function waitUntilAgentIdle(name) {
  const deadline = Date.now() + 180000;
  const notBefore = Date.now() + 1200;
  while (Date.now() < deadline) {
    if (!turnIsLive(name) && Date.now() >= notBefore) {
      await delay(400);
      if (!turnIsLive(name)) return true;
    }
    await delay(250);
  }
  return false;
}

/**
 * Send once the agent looks free. If the run slot is still held, the server
 * stores the message with ``meta.hold`` and the thread hides it until the
 * current turn ends — no « En file » / Send now.
 */
async function deliverPrefs(bot, visible, script) {
  const saved = await api.sendMessage(bot, visible, [], {
    prompt: script,
    hold: true,
  });
  if (!saved?.id) return null;
  if (!saved.meta?.hold) rememberMessage(bot, saved);
  return saved;
}

let prefsInFlight = false;

function prefsPayload(resolved) {
  if (resolved.script === "fr" || resolved.script === "en") {
    const loc = resolved.script;
    return {
      visible: rawMessage("setup.firstChatPrefsVisible", loc),
      script: rawMessage("setup.firstChatScript", loc),
    };
  }
  return {
    visible: rawMessage("setup.firstChatPrefsVisibleOther", "en", {
      lang: resolved.speak,
    }),
    script: rawMessage("setup.firstChatScriptOther", "en", {
      lang: resolved.speak,
    }),
  };
}

/**
 * If first-chat is waiting on the language answer for this bot, send the
 * personalization prompt in the chosen language and clear the pending flag.
 */
export async function maybeContinueFirstChatPrefs(bot, answer) {
  const pending = state.firstChatPrefsPending || "";
  if (!bot || pending !== bot || prefsInFlight) return false;
  const resolved = resolveOnboardingLang(answer);
  if (!resolved) return false;

  prefsInFlight = true;
  try {
    try {
      await api.putSettings({
        first_chat_onboarding: true,
        locale: resolved.ui,
      });
    } catch {
      /* continue — message still useful */
    }
    setLocale(resolved.ui, { persist: false });

    const { visible, script } = prefsPayload(resolved);
    if (!script || script.length < 200) {
      throw new Error("Onboarding prefs script missing or truncated");
    }
    // Keep the pending flag until the message is actually accepted, so a
    // reload during the wait can resume. Do not paint a queued bubble.
    const idle = await waitUntilAgentIdle(bot);
    if (!idle) return false;
    const saved = await deliverPrefs(bot, visible, script);
    if (!saved) return false;
    state.firstChatPrefsPending = null;
    try {
      await api.putSettings({
        first_chat_prefs_pending: null,
        first_chat_done: true,
      });
    } catch {
      /* the message is already in the thread */
    }
    return true;
  } catch (e) {
    throw e;
  } finally {
    prefsInFlight = false;
  }
}

/**
 * If language was saved in memory but prefs were never sent (e.g. Deutsch),
 * resume the second onboarding message.
 */
export async function resumeFirstChatPrefsIfStuck() {
  const pending =
    typeof state.firstChatPrefsPending === "string"
      ? state.firstChatPrefsPending.trim()
      : "";
  if (!pending) return false;
  try {
    const memory = await api.memoryEntries();
    const entries = Array.isArray(memory) ? memory : memory?.entries || [];
    const langEntry = entries.find((e) => e?.key === "preferred_language");
    const value = String(langEntry?.value || "").trim();
    if (!value) return false;
    return await maybeContinueFirstChatPrefs(pending, value);
  } catch {
    return false;
  }
}

/** Restore pending bot from settings after reload; resume if language already saved. */
export async function refreshFirstChatPrefsPending() {
  try {
    const settings = await api.settings();
    const pending = settings?.first_chat_prefs_pending;
    state.firstChatPrefsPending =
      typeof pending === "string" && pending.trim() ? pending.trim() : null;
    if (state.firstChatPrefsPending) {
      await resumeFirstChatPrefsIfStuck();
    }
  } catch {
    /* keep last */
  }
}
