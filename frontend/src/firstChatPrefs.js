/** After the onboarding language clarify, send the prefs script in that locale. */

import { api } from "./api";
import { i18n, setLocale } from "./i18n";
import { dropOptimisticDupes, isOptimisticMessageId, state } from "./store";

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
  if (!bot || pending !== bot) return false;
  const resolved = resolveOnboardingLang(answer);
  if (!resolved) return false;

  state.firstChatPrefsPending = null;
  try {
    await api.putSettings({
      first_chat_prefs_pending: null,
      first_chat_done: true,
      first_chat_onboarding: true,
      locale: resolved.ui,
    });
  } catch {
    /* continue — message still useful */
  }
  setLocale(resolved.ui);

  const { visible, script } = prefsPayload(resolved);
  if (!script || script.length < 200) {
    throw new Error("Onboarding prefs script missing or truncated");
  }
  const tempId = `tmp-prefs-${Date.now()}`;
  rememberMessage(bot, {
    id: tempId,
    bot,
    conversation_id: "main",
    role: "user",
    content: visible,
    attachments: [],
    meta: {},
    created_at: new Date().toISOString(),
  });
  try {
    const saved = await api.sendMessage(bot, visible, [], { prompt: script });
    const list = state.messages[bot] || [];
    for (let i = list.length - 1; i >= 0; i--) {
      if (list[i]?.id === tempId || (isOptimisticMessageId(list[i]?.id) && list[i].content === visible)) {
        list.splice(i, 1);
      }
    }
    if (saved?.id) rememberMessage(bot, saved);
    return true;
  } catch (e) {
    const list = state.messages[bot] || [];
    for (let i = list.length - 1; i >= 0; i--) {
      if (list[i]?.id === tempId) list.splice(i, 1);
    }
    state.firstChatPrefsPending = bot;
    throw e;
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
