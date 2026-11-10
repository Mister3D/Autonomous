<template>
  <div class="details">
    <div class="field-block model-field">
      <span class="ui-toggle-main">
        <UiIconBadge size="sm">
          <UiIcon name="database" :size="16" />
        </UiIconBadge>
        <ModelPicker field :model="bot.model || ''" @update:model="onModel" />
      </span>
    </div>
    <UiToggleRow
      :title="t('details.internet')"
      :hint="t('details.internetHint')"
      :model-value="!!bot.internet"
      @change="toggleNet"
    >
      <template #icon>
        <UiIcon name="globe" :size="16" />
      </template>
    </UiToggleRow>
    <BotCompanion :bot="bot" />
    <UiToggleRow
      :title="t('details.memoryAccess')"
      :hint="t('details.memoryAccessHint')"
      :model-value="bot.memory_access !== false"
      @change="toggleMemory"
    >
      <template #icon>
        <UiIcon name="memory" :size="16" />
      </template>
    </UiToggleRow>
    <UiToggleRow
      :title="t('details.isManager')"
      :tip="t('details.isManagerHint')"
      :model-value="!!bot.is_manager"
      :disabled="managerLocked"
      :muted="managerLocked"
      :disabled-reason="managerLockReason"
      @change="toggleManager"
    >
      <template #icon>
        <UiIcon name="users" :size="16" />
      </template>
    </UiToggleRow>
    <UiToggleRow
      :title="t('details.autoSleep')"
      :hint="t('details.autoSleepHint')"
      :model-value="bot.auto_sleep !== false"
      @change="toggleSleep"
    >
      <template #icon>
        <UiIcon name="moon" :size="16" />
      </template>
    </UiToggleRow>
    <BotMcpGrants :bot="bot" />

    <div class="package-usage" aria-live="polite">
      <div class="package-usage-head">
        <span class="ui-toggle-main">
          <UiIconBadge size="sm">
            <UiIcon name="harddrive" :size="16" />
          </UiIconBadge>
          <span class="ui-toggle-copy">
            <strong>{{ t("details.package") }}</strong>
            <ul v-if="pkg && !pkgError" class="package-breakdown">
              <li>
                <span>{{ t("details.packageFiles") }}</span>
                <span>{{ formatBytes(pkg.files_bytes) }}</span>
              </li>
              <li v-if="(pkg.screenshots_bytes || 0) > 0">
                <span>{{ t("details.packageScreenshots") }}</span>
                <span>{{ formatBytes(pkg.screenshots_bytes) }}</span>
              </li>
              <li v-if="(pkg.browser_bytes || 0) > 0">
                <span>{{ t("details.packageBrowser") }}</span>
                <span>{{ formatBytes(pkg.browser_bytes) }}</span>
              </li>
              <li>
                <span>
                  {{ t("details.packageChat") }}
                  <small v-if="pkg.messages">{{
                    t("details.packageChatCount", { n: pkg.messages })
                  }}</small>
                </span>
                <span>{{ formatBytes(pkg.chat_bytes) }}</span>
              </li>
              <li v-if="(pkg.agent_bytes || 0) > 0">
                <span>{{ t("details.packageAgent") }}</span>
                <span>{{ formatBytes(pkg.agent_bytes) }}</span>
              </li>
              <li>
                <span>{{ t("details.packageVm") }}</span>
                <span>{{ vmLabel }}</span>
              </li>
              <li class="package-total-row">
                <span>{{ t("details.packageTotal") }}</span>
                <span>{{ totalLabel }}</span>
              </li>
            </ul>
            <p v-else-if="pkgLoading" class="package-status hint">{{ t("details.packageLoading") }}</p>
            <p v-else-if="pkgError" class="package-status hint">{{ t("details.packageError") }}</p>
          </span>
        </span>
      </div>
    </div>

    <ManageMenu :bot="bot" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { state } from "../store";
import BotCompanion from "./BotCompanion.vue";
import BotMcpGrants from "./BotMcpGrants.vue";
import ManageMenu from "./ManageMenu.vue";
import ModelPicker from "./ModelPicker.vue";
import UiIcon from "./ui/UiIcon.vue";
import UiIconBadge from "./ui/UiIconBadge.vue";
import UiToggleRow from "./ui/UiToggleRow.vue";

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();

const pkg = ref(null);
const pkgLoading = ref(false);
const pkgError = ref(false);
let pollTimer = 0;
let loadSeq = 0;

const otherManager = computed(
  () => state.bots.find((b) => b.is_manager && b.name !== props.bot.name) || null
);
/** Cannot promote this bot while another holds the Manager slot. */
const managerLocked = computed(() => !!otherManager.value && !props.bot.is_manager);
const managerLockReason = computed(() =>
  managerLocked.value ? t("details.isManagerTaken") : "",
);

