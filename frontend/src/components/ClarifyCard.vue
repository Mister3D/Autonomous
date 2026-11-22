<template>
  <div class="chat-request-card clarify-card" :class="state">
    <header class="chat-request-card-head clarify-card-head">
      <strong>{{ title }}</strong>
      <span class="chat-request-card-state clarify-state">{{ stateLabel }}</span>
    </header>
    <p class="clarify-prompt">{{ prompt }}</p>

    <template v-if="pending">
      <p v-if="error" class="clarify-error">{{ error }}</p>
      <div v-if="choices.length" class="clarify-choices">
        <UiButton
          v-for="label in choices"
          :key="label"
          type="button"
          class="clarify-choice"
          :disabled="busy"
          @click="submit({ choice: label })"
        >
          {{ label }}
        </UiButton>
      </div>
      <form v-if="allowText" class="clarify-text" @submit.prevent="submitText">
        <p v-if="choices.length" class="clarify-or">{{ t("clarify.or") }}</p>
        <div class="clarify-text-row">
          <input
            v-model="draft"
            type="text"
            :maxlength="500"
            :placeholder="t('clarify.placeholder')"
            :disabled="busy"
            :aria-label="t('clarify.placeholder')"
          />
          <UiButton variant="primary" type="submit" :disabled="busy || !draft.trim()">
            {{ t("clarify.send") }}
          </UiButton>
        </div>
      </form>
    </template>
    <p v-else class="clarify-resolved">{{ resolvedText }}</p>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { maybeContinueFirstChatPrefs } from "../firstChatPrefs";
import UiButton from "./ui/UiButton.vue";

const props = defineProps({
  message: { type: Object, required: true },
});

const { t } = useI18n();
const busy = ref(false);
const error = ref("");
const draft = ref("");

const meta = computed(() => props.message.meta || {});
const state = computed(() => meta.value.state || "pending");
const pending = computed(() => state.value === "pending");
const title = computed(() => meta.value.title || t("clarify.title"));
const prompt = computed(() => meta.value.prompt || props.message.content || "");
const choices = computed(() =>
  Array.isArray(meta.value.choices) ? meta.value.choices.filter(Boolean) : []
);
const allowText = computed(() => {
  if (isLanguageChoice(meta.value.title, meta.value.prompt, choices.value)) return true;
  if (typeof meta.value.allow_text === "boolean") return meta.value.allow_text;
  return choices.value.length === 0;
});

function isLanguageChoice(title, prompt, labels) {
  const blob = `${title || ""}\n${prompt || ""}\n${(labels || []).join("\n")}`.toLowerCase();
  const asks = blob.includes("langue") || blob.includes("language");
  const hasFr = blob.includes("français") || blob.includes("francais");
  const hasEn = blob.includes("english") || blob.includes("anglais");
  return asks && hasFr && hasEn;
}

const stateLabel = computed(() => {
  if (state.value === "answered") return t("clarify.answered");
  if (state.value === "cancelled") return t("clarify.cancelled");
  return t("clarify.pending");
});

const resolvedText = computed(() => {
  if (state.value === "cancelled") return t("clarify.resolvedCancelled");
  const answer = String(meta.value.answer || "").trim();
  if (answer) return t("clarify.resolvedAnswer", { answer });
  return t("clarify.resolvedAnswer", { answer: "—" });
});

async function submit(body) {
  const id = meta.value.request_id;
  if (!id || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.resolveClarify(id, body);
    draft.value = "";
    const answer = String(body.choice || body.text || "").trim();
    const bot = props.message.bot;
    try {
      await maybeContinueFirstChatPrefs(bot, answer);
    } catch (e) {
      error.value = e.message || String(e);
    }
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}

function submitText() {
  const text = draft.value.trim();
  if (!text) return;
  submit({ text });
}
</script>
