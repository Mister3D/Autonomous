<template>
  <div class="companion-link">
    <UiToggleRow
      :title="t('details.companionTransfer')"
      :hint="t('details.companionTransferHint')"
      :model-value="transferOn"
      @change="onTransfer"
    >
      <template #icon>
        <UiIcon name="link" :size="16" />
      </template>
    </UiToggleRow>
    <div v-if="transferOn && devices.length" class="companion-pick" :class="{ open }" ref="root">
      <button
        class="companion-trigger"
        type="button"
        :aria-expanded="open"
        aria-haspopup="listbox"
        @click="open = !open"
      >
        <span class="companion-trigger-copy">
          <span class="companion-trigger-label">{{ currentName }}</span>
          <span v-if="showStatus" class="companion-status" :class="{ on: online }">
            {{ online ? t("companion.online") : t("companion.offline") }}
          </span>
        </span>
        <svg class="companion-caret" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
          <path d="M2.5 4.2 6 7.8 9.5 4.2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <ul v-if="open" class="companion-menu" role="listbox">
        <li v-for="device in devices" :key="device.id">
          <button
            type="button"
            role="option"
            :aria-selected="device.id === bot.companion_id"
            :class="{ active: device.id === bot.companion_id }"
            @click="choose(device.id)"
          >
            <span class="companion-option-copy">
              <span class="companion-option-label">{{ device.name }}</span>
              <span class="companion-status" :class="{ on: device.online }">
                {{ device.online ? t("companion.online") : t("companion.offline") }}
              </span>
            </span>
          </button>
        </li>
      </ul>
    </div>
    <p v-if="error" class="mcp-grants-error">{{ error }}</p>
    <UiToggleRow
      v-if="bot.companion_id && bot.companion_egress"
      :title="t('details.companionKill')"
      :hint="t('details.companionKillHint')"
      :model-value="!!bot.companion_killswitch"
      @change="onKill"
    >
      <template #icon>
        <UiIcon name="update" :size="16" />
      </template>
    </UiToggleRow>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { api } from "../api";
import { state } from "../store";
import UiIcon from "./ui/UiIcon.vue";
import UiToggleRow from "./ui/UiToggleRow.vue";

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();
const router = useRouter();
const devices = ref([]);
const devicesReady = ref(false);
const error = ref("");
const open = ref(false);
const arming = ref(false);
const root = ref(null);
let timer = 0;

const transferOn = computed(() => !!props.bot.companion_egress || arming.value);
const current = computed(
  () => devices.value.find((device) => device.id === props.bot.companion_id) || null
);
const currentName = computed(
  () => current.value?.name || props.bot.companion_name || t("details.companionPick")
);
const showStatus = computed(() => !!(current.value || props.bot.companion_id));
const online = computed(() => (current.value ? !!current.value.online : !!props.bot.companion_online));

function apply(next) {
  const i = state.bots.findIndex((b) => b.name === props.bot.name);
  if (i >= 0) state.bots[i] = { ...state.bots[i], ...next };
}

async function save(patch, previous) {
  error.value = "";
  apply(patch);
  try {
    const saved = await api.patchBot(props.bot.name, patch);
    apply(saved);
    return true;
  } catch (e) {
    apply(previous);
    error.value = e.message;
    return false;
  }
}

function snapshot() {
  return {
    companion_id: props.bot.companion_id || null,
    companion_name: props.bot.companion_name || "",
    companion_online: !!props.bot.companion_online,
    companion_egress: !!props.bot.companion_egress,
    companion_killswitch: !!props.bot.companion_killswitch,
  };
}

function choose(id) {
  open.value = false;
  onCompanion(id);
}

async function onCompanion(id) {
  const previous = snapshot();
  const device = devices.value.find((row) => row.id === id);
  const ok = await save(
    {
      companion_id: id,
      companion_egress: true,
      companion_killswitch: false,
    },
    previous
  );
  if (ok) {
    arming.value = false;
    if (device) {
      apply({
        companion_name: device.name,
        companion_online: !!device.online,
      });
    }
  }
}

async function onTransfer(ev) {
  const next = ev.target.checked;
  if (!next) {
    arming.value = false;
    open.value = false;
    const previous = snapshot();
    const ok = await save(
      { companion_egress: false, companion_killswitch: false },
      previous
    );
    if (!ok) ev.target.checked = true;
    return;
  }
  if (!devicesReady.value) await loadDevices();
  if (!devicesReady.value) {
    ev.target.checked = false;
    return;
  }
  if (!devices.value.length) {
    ev.target.checked = false;
    const here = router.currentRoute.value.fullPath;
    if (here && !here.startsWith("/settings")) {
      sessionStorage.setItem("autonomous.settingsReturn", here);
    }
    router.push({
      name: "settings",
      params: { section: "companions" },
      query: { besoin: "connexion" },
    });
    return;
  }
  if (props.bot.companion_id) {
    const previous = snapshot();
    const ok = await save({ companion_egress: true }, previous);
    if (!ok) ev.target.checked = false;
    return;
  }
  arming.value = true;
  open.value = true;
}

async function onKill(ev) {
  const next = ev.target.checked;
  const previous = snapshot();
  const ok = await save({ companion_killswitch: next }, previous);
  if (!ok) ev.target.checked = !next;
}

async function loadDevices() {
  try {
    const data = await api.listDevices();
    devices.value = data.devices || [];
    devicesReady.value = true;
    error.value = "";
  } catch (e) {
    // Browser TypeError ("Failed to fetch") = network blip / server restart,
    // not an API error body. Keep showing it until the next successful poll.
    error.value = e.message || String(e);
  }
}

function onDoc(ev) {
  if (!root.value?.contains(ev.target)) open.value = false;
}

function onKey(ev) {
  if (ev.key === "Escape") open.value = false;
}

watch(() => props.bot.name, () => {
  open.value = false;
  arming.value = false;
  devicesReady.value = false;
  loadDevices();
}, { immediate: true });
timer = window.setInterval(() => {
  loadDevices();
}, 5000);
onMounted(() => {
  document.addEventListener("pointerdown", onDoc);
  document.addEventListener("keydown", onKey);
});
onUnmounted(() => {
  window.clearInterval(timer);
  document.removeEventListener("pointerdown", onDoc);
  document.removeEventListener("keydown", onKey);
});
</script>
