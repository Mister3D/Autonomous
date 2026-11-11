<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="modal-backdrop"
      @click.self="emit('close')"
    >
      <div
        class="modal events-instruction-modal"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
      >
        <header class="events-instruction-head">
          <p class="events-instruction-kind">{{ kindLabel }}</p>
          <h2 :id="titleId">{{ displayName }}</h2>
        </header>
        <div class="events-instruction-scroll">
          <template v-if="showPayload">
            <p class="events-instruction-label">{{ t("chat.webhookPayload") }}</p>
            <pre class="events-instruction-body events-payload-pre">{{ payloadText }}</pre>
          </template>
          <p class="events-instruction-label">{{ t("events.instructionLabel") }}</p>
          <p class="events-instruction-body">{{ displayText }}</p>
        </div>
        <div class="events-instruction-actions">
          <button type="button" class="btn primary" @click="emit('close')">
            {{ t("events.closeInstruction") }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps({
  open: { type: Boolean, default: false },
  name: { type: String, default: "" },
  instruction: { type: String, default: "" },
  kind: { type: String, default: "webhook" },
  showPayload: { type: Boolean, default: false },
  payload: { type: String, default: "" },
});

const emit = defineEmits(["close"]);
const { t } = useI18n();
const titleId = "event-instruction-title";

const displayName = computed(() => String(props.name || "").trim() || "—");
const displayText = computed(() => {
  const text = String(props.instruction || "").trim();
  return text || t("events.instructionEmpty");
});
const payloadText = computed(() => {
  const text = String(props.payload || "").trim();
  return text || t("chat.webhookPayloadEmpty");
});
const kindLabel = computed(() =>
  props.kind === "schedule" ? t("chat.scheduleLabel") : t("chat.webhookLabel")
);
</script>