const totalLabel = computed(() => {
  if (pkgLoading.value && !pkg.value) return t("details.packageLoading");
  if (pkgError.value) return "—";
  if (!pkg.value) return "—";
  return formatBytes(pkg.value.total_bytes);
});

const vmLabel = computed(() => {
  if (!pkg.value) return "—";
  const st = pkg.value.vm_state || "absent";
  if (st === "absent") return t("details.packageVmAbsent");
  if (pkg.value.vm_bytes == null) return t("details.packageVmUnknown");
  return formatBytes(pkg.value.vm_bytes);
});

function formatBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(v < 10 * 1024 ? 1 : 0)} KB`;
  if (v < 1024 * 1024 * 1024) {
    return `${(v / (1024 * 1024)).toFixed(v < 10 * 1024 * 1024 ? 1 : 0)} MB`;
  }
  return `${(v / (1024 * 1024 * 1024)).toFixed(v < 10 * 1024 * 1024 * 1024 ? 1 : 0)} GB`;
}

async function loadPackage() {
  const name = props.bot?.name;
  if (!name) return;
  const seq = ++loadSeq;
  pkgLoading.value = true;
  pkgError.value = false;
  try {
    const next = await api.botPackage(name);
    if (seq !== loadSeq) return;
    pkg.value = next;
  } catch {
    if (seq !== loadSeq) return;
    pkgError.value = true;
  } finally {
    if (seq === loadSeq) pkgLoading.value = false;
  }
}

watch(
  () => props.bot?.name,
  () => {
    pkg.value = null;
    loadPackage();
  },
  { immediate: true },
);

watch(
  () => [
    props.bot?.desk?.state,
    props.bot?.desk?.container_name,
    state.filesFeed?.bot === props.bot?.name ? state.filesFeed?.at : 0,
  ],
  () => {
    loadPackage();
  },
);

onMounted(() => {
  pollTimer = window.setInterval(() => {
    loadPackage();
  }, 20000);
});

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = 0;
  loadSeq += 1;
});

async function onModel(next) {
  const model = String(next || "").trim();
  if (!model) return;
  const i = state.bots.findIndex((b) => b.name === props.bot.name);
  const prev = i >= 0 ? state.bots[i].model : props.bot.model;
  if (i >= 0) state.bots[i] = { ...state.bots[i], model };
  try {
    await api.patchBot(props.bot.name, { model });
  } catch (e) {
    if (i >= 0) state.bots[i] = { ...state.bots[i], model: prev };
    alert(e.message);
  }
}

async function toggleNet(ev) {
  const next = ev.target.checked;
  const i = state.bots.findIndex((b) => b.name === props.bot.name);
  const prev = i >= 0 ? state.bots[i].internet : props.bot.internet;
  if (i >= 0) state.bots[i] = { ...state.bots[i], internet: next };
  try {
    await api.patchBot(props.bot.name, { internet: next });
  } catch (e) {
    if (i >= 0) state.bots[i] = { ...state.bots[i], internet: prev };
    ev.target.checked = !!prev;
    alert(e.message);
  }
}

async function toggleMemory(ev) {
  const next = ev.target.checked;
  const i = state.bots.findIndex((b) => b.name === props.bot.name);
  const prev = i >= 0 ? state.bots[i].memory_access !== false : props.bot.memory_access !== false;
  if (i >= 0) state.bots[i] = { ...state.bots[i], memory_access: next };
  try {
    await api.patchBot(props.bot.name, { memory_access: next });
  } catch (e) {
    if (i >= 0) state.bots[i] = { ...state.bots[i], memory_access: prev };
    ev.target.checked = !!prev;
    alert(e.message);
  }
}

async function toggleManager(ev) {
  const next = ev.target.checked;
  const i = state.bots.findIndex((b) => b.name === props.bot.name);
  const prev = i >= 0 ? !!state.bots[i].is_manager : !!props.bot.is_manager;
  if (i >= 0) state.bots[i] = { ...state.bots[i], is_manager: next };
  try {
    await api.patchBot(props.bot.name, { is_manager: next });
  } catch (e) {
    if (i >= 0) state.bots[i] = { ...state.bots[i], is_manager: prev };
    ev.target.checked = !!prev;
    alert(e.message);
  }
}

async function toggleSleep(ev) {
  const next = ev.target.checked;
  const i = state.bots.findIndex((b) => b.name === props.bot.name);
  const prev = i >= 0 ? state.bots[i].auto_sleep : props.bot.auto_sleep;
  if (i >= 0) state.bots[i] = { ...state.bots[i], auto_sleep: next };
  try {
    await api.patchBot(props.bot.name, { auto_sleep: next });
  } catch (e) {
    if (i >= 0) state.bots[i] = { ...state.bots[i], auto_sleep: prev };
    ev.target.checked = prev !== false;
    alert(e.message);
  }
}

</script>
