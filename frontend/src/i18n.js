import { createI18n } from "vue-i18n";
import { api } from "./api";
import en from "./locales/en.json";
import fr from "./locales/fr.json";

const saved = localStorage.getItem("autonomous.locale") || "en";

export const i18n = createI18n({
  legacy: false,
  locale: saved === "fr" ? "fr" : "en",
  fallbackLocale: "en",
  messages: { en, fr },
});

function normalizeLocale(locale) {
  return locale === "fr" ? "fr" : "en";
}

/**
 * Apply UI language. Always mirrors into localStorage.
 * When ``persist`` is true (default), also writes ``settings.locale`` so another
 * browser / device restores the same language after login.
 */
export function setLocale(locale, { persist = true } = {}) {
  const code = normalizeLocale(locale);
  i18n.global.locale.value = code;
  localStorage.setItem("autonomous.locale", code);
  if (!persist) return;
  // api.js has no i18n/store imports — static is fine (avoids Vite dual-import warn).
  api.putSettings({ locale: code }).catch(() => {
    /* offline / not logged in — localStorage still updated */
  });
}

/** Load ``settings.locale`` after auth (server wins over a stale localStorage). */
export async function loadLocaleFromServer() {
  const s = await api.settings();
  const raw = s?.locale;
  if (raw === "fr" || raw === "en") {
    setLocale(raw, { persist: false });
  }
}
