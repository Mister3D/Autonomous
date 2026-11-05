<template>
  <section class="settings-block">
    <h3>{{ t("llm.title") }}</h3>
    <p class="hint">{{ t("llm.hint") }}</p>
    <p v-if="loadError" class="vault-error">{{ loadError }}</p>
    <label v-if="providers.length > 1" class="settings-field">
      <span>{{ t("llm.provider") }}</span>
      <select v-model="form.provider" @change="fillFrom(form.provider)">
        <option v-for="p in providers" :key="p.provider" :value="p.provider">{{ p.provider }}</option>
        <option value="">{{ t("llm.newProvider") }}</option>
      </select>
    </label>
    <label v-if="!providers.length || !existing" class="settings-field">
      <span>{{ t("llm.providerId") }}</span>
      <input v-model.trim="form.newProvider" type="text" placeholder="autonomous" spellcheck="false" />
    </label>
    <label class="settings-field">
      <span>{{ t("llm.baseUrl") }}</span>
      <input v-model.trim="form.base_url" type="url" placeholder="https://api.example.com/v1" spellcheck="false" />
      <small>{{ t("llm.baseUrlHint") }}</small>
    </label>
    <label class="settings-field">
      <span>{{ t("llm.apiKey") }}</span>
      <SecretInput v-model="form.api_key" :placeholder="keyPlaceholder" autocomplete="new-password" />
      <small>{{ keyHint }}</small>
    </label>
    <div class="settings-field">
      <span>{{ t("llm.model") }}</span>
      <div class="settings-field-row">
        <ModelCombo v-model.trim="form.model" :options="remoteModels" :placeholder="t('llm.modelPlaceholder')" />
        <button class="btn" type="button" :disabled="fetching || !form.base_url" @click="fetchModels">
          {{ fetching ? t("llm.fetching") : t("llm.fetchModels") }}
        </button>
      </div>
      <small v-if="fetchError" class="vault-error">{{ fetchError }}</small>
      <small v-else-if="fetched">{{ t("llm.modelsFound", { count: remoteModels.length }) }}</small>
      <small v-else>{{ t("llm.modelHint") }}</small>
    </div>
    <label class="settings-field">
      <span>{{ t("llm.modelName") }}</span>
      <input v-model.trim="form.model_name" type="text" :placeholder="form.model" />
    </label>
    <label class="toggle-row">
      <span>
        <strong>{{ t("llm.images") }}</strong>
        <small>{{ t("llm.imagesHint") }}</small>
      </span>
      <input v-model="form.images" type="checkbox" role="switch" :aria-label="t('llm.images')" />
    </label>
    <div class="setup-toolbar">
      <button class="btn primary" type="button" :disabled="saving || !canSave" @click="save">
        {{ saving ? "…" : t("llm.save") }}
      </button>
      <span v-if="saved" class="setup-ok">{{ t("llm.saved") }}</span>
      <span v-if="saveError" class="vault-error">{{ saveError }}</span>
    </div>
    <p class="hint">{{ t("llm.fileNote", { path: view?.path || "~/.pi/agent/models.json" }) }}</p>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { refreshSetup } from "../store";
import ModelCombo from "./ModelCombo.vue";
import SecretInput from "./SecretInput.vue";

const { t } = useI18n();
const view = ref(null);
const loadError = ref("");
const form = reactive({ provider: "", newProvider: "", base_url: "", api_key: "", model: "", model_name: "", images: true });
const remoteModels = ref([]);
const fetching = ref(false);
const fetched = ref(false);
const fetchError = ref("");
const saving = ref(false);
const saved = ref(false);
const saveError = ref("");

const providers = computed(() => view.value?.providers || []);
const existing = computed(() => providers.value.find((p) => p.provider === form.provider) || null);
const keyInfo = computed(() => existing.value?.api_key || { set: false, hint: "", source: "none" });
const keyPlaceholder = computed(() =>
  keyInfo.value.set ? t("secret.keepCurrent", { hint: keyInfo.value.hint || "" }) : t("llm.apiKeyPlaceholder"),
);
const keyHint = computed(() => {
  const src = keyInfo.value.source || "";
  if (src.startsWith("env:")) return t("llm.keyFromEnv", { name: src.slice(4) });
  if (src === "command") return t("llm.keyFromCommand");
  return t("llm.apiKeyHint");
});
const canSave = computed(() => !!form.base_url && !!form.model && (!!existing.value || !!form.newProvider || !providers.value.length));

function fillFrom(name) {
  const p = providers.value.find((x) => x.provider === name);
  form.api_key = "";
  remoteModels.value = [];
  fetched.value = false;
  fetchError.value = "";
  if (!p) {
    Object.assign(form, { base_url: "", model: "", model_name: "", images: true });
    return;
  }
  const m = p.models[0] || {};
  Object.assign(form, { base_url: p.base_url, model: m.id || "", model_name: m.name || "", images: m.images !== false });
}

async function load() {
  try {
    view.value = await api.setupLlm();
    const first = providers.value[0];
    form.provider = first ? first.provider : "";
    fillFrom(form.provider);
  } catch (e) {
    loadError.value = e.message;
  }
}

async function fetchModels() {
  fetching.value = true;
  fetched.value = false;
  fetchError.value = "";
  try {
    const r = await api.setupLlmModels({
      provider: existing.value ? form.provider : form.newProvider,
      base_url: form.base_url,
      api_key: form.api_key,
    });
    remoteModels.value = r.models || [];
    fetched.value = true;
    if (!form.model && remoteModels.value.length === 1) form.model = remoteModels.value[0];
  } catch (e) {
    remoteModels.value = [];
    fetchError.value = e.message;
  } finally {
    fetching.value = false;
  }
}

async function save() {
  saving.value = true;
  saved.value = false;
  saveError.value = "";
  try {
    view.value = await api.saveSetupLlm({
      provider: existing.value ? form.provider : form.newProvider || "autonomous",
      base_url: form.base_url,
      api_key: form.api_key,
      model: form.model,
      model_name: form.model_name,
      images: form.images,
    });
    form.provider = view.value.providers[0]?.provider || form.provider;
    form.api_key = "";
    saved.value = true;
    refreshSetup(true);
  } catch (e) {
    saveError.value = e.message;
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
