<template>
  <div class="chat-request-card memory-card" :class="state">
    <header class="chat-request-card-head memory-card-head">
      <strong>{{ title }}</strong>
      <span class="chat-request-card-state memory-state">{{ stateLabel }}</span>
    </header>
    <p v-if="meta.reason" class="memory-reason">{{ meta.reason }}</p>
    <p class="memory-meta-line">
      {{ t("memory.key") }}: <code>{{ meta.key }}</code>
      · {{ tierLabel }}
    </p>
    <p v-if="meta.action === 'set' && meta.value" class="memory-meta-line memory-value">
      {{ t("memory.value") }}: {{ meta.value }}
    </p>
    <p v-if="meta.action === 'delete'" class="memory-hint">
      {{ t("memory.deleteHint") }}
    </p>
    <p class="memory-hint">{{ t("memory.nonBlocking") }}</p>

    <template v-if="pending">
      <p v-if="error" class="memory-error">{{ error }}</p>
      <div class="chat-request-card-actions memory-actions">
        <UiButton variant="ghost" type="button" :disabled="busy" @click="resolve('deny')">
          {{ t("memory.deny") }}
        </UiButton>
        <UiButton
          variant="primary"
          type="button"
          class="memory-confirm"
          :disabled="busy"
          @click="resolve('approve')"
        >
          {{ t("memory.confirm") }}
        </UiButton>
      </div>
    </template>
    <p v-else class="memory-resolved">{{ resolvedText }}</p>
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

const title = computed(() => {
  const label = meta.value.label || meta.value.key || "";
  if (meta.value.action === "delete") {
    return t("memory.proposalDelete", { label });
  }
  return t("memory.proposalSet", { label });
});

const tierLabel = computed(() =>
  meta.value.tier === "core" ? t("memory.tierCore") : t("memory.tierBrowse"),
);

const stateLabel = computed(() => {
  if (state.value === "approved") return t("memory.approved");
  if (state.value === "denied") return t("memory.denied");
  return t("memory.pending");
});

const resolvedText = computed(() => {
  if (state.value === "approved") return t("memory.resolvedApproved");
  if (state.value === "denied") return t("memory.resolvedDenied");
  return "";
});

async function resolve(action) {
  const id = meta.value.proposal_id;
  if (!id || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.resolveMemoryProposal(id, { action });
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>
