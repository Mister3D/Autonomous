<template>
  <div class="details">
    <h3>{{ t("settings.title") }}</h3>
    <div class="field-block">
      <strong>{{ t("details.model") }}</strong>
      <small>{{ t("details.modelHint") }}</small>
      <ModelPicker :model="bot.model || ''" @update:model="onModel" />
    </div>
    <div v-if="bot.pi_session_id" class="info-row">
      <span>
        <strong>{{ t("details.piSession") }}</strong>
        <small class="mono">{{ bot.pi_session_id }}</small>
      </span>
    </div>
    <label class="toggle-row">
      <span>
        <strong>{{ t("details.internet") }}</strong>
        <small>{{ t("details.internetHint") }}</small>
      </span>
      <input
        type="checkbox"
        role="switch"
        :checked="!!bot.internet"
        :aria-label="t('details.internet')"
        @change="toggleNet"
      />
    </label>
    <BotCompanion :bot="bot" />
    <label class="toggle-row">
      <span>
        <strong>{{ t("details.memoryAccess") }}</strong>
      </span>
      <input
        type="checkbox"
        role="switch"
        :checked="bot.memory_access !== false"
        :aria-label="t('details.memoryAccess')"
        @change="toggleMemory"
      />
    </label>
    <label class="toggle-row" :class="{ muted: managerLocked }">
      <span>
        <strong>{{ t("details.isManager") }}</strong>
        <small v-if="managerLocked">
          {{ t("details.isManagerTaken", { name: otherManager.label || otherManager.name }) }}
        </small>
        <small v-else>{{ t("details.isManagerHint") }}</small>
      </span>
      <input
        type="checkbox"
        role="switch"
        :checked="!!bot.is_manager"
        :disabled="managerLocked"
        :aria-label="t('details.isManager')"
        @change="toggleManager"
      />
    </label>
    <label class="toggle-row">
      <span>
        <strong>{{ t("details.autoSleep") }}</strong>
        <small>{{ t("details.autoSleepHint") }}</small>
      </span>
      <input
        type="checkbox"
        role="switch"
        :checked="bot.auto_sleep !== false"
        :aria-label="t('details.autoSleep')"
        @change="toggleSleep"
      />
    </label>
    <BotMcpGrants :bot="bot" />
    <div class="info-row">
      <span>
        <strong>{{ t("details.desk") }}</strong>
        <small>{{ deskLabel }}</small>
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

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();

const otherManager = computed(
  () => state.bots.find((b) => b.is_manager && b.name !== props.bot.name) || null
);
/** Cannot promote this bot while another holds the Manager slot. */
const managerLocked = computed(() => !!otherManager.value && !props.bot.is_manager);

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
