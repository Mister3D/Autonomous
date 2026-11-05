<template>
  <div class="desk-req-card" :class="stateName">
    <header class="desk-req-head">
      <strong>{{ t("shell.requestTitle") }}</strong>
      <span class="desk-req-state">{{ stateLabel }}</span>
    </header>
    <p v-if="reason" class="desk-req-hint">{{ reason }}</p>
    <p v-else class="desk-req-hint">{{ t("shell.requestHint") }}</p>

    <template v-if="pending">
      <p v-if="error" class="desk-req-error">{{ error }}</p>
      <div class="desk-req-actions">
        <button type="button" class="btn ghost" :disabled="busy" @click="deny">
          {{ t("shell.requestDeny") }}
        </button>
        <button type="button" class="btn primary" :disabled="busy" @click="approve">
          {{ busy ? t("desk.working") : t("shell.requestApprove") }}
        </button>
      </div>
    </template>

    <p v-else class="desk-req-resolved">{{ resolvedText }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { state } from "../store";

const props = defineProps({
  message: { type: Object, required: true },
});

const { t } = useI18n();
const busy = ref(false);
const error = ref("");

const meta = computed(() => props.message.meta || {});
const stateName = computed(() => meta.value.state || "pending");
const pending = computed(() => stateName.value === "pending");
const reason = computed(() => (meta.value.reason || "").trim());

const stateLabel = computed(() => {
  if (stateName.value === "approved") return t("shell.requestApproved");
  if (stateName.value === "denied") return t("shell.requestDenied");
  return t("shell.requestPending");
});

const resolvedText = computed(() =>
  stateName.value === "denied" ? t("shell.requestDenied") : t("shell.requestApproved"),
);

async function refreshBot() {
  try {
    const bot = await api.getBot(props.message.bot);
    const i = state.bots.findIndex((b) => b.name === bot.name);
    if (i >= 0) state.bots[i] = bot;
  } catch {
    /* ignore */
  }
}

async function approve() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.shellRequestResolve(props.message.bot, "approve");
    await refreshBot();
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function deny() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.shellRequestResolve(props.message.bot, "deny");
    await refreshBot();
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>
