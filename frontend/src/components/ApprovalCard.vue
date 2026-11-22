<template>
  <div class="chat-request-card approval-card" :class="state">
    <header class="chat-request-card-head approval-card-head">
      <strong>{{ title }}</strong>
      <span class="chat-request-card-state approval-state">{{ stateLabel }}</span>
    </header>
    <p class="approval-prompt">{{ prompt }}</p>

    <template v-if="pending">
      <p v-if="error" class="approval-error">{{ error }}</p>
      <div class="chat-request-card-actions approval-actions">
        <UiButton variant="ghost" type="button" :disabled="busy" @click="resolve('deny')">
          {{ t("approval.refuse") }}
        </UiButton>
        <UiButton
          variant="primary"
          type="button"
          class="approval-accept"
          :disabled="busy"
          @click="resolve('approve')"
        >
          {{ t("approval.accept") }}
        </UiButton>
      </div>
    </template>
    <p v-else class="approval-resolved">{{ resolvedText }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import UiButton from "./ui/UiButton.vue";

const props = defineProps({
  message: { type: Object, required: true },
});

const { t } = useI18n();
const busy = ref(false);
const error = ref("");

const meta = computed(() => props.message.meta || {});
const state = computed(() => meta.value.state || "pending");
const pending = computed(() => state.value === "pending");
const title = computed(() => meta.value.title || t("approval.title"));
const prompt = computed(() => meta.value.prompt || props.message.content || "");

const stateLabel = computed(() => {
  if (state.value === "approved") return t("approval.accepted");
  if (state.value === "denied") return t("approval.refused");
  if (state.value === "cancelled") return t("approval.cancelled");
  return t("approval.pending");
});

const resolvedText = computed(() => {
  if (state.value === "approved") return t("approval.resolvedAccepted");
  if (state.value === "cancelled") return t("approval.resolvedCancelled");
  return t("approval.resolvedRefused");
});

async function resolve(action) {
  const id = meta.value.request_id;
  if (!id || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.resolveApproval(id, { action });
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>
