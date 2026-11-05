import { createI18n } from "vue-i18n";
import en from "./locales/en.json";
import fr from "./locales/fr.json";

const saved = localStorage.getItem("autonomous.locale") || "en";

export const i18n = createI18n({
  legacy: false,
  locale: saved,
  fallbackLocale: "en",
  messages: { en, fr },
});

export function setLocale(locale) {
  i18n.global.locale.value = locale;
  localStorage.setItem("autonomous.locale", locale);
}
