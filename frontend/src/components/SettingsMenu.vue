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
      <UiIcon name="settings" :size="18" />
    </button>
    <ul v-if="open" class="settings-pop" role="menu">
      <li>
        <button type="button" role="menuitem" @click="openSettings">
          <UiIcon name="settings" :size="16" />
          <span>{{ t("settings.title") }}</span>
        </button>
      </li>
      <li class="settings-sep" role="separator" />
      <li>
        <button type="button" role="menuitem" @click="logout">
          <UiIcon name="logout" :size="16" />
          <span>{{ t("manage.logout") }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { api } from "../api";
import { state } from "../store";
import { disconnectEvents } from "../sync";
import UiIcon from "./ui/UiIcon.vue";

const { t } = useI18n();
const router = useRouter();
const open = ref(false);
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
