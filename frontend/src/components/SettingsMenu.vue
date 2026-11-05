<template>
  <div class="settings-menu" :class="{ open }" ref="root">
    <button
      class="settings-orb"
      type="button"
      :aria-label="t('settings.menu')"
      :aria-expanded="open"
      aria-haspopup="menu"
      @click="open = !open"
    >
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
        <circle cx="12" cy="12" r="3.2" />
        <path
          d="M12 3.5v2.2M12 18.3v2.2M4.9 6.6l1.6 1.5M17.5 15.9l1.6 1.5M3.5 12h2.2M18.3 12h2.2M4.9 17.4l1.6-1.5M17.5 8.1l1.6-1.5"
          stroke-linecap="round"
        />
      </svg>
    </button>
    <ul v-if="open" class="settings-pop" role="menu">
      <li>
        <button type="button" role="menuitem" @click="openSettings">
          <span>{{ t("settings.title") }}</span>
        </button>
      </li>
      <li class="settings-sep" role="separator" />
      <li v-if="!confirming">
        <button class="danger" type="button" role="menuitem" @click.stop="confirming = true">
          <span>{{ t("settings.deleteAllBots") }}</span>
        </button>
      </li>
      <li v-else class="inline-confirm" role="group">
        <p>{{ t("confirm.deleteAllBots", { count: state.bots.length }) }}</p>
        <button
          class="danger"
          type="button"
          :disabled="deleting || !state.bots.length"
          @click.stop="deleteAllBots"
        >
          {{ deleting ? t("settings.deletingAllBots") : t("confirm.deleteAllGo") }}
        </button>
        <button type="button" :disabled="deleting" @click.stop="confirming = false">
          {{ t("files.cancel") }}
        </button>
      </li>
      <li class="settings-sep" role="separator" />
      <li>
        <button type="button" role="menuitem" @click="logout">
          <span>{{ t("manage.logout") }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { api } from "../api";
import { state } from "../store";
import { disconnectEvents } from "../sync";

const { t } = useI18n();
const router = useRouter();
const open = ref(false);
const confirming = ref(false);
const deleting = ref(false);
const root = ref(null);

function openSettings() {
  open.value = false;
  const here = router.currentRoute.value.fullPath;
  if (here && !here.startsWith("/settings")) {
    sessionStorage.setItem("autonomous.settingsReturn", here);
  }
  router.push({ name: "settings", params: { section: "agent" } });
}

async function logout() {
  open.value = false;
  await api.logout();
  state.authenticated = false;
  state.mustChangePassword = false;
  disconnectEvents();
  router.push("/login");
}

async function deleteAllBots() {
  if (deleting.value) return;
  const names = state.bots.map((b) => b.name);
  if (!names.length) {
    confirming.value = false;
    open.value = false;
    return;
  }
  deleting.value = true;
  try {
    for (const name of names) {
      await api.deleteBot(name);
      delete state.messages[name];
    }
    state.currentBot = null;
    confirming.value = false;
    open.value = false;
    router.replace("/");
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    deleting.value = false;
  }
}

watch(open, (isOpen) => {
  if (!isOpen && !deleting.value) confirming.value = false;
});

function onDoc(ev) {
  if (!root.value?.contains(ev.target)) open.value = false;
}

function onKey(ev) {
  if (ev.key === "Escape") open.value = false;
}

onMounted(() => {
  document.addEventListener("pointerdown", onDoc);
  document.addEventListener("keydown", onKey);
});

onUnmounted(() => {
  document.removeEventListener("pointerdown", onDoc);
  document.removeEventListener("keydown", onKey);
});
</script>
