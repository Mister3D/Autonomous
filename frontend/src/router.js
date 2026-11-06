import { createRouter, createWebHistory } from "vue-router";
import LoginView from "./views/LoginView.vue";
import HubView from "./views/HubView.vue";
import SettingsModal from "./components/SettingsModal.vue";
import { api } from "./api";
import { loadLocaleFromServer } from "./i18n";
import { state } from "./store";
import { connectEvents, disconnectEvents, refreshBots } from "./sync";

/** One server locale pull per authenticated session (reset on logout). */
let localeSynced = false;

export const TABS = ["discussion", "terminal", "screen"];

const TAB_ALIASES = {
  discussion: "discussion",
  messages: "discussion",
  message: "discussion",
  terminal: "terminal",
  screen: "screen",
  ecran: "screen",
  écran: "screen",
};

export function normalizeTab(tab) {
  if (tab == null || tab === "") return "discussion";
  const key = String(tab).toLowerCase();
  return TAB_ALIASES[key] || (TABS.includes(key) ? key : "discussion");
}

export function botPath(name, tab = "discussion") {
  return `/b/${encodeURIComponent(name)}/${normalizeTab(tab)}`;
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginView, meta: { public: true } },
    { path: "/settings/:section?", name: "settings", component: SettingsModal },
    { path: "/", name: "hub", component: HubView },
    { path: "/setup", name: "setup", component: HubView },
    {
      path: "/b/:name/:tab?",
      name: "bot",
      component: HubView,
      props: true,
    },
  ],
});

router.beforeEach(async (to) => {
  try {
    const status = await api.authStatus();
    state.authenticated = !!status.authenticated;
    state.mustChangePassword = !!(
      status.authenticated && status.must_change_password
    );
  } catch {
    state.authenticated = false;
    state.mustChangePassword = false;
  }
  if (!to.meta.public && !state.authenticated) {
    return { name: "login", query: { next: to.fullPath } };
  }
  // Generated install password: stay on /login until replaced.
  if (state.authenticated && state.mustChangePassword && to.name !== "login") {
    return { name: "login", query: { next: to.fullPath } };
  }
  if (to.name === "login" && state.authenticated && !state.mustChangePassword) {
    const next = typeof to.query.next === "string" ? to.query.next : "/";
    return next || "/";
  }
  if (state.authenticated && !state.mustChangePassword) {
    if (!localeSynced) {
      localeSynced = true;
      try {
        await loadLocaleFromServer();
      } catch {
        /* keep localStorage locale */
      }
    }
    connectEvents();
    try {
      await refreshBots();
    } catch {
      /* ignore */
    }
  } else {
    localeSynced = false;
    disconnectEvents();
  }

  // Canonicalize /b/:name/:tab (aliases → discussion|terminal|screen)
  if (to.name === "bot") {
    const name = to.params.name;
    const raw = to.params.tab;
    const tab = normalizeTab(raw);
    if (raw == null || raw === "" || String(raw) !== tab) {
      return {
        name: "bot",
        params: { name, tab },
        query: to.query,
        hash: to.hash,
        replace: true,
      };
    }
  }
  return true;
});
