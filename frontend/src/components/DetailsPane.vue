<template>
  <div class="details">
    <h3>{{ t("settings.title") }}</h3>
    <div class="field-block">
      <div class="ui-toggle-main field-block-label">
        <UiIconBadge size="sm">
          <UiIcon name="model" :size="16" />
        </UiIconBadge>
        <span class="ui-toggle-copy">
          <strong>{{ t("details.model") }}</strong>
          <small>{{ t("details.modelHint") }}</small>
        </span>
      </div>
      <ModelPicker :model="bot.model || ''" @update:model="onModel" />
    </div>
    <div v-if="bot.pi_session_id" class="info-row">
      <span class="ui-toggle-main">
        <UiIconBadge size="sm">
          <UiIcon name="terminal" :size="16" />
        </UiIconBadge>
        <span class="ui-toggle-copy">
          <strong>{{ t("details.piSession") }}</strong>
          <small class="mono">{{ bot.pi_session_id }}</small>
        </span>
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
      :model-value="bot.memory_access !== false"
      @change="toggleMemory"
    >
      <template #icon>
        <UiIcon name="memory" :size="16" />
      </template>
    </UiToggleRow>
    <UiToggleRow
      :title="t('details.isManager')"
      :hint="managerHint"
      :model-value="!!bot.is_manager"
      :disabled="managerLocked"
      :muted="managerLocked"
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
    <div class="info-row">
      <span class="ui-toggle-main">
        <UiIconBadge size="sm">
          <UiIcon name="monitor" :size="16" />
        </UiIconBadge>
        <span class="ui-toggle-copy">
          <strong>{{ t("details.desk") }}</strong>
          <small>{{ deskLabel }}</small>
        </span>
      </span>
    </div>

    <ManageMenu :bot="bot" />
  </div>
</template>

<script setup>
import { computed } from "vue";
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

const otherManager = computed(
  () => state.bots.find((b) => b.is_manager && b.name !== props.bot.name) || null
);
/** Cannot promote this bot while another holds the Manager slot. */
const managerLocked = computed(() => !!otherManager.value && !props.bot.is_manager);
const managerHint = computed(() => {
  if (managerLocked.value) {
    return t("details.isManagerTaken", { name: otherManager.value.label || otherManager.value.name });
  }
  return t("details.isManagerHint");
});

const deskLabel = computed(() => {
  const d = props.bot.desk;
  if (!d || d.state === "absent") return t("desk.absent");
  if (d.state === "creating") return t("desk.creating");
  if (d.state === "running") return t("desk.running");
  if (d.state === "sleeping") return t("desk.sleeping");
  if (d.state === "error") return d.last_error || t("desk.createFailed");
  return d.state || "";
});

async function onModel(next) {
  const i = state.bots.findIndex((b) => b.name === props.bot.name);
  const prev = i >= 0 ? state.bots[i].model : props.bot.model;
  if (i >= 0) state.bots[i] = { ...state.bots[i], model: next };
  try {
    await api.patchBot(props.bot.name, { model: next });
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
