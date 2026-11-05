<template>
  <div class="agent-resume-card" :class="state">
    <header class="agent-resume-head">
      <strong>{{ t("chat.resumeTitle") }}</strong>
      <span class="agent-resume-state">{{ stateLabel }}</span>
    </header>
    <p class="agent-resume-body">{{ message.content || t("chat.resumeBody") }}</p>
    <div v-if="pending" class="agent-resume-actions">
      <button type="button" class="btn primary" :disabled="busy" @click="resume">
        {{ busy ? t("chat.resuming") : t("chat.resume") }}
      </button>
    </div>
    <p v-else-if="error" class="agent-resume-error">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";

const props = defineProps({
  message: { type: Object, required: true },
});

const { t } = useI18n();
const busy = ref(false);
const error = ref("");

const meta = computed(() => props.message.meta || {});
const state = computed(() => meta.value.state || "pending");
const pending = computed(() => state.value === "pending");

const stateLabel = computed(() => {
  if (state.value === "resumed") return t("chat.resumeDone");
  if (state.value === "dismissed") return t("chat.resumeDismissed");
  return t("chat.resumePending");
});

async function resume() {
  if (busy.value || !pending.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.resumeBot(props.message.bot);
  } catch (e) {
    error.value = e?.message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>
