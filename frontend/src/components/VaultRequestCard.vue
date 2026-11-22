<template>
  <div class="chat-request-card vault-card" :class="state">
    <header class="chat-request-card-head vault-card-head">
      <strong>{{ title }}</strong>
      <span class="chat-request-card-state vault-state">{{ stateLabel }}</span>
    </header>
    <p v-if="meta.reason" class="vault-reason">{{ meta.reason }}</p>
    <p v-if="meta.origin" class="vault-meta-line">
      {{ t("vault.origin") }}: <code>{{ meta.origin }}</code>
    </p>
    <p v-if="meta.label && kind === 'access'" class="vault-meta-line">
      {{ t("vault.label") }}: {{ meta.label }}
    </p>

    <template v-if="pending">
      <form class="vault-form" @submit.prevent="submit('approve')">
        <template v-if="kind === 'access'">
          <p class="vault-hint">{{ t("vault.accessHint") }}</p>
          <label v-if="entries.length" class="vault-entry-pick">
            <span>{{ t("vault.entry") }}</span>
            <MenuSelect
              v-model="entryId"
              :options="entryOptions"
              :placeholder="t('vault.pickEntry')"
              :aria-label="t('vault.entry')"
              allow-empty
              field
            />
          </label>
          <p v-else class="vault-hint warn">{{ t("vault.empty") }}</p>
        </template>
        <template v-else>
          <label v-if="showLabelInput">
            <span>{{ t("vault.label") }}</span>
            <input v-model="entryLabel" type="text" autocomplete="off" />
          </label>
          <label v-for="field in formFields" :key="field.id">
            <span>{{ field.label }}</span>
            <SecretInput
              v-if="field.secret"
              v-model="values[field.id]"
              autocomplete="off"
              :required="field.required !== false"
              :disabled="busy"
            />
            <input
              v-else
              v-model="values[field.id]"
              type="text"
              autocomplete="username"
              :required="field.required !== false"
            />
          </label>
        </template>
        <p class="vault-hint">{{ t("vault.neverLlm") }}</p>
        <p v-if="error" class="vault-error">{{ error }}</p>
        <div class="chat-request-card-actions vault-actions">
          <UiButton variant="ghost" type="button" :disabled="busy" @click="submit('deny')">
            {{ t("vault.deny") }}
          </UiButton>
          <UiButton variant="primary" type="submit" :disabled="busy || !canApprove">
            {{ t("vault.approve") }}
          </UiButton>
        </div>
      </form>
    </template>
    <p v-else class="vault-resolved">{{ resolvedText }}</p>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import MenuSelect from "./MenuSelect.vue";
import SecretInput from "./SecretInput.vue";
import UiButton from "./ui/UiButton.vue";

const props = defineProps({
  message: { type: Object, required: true },
});

const { t } = useI18n();
const busy = ref(false);
const error = ref("");
const entries = ref([]);
const entryId = ref("");
const entryLabel = ref("");
const values = reactive({});

const meta = computed(() => props.message.meta || {});
const kind = computed(() => meta.value.request_kind || "credential");
const state = computed(() => meta.value.state || "pending");
const pending = computed(() => state.value === "pending");

const defaultLoginFields = [
  { id: "username", label: t("vault.username"), secret: false, required: true },
  { id: "password", label: t("vault.password"), secret: true, required: true },
];
const defaultSecretFields = [
  { id: "secret", label: t("vault.secret"), secret: true, required: true },
];

const formFields = computed(() => {
  const fromAgent = Array.isArray(meta.value.fields) ? meta.value.fields : [];
  if (fromAgent.length) return fromAgent;
  if (kind.value === "login") return defaultLoginFields;
  if (kind.value === "secret") return defaultSecretFields;
  return defaultSecretFields;
});

const showLabelInput = computed(() => kind.value !== "access");

const entryOptions = computed(() =>
  entries.value.map((e) => ({
    value: e.id,
    label: e.label,
    meta: e.kind || "",
  })),
);

const title = computed(() => {
  if (meta.value.label && kind.value !== "access") return meta.value.label;
  if (kind.value === "login") return t("vault.requestLogin");
  if (kind.value === "access") return t("vault.requestAccess");
  if (kind.value === "credential") return t("vault.requestCredential");
  return t("vault.requestSecret");
});

const stateLabel = computed(() => {
  if (state.value === "approved") return t("vault.approved");
  if (state.value === "denied") return t("vault.denied");
  if (state.value === "cancelled") return t("vault.cancelled");
  return t("vault.pending");
});

const resolvedText = computed(() => props.message.content || stateLabel.value);

const canApprove = computed(() => {
  if (kind.value === "access") return Boolean(entryId.value || meta.value.entry_id);
  return formFields.value.every((f) => {
    if (f.required === false) return true;
    return Boolean(String(values[f.id] || "").trim());
  });
});

function initValues() {
  entryLabel.value = meta.value.label || "";
  entryId.value = meta.value.entry_id || "";
  for (const field of formFields.value) {
    if (values[field.id] === undefined) values[field.id] = "";
  }
}

onMounted(async () => {
  initValues();
  if (kind.value !== "access" || !pending.value) return;
  try {
    entries.value = await api.vaultEntries();
    if (!entryId.value && meta.value.entry_id) entryId.value = meta.value.entry_id;
  } catch (e) {
    error.value = e.message;
  }
});

async function submit(action) {
  if (busy.value) return;
  error.value = "";
  busy.value = true;
  try {
    const body = { action };
    if (action === "approve") {
      if (kind.value === "access") {
        body.entry_id = entryId.value || meta.value.entry_id;
      } else {
        body.label = entryLabel.value.trim() || meta.value.label || "";
        body.origin = meta.value.origin || "";
        body.values = {};
        for (const field of formFields.value) {
          body.values[field.id] = values[field.id] || "";
        }
      }
    }
    await api.resolveVaultRequest(meta.value.request_id, body);
    for (const field of formFields.value) {
      if (field.secret) values[field.id] = "";
    }
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}
</script>
