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
    <div class="toggle-row info-row has-icon thinking-row">
      <span class="ui-toggle-main">
        <UiIconBadge size="sm">
          <UiIcon name="cpu" :size="16" />
        </UiIconBadge>
        <span class="ui-toggle-copy">
          <strong>{{ t("details.thinking") }}</strong>
          <small>{{ t("details.thinkingHint") }}</small>
        </span>
      </span>
      <MenuSelect
        field
        :model-value="thinkingLevel"
        :options="thinkingOptions"
        :aria-label="t('details.thinking')"
        @update:model-value="onThinking"
      />
    </div>
    <section class="bot-notebook" aria-live="polite">
      <div class="toggle-row info-row has-icon">
        <span class="ui-toggle-main">
          <UiIconBadge size="sm">
            <UiIcon name="save" :size="16" />
          </UiIconBadge>
          <span class="ui-toggle-copy">
            <strong>{{ t("details.notebook") }}</strong>
            <small v-if="notebookLoading">{{ t("details.packageLoading") }}</small>
            <small v-else-if="!notebook.length">{{ t("details.notebookEmpty") }}</small>
          </span>
        </span>
        <UiOrb
          :label="t('details.notebookShow')"
          :expanded="notebookOpen ? 'true' : 'false'"
          @click="notebookOpen = true"
        >
          <UiIcon name="eye" :size="16" />
        </UiOrb>
      </div>
      <UiModal
        :open="notebookOpen"
        panel-class="notebook-modal"
        :aria-label="t('details.notebook')"
        @close="notebookOpen = false"
      >
        <h2>{{ t("details.notebook") }}</h2>
        <p v-if="notebookLoading" class="hint">{{ t("details.packageLoading") }}</p>
        <p v-else-if="!notebook.length" class="hint">{{ t("details.notebookEmpty") }}</p>
        <div v-else class="notebook-modal-body">
          <div v-for="group in notebookGroups" :key="group.kind" class="bot-notebook-group">
            <h4>{{ group.label }}</h4>
            <ul>
              <li v-for="row in group.rows" :key="row.id">
                <template v-if="row.kind === 'note'">
                  <strong>{{ row.title }}</strong>
                  <p>{{ row.body }}</p>
                </template>
                <span v-else>{{ row.body }}</span>
              </li>
            </ul>
          </div>
        </div>
        <div class="mcp-dialog-actions">
          <UiButton variant="ghost" type="button" @click="notebookOpen = false">
            {{ t("details.notebookClose") }}
          </UiButton>
        </div>
      </UiModal>
    </section>
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
import MenuSelect from "./MenuSelect.vue";
import ModelPicker from "./ModelPicker.vue";
import UiButton from "./ui/UiButton.vue";
import UiIcon from "./ui/UiIcon.vue";
import UiIconBadge from "./ui/UiIconBadge.vue";
import UiModal from "./ui/UiModal.vue";
import UiOrb from "./ui/UiOrb.vue";
import UiToggleRow from "./ui/UiToggleRow.vue";

const THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();

const thinkingOptions = computed(() =>
  THINKING_LEVELS.map((value) => ({
    value,
    label: t(`details.thinkingLevel.${value}`),
  })),
);

const thinkingLevel = computed(() => {
  const raw = props.bot?.thinking;
  if (raw === false || raw === 0 || raw === "0") return "off";
  if (raw === true || raw === 1 || raw === "1" || raw == null || raw === "") return "medium";
  const s = String(raw).trim().toLowerCase();
  return THINKING_LEVELS.includes(s) ? s : "medium";
});

const pkg = ref(null);
const pkgLoading = ref(false);
const pkgError = ref(false);
const notebook = ref([]);
const notebookLoading = ref(false);
const notebookOpen = ref(false);
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

const notebookGroups = computed(() => {
  const rows = notebook.value || [];
  const groups = [
    { kind: "order", label: t("details.notebookOrders") },
    { kind: "open", label: t("details.notebookOpen") },
    { kind: "note", label: t("details.notebookNotes") },
  ];
  return groups
    .map((g) => ({ ...g, rows: rows.filter((r) => r.kind === g.kind) }))
    .filter((g) => g.rows.length);
});

const notebookTick = computed(() => {
  const name = props.bot?.name;
  const rows = (name && state.messages[name]) || [];
  let n = 0;
  for (const m of rows) {
    if (m?.meta?.kind === "notebook") n += 1;
  }
  return `${name || ""}:${n}`;
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

async function loadNotebook() {
  const name = props.bot?.name;
  if (!name) return;
  notebookLoading.value = !notebook.value.length;
  try {
    notebook.value = await api.notebook(name);
  } catch {
    notebook.value = [];
  } finally {
    notebookLoading.value = false;
  }
}

function onNotebookKey(ev) {
  if (ev.key === "Escape") notebookOpen.value = false;
}

watch(notebookOpen, (open) => {
  if (open) document.addEventListener("keydown", onNotebookKey);
  else document.removeEventListener("keydown", onNotebookKey);
});

watch(
  () => props.bot?.name,
  () => {
    pkg.value = null;
    notebook.value = [];
    notebookOpen.value = false;
    loadPackage();
    loadNotebook();
  },
  { immediate: true },
);

watch(notebookTick, () => {
  loadNotebook();
});

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
  document.removeEventListener("keydown", onNotebookKey);
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

async function onThinking(next) {
  const level = String(next || "").trim().toLowerCase();
  if (!THINKING_LEVELS.includes(level)) return;
  const i = state.bots.findIndex((b) => b.name === props.bot.name);
  const prev = i >= 0 ? state.bots[i].thinking : props.bot.thinking;
  if (i >= 0) state.bots[i] = { ...state.bots[i], thinking: level };
  try {
    await api.patchBot(props.bot.name, { thinking: level });
  } catch (e) {
    if (i >= 0) state.bots[i] = { ...state.bots[i], thinking: prev };
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
