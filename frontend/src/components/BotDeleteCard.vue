<template>
  <div class="bot-delete-card" :class="state">
    <header class="bot-delete-card-head">
      <strong>{{ title }}</strong>
      <span class="bot-delete-state">{{ stateLabel }}</span>
    </header>
    <p v-if="prompt" class="bot-delete-prompt">{{ prompt }}</p>

    <ul v-if="rows.length" class="bot-delete-list">
      <li v-for="row in rows" :key="row.name">
        <label class="bot-delete-row">
          <input
            v-model="row.selected"
            type="checkbox"
            :disabled="!pending || busy"
          />
          <BotAvatar class="bot-delete-av" :bot="avatarBot(row)" size="sm" />
          <span class="bot-delete-label">{{ row.label || row.name }}</span>
          <small v-if="row.label && row.label !== row.name">@{{ row.name }}</small>
        </label>
      </li>
    </ul>

    <template v-if="pending">
      <p v-if="error" class="bot-delete-error">{{ error }}</p>
      <div class="bot-delete-actions">
        <button type="button" class="btn ghost" :disabled="busy" @click="resolve('deny')">
          {{ t("botDelete.cancel") }}
        </button>
        <button
          type="button"
          class="btn primary bot-delete-confirm"
          :disabled="busy || !selectedNames.length"
          @click="resolve('confirm')"
        >
          {{ t("botDelete.confirm") }}
        </button>
      </div>
    </template>
    <p v-else class="bot-delete-resolved">{{ resolvedText }}</p>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import BotAvatar from "./BotAvatar.vue";

const props = defineProps({
  message: { type: Object, required: true },
  botName: { type: String, required: true },
});

const { t } = useI18n();
const busy = ref(false);
const error = ref("");
const rows = reactive([]);

const meta = computed(() => props.message.meta || {});
const state = computed(() => meta.value.state || "pending");
const pending = computed(() => state.value === "pending");
const title = computed(() => meta.value.title || t("botDelete.title"));
const prompt = computed(() => meta.value.prompt || "");

const selectedNames = computed(() =>
  rows.filter((r) => r.selected).map((r) => r.name),
);

function syncRows(list) {
  rows.splice(0, rows.length);
  for (const b of list || []) {
    rows.push({
      name: b.name,
      label: b.label || b.name,
      avatar: b.avatar || "",
      avatar_color: b.avatar_color ?? 0,
      selected: b.selected !== false,
    });
  }
}

watch(
  () => meta.value.bots,
  (list) => syncRows(list),
  { immediate: true, deep: true },
);

function avatarBot(row) {
  return {
    name: row.name,
    label: row.label,
    avatar: row.avatar,
    avatar_color: row.avatar_color,
    status: "idle",
  };
}

const stateLabel = computed(() => {
  if (state.value === "confirmed") return t("botDelete.confirmed");
  if (state.value === "denied") return t("botDelete.denied");
  if (state.value === "cancelled") return t("botDelete.cancelled");
  return t("botDelete.pending");
});

const resolvedText = computed(() => {
  const deleted = meta.value.result?.deleted || [];
  if (state.value === "confirmed") {
    return deleted.length
      ? t("botDelete.resolvedDeleted", { list: deleted.map((n) => `@${n}`).join(", ") })
      : t("botDelete.resolvedNone");
  }
  if (state.value === "cancelled") return t("botDelete.resolvedCancelled");
  return t("botDelete.resolvedDenied");
});

async function resolve(action) {
  const id = meta.value.request_id;
  if (!id || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.resolveBotDelete(props.botName, id, {
      action,
      bots: action === "confirm" ? selectedNames.value : [],
    });
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>
