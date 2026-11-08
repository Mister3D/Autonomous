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
      :hint="t('details.isManagerHint')"
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
const managerLockReason = computed(() =>
  managerLocked.value
    ? t("details.isManagerTaken", { name: otherManager.value.label || otherManager.value.name })
    : "",
);

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
