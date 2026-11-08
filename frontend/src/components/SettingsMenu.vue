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
      <li class="action-row settings-action-row">
        <button
          class="danger"
          type="button"
          role="menuitem"
          :disabled="deleting || !state.bots.length"
          @click.stop="toggleDeleteAll"
        >
          <UiIcon name="trash" :size="16" />
          <span>{{ deleting ? t("settings.deletingAllBots") : t("settings.deleteAllBots") }}</span>
        </button>
        <span
          v-if="armed"
          class="action-confirm-wrap"
          @pointerenter="tip = true"
          @pointerleave="tip = false"
          @focusin="tip = true"
          @focusout="tip = false"
        >
          <button
            class="action-confirm"
            type="button"
            :disabled="deleting || !state.bots.length"
            :aria-label="deleteConfirmLabel"
            @click.stop="deleteAllBots"
          >
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path
                d="M3.2 8.2 6.4 11.4 12.8 4.6"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </button>
          <span v-if="tip" class="action-confirm-tip" role="tooltip">{{ deleteConfirmLabel }}</span>
        </span>
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
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { api } from "../api";
import { state } from "../store";
import { disconnectEvents } from "../sync";
import UiIcon from "./ui/UiIcon.vue";

const { t } = useI18n();
const router = useRouter();
const open = ref(false);
const armed = ref(false);
const tip = ref(false);
const deleting = ref(false);
const root = ref(null);

const deleteConfirmLabel = computed(() =>
  t("confirm.deleteAllBots", { count: state.bots.length }),
);

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

function toggleDeleteAll() {
  if (deleting.value || !state.bots.length) return;
  armed.value = !armed.value;
  tip.value = false;
}

async function deleteAllBots() {
  if (deleting.value || !armed.value) return;
  const names = state.bots.map((b) => b.name);
  if (!names.length) {
    armed.value = false;
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
    armed.value = false;
    open.value = false;
    router.replace("/");
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    deleting.value = false;
  }
}

watch(open, (isOpen) => {
  if (!isOpen && !deleting.value) {
    armed.value = false;
    tip.value = false;
  }
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
