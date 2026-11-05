<template>
  <section class="settings-block">
    <h3>{{ t("llm.title") }}</h3>
    <p class="hint">{{ t("llm.hint") }}</p>
    <p class="hint">
      {{ t("llm.docsLead") }}
      <a :href="docsModels" target="_blank" rel="noopener noreferrer">{{ t("llm.docsModels") }}</a>
      ·
      <a :href="docsConfig" target="_blank" rel="noopener noreferrer">{{ t("llm.docsConfig") }}</a>
    </p>
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
    <div class="setup-toolbar">
      <button
        class="btn primary"
        type="button"
        :disabled="!providerDirty || providerSaving || !canSaveProvider"
        @click="saveProvider"
      >
        {{ providerSaving ? "…" : t("llm.saveProvider") }}
      </button>
      <span v-if="providerError" class="vault-error">{{ providerError }}</span>
    </div>

    <div class="settings-field llm-models-head">
      <span>{{ t("llm.modelsList") }}</span>
      <div class="settings-field-row">
        <button class="btn" type="button" :disabled="fetching || !form.base_url" @click="fetchModels">
          {{ fetching ? t("llm.fetching") : t("llm.fetchModels") }}
        </button>
        <button class="btn" type="button" @click="addBlankModel">{{ t("llm.addModel") }}</button>
      </div>
      <small v-if="fetchError" class="vault-error">{{ fetchError }}</small>
      <small v-else-if="fetched">{{ t("llm.modelsFound", { count: remoteModels.length }) }}</small>
      <small v-else>{{ t("llm.modelsListHint") }}</small>
    </div>

    <div v-if="remoteModels.length" class="llm-remote-pick">
      <ModelCombo v-model.trim="pickRemote" :options="remoteModels" :placeholder="t('llm.modelPlaceholder')" />
      <button class="btn" type="button" :disabled="!pickRemote" @click="addRemoteModel">
        {{ t("llm.addFromList") }}
      </button>
    </div>

    <ul v-if="form.models.length" class="llm-model-list">
      <li v-for="(m, idx) in form.models" :key="m._key" class="llm-model-card">
        <div class="llm-model-card-top">
          <strong>{{ m.name || m.id || t("llm.newModel") }}</strong>
          <button
            class="btn danger-ghost"
            type="button"
            :disabled="form.models.length <= 1 || m._saving"
            @click="removeModel(idx)"
          >
            {{ t("llm.removeModel") }}
          </button>
        </div>
        <label class="settings-field">
          <span>{{ t("llm.model") }}</span>
          <input v-model.trim="m.id" type="text" :placeholder="t('llm.modelPlaceholder')" spellcheck="false" />
        </label>
        <label class="settings-field">
          <span>{{ t("llm.modelName") }}</span>
          <input v-model.trim="m.name" type="text" :placeholder="m.id || t('llm.modelNamePlaceholder')" />
          <small>{{ t("llm.modelNameHint") }}</small>
        </label>
        <label class="toggle-row">
          <span>
            <strong>{{ t("llm.images") }}</strong>
            <small>{{ t("llm.imagesHint") }}</small>
          </span>
          <input v-model="m.images" type="checkbox" role="switch" :aria-label="t('llm.images')" />
        </label>
        <div class="llm-limits-grid">
          <label class="settings-field">
            <span>{{ t("llm.maxImages") }}</span>
            <input v-model.number="m.max_images" type="number" min="1" max="32" step="1" placeholder="—" />
            <small>{{ t("llm.maxImagesHint") }}</small>
          </label>
          <label class="settings-field">
            <span>{{ t("llm.contextWindow") }}</span>
            <input v-model.number="m.context_window" type="number" min="1024" step="1024" placeholder="128000" />
            <small>{{ t("llm.contextWindowHint") }}</small>
          </label>
          <label class="settings-field">
            <span>{{ t("llm.maxTokens") }}</span>
            <input v-model.number="m.max_tokens" type="number" min="256" step="256" placeholder="16384" />
            <small>{{ t("llm.maxTokensHint") }}</small>
          </label>
        </div>
        <div class="llm-model-actions">
          <button
            class="btn primary"
            type="button"
            :disabled="!isModelDirty(m) || m._saving || !canSaveModel(m)"
            @click="saveModel(m)"
          >
            {{ m._saving ? "…" : t("llm.save") }}
          </button>
          <span v-if="m._error" class="vault-error">{{ m._error }}</span>
        </div>
      </li>
    </ul>
    <p v-else class="hint">{{ t("llm.noModels") }}</p>

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

let keySeq = 0;

function normNum(v) {
  if (v === "" || v == null || Number.isNaN(Number(v))) return null;
  return Number(v);
}

function modelFingerprint(m) {
  return JSON.stringify({
    id: String(m.id || "").trim(),
    name: String(m.name || "").trim(),
    images: !!m.images,
    max_images: normNum(m.max_images),
    context_window: normNum(m.context_window),
    max_tokens: normNum(m.max_tokens),
  });
}

function blankModel(partial = {}) {
  keySeq += 1;
  const row = {
    _key: `m-${keySeq}`,
    id: "",
    name: "",
    images: true,
    max_images: null,
    context_window: null,
    max_tokens: null,
    _saving: false,
    _error: "",
    _saved: "",
    ...partial,
  };
  if (!row._saved) row._saved = modelFingerprint(row);
  return row;
}

function markClean(m) {
  m._saved = modelFingerprint(m);
  m._error = "";
}

function isModelDirty(m) {
  return modelFingerprint(m) !== m._saved;
}

const { t } = useI18n();
const view = ref(null);
const loadError = ref("");
const form = reactive({
  provider: "",
  newProvider: "",
  base_url: "",
  api_key: "",
  models: [blankModel()],
});
const providerSaved = ref({ provider: "", base_url: "", api_key: "" });
const providerSaving = ref(false);
const providerError = ref("");
const remoteModels = ref([]);
const pickRemote = ref("");
const fetching = ref(false);
const fetched = ref(false);
const fetchError = ref("");

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
const docsModels = computed(
  () => view.value?.docs?.models || "https://pi.dev/docs/latest/models",
);
const docsConfig = computed(
  () => view.value?.docs?.configuration || "https://pi.dev/docs/latest/models-configuration",
);

const providerId = computed(() =>
  existing.value ? form.provider : form.newProvider || (!providers.value.length ? "autonomous" : ""),
);

const providerDirty = computed(() => {
  const cur = {
    provider: providerId.value,
    base_url: String(form.base_url || "").trim(),
    api_key: String(form.api_key || ""),
  };
  const saved = providerSaved.value;
  if (cur.base_url !== saved.base_url) return true;
  if (cur.provider !== saved.provider) return true;
  if (cur.api_key) return true; // typed key always counts as a change
  return false;
});

const canSaveProvider = computed(
  () => !!form.base_url && !!providerId.value,
);

function canSaveModel(m) {
  return !!form.base_url && !!providerId.value && !!String(m.id || "").trim();
}

function rememberProviderClean() {
  providerSaved.value = {
    provider: providerId.value,
    base_url: String(form.base_url || "").trim(),
    api_key: "",
  };
  form.api_key = "";
  providerError.value = "";
}

function fillFrom(name) {
  const p = providers.value.find((x) => x.provider === name);
  form.api_key = "";
  remoteModels.value = [];
  pickRemote.value = "";
  fetched.value = false;
  fetchError.value = "";
  providerError.value = "";
  if (!p) {
    form.base_url = "";
    form.models = [blankModel()];
    rememberProviderClean();
    return;
  }
  form.base_url = p.base_url || "";
  const rows = (p.models || []).map((m) => {
    const row = blankModel({
      id: m.id || "",
      name: m.name || "",
      images: m.images !== false,
      max_images: m.max_images ?? null,
      context_window: m.context_window ?? null,
      max_tokens: m.max_tokens ?? null,
    });
    markClean(row);
    return row;
  });
  form.models = rows.length ? rows : [blankModel()];
  rememberProviderClean();
}

function addBlankModel() {
  const row = blankModel();
  // New empty card starts clean until the user edits (no id yet → save stays disabled).
  markClean(row);
  form.models.push(row);
}

function addRemoteModel() {
  const id = String(pickRemote.value || "").trim();
  if (!id) return;
  if (form.models.some((m) => m.id === id)) {
    pickRemote.value = "";
    return;
  }
  const empty = form.models.find((m) => !String(m.id || "").trim());
  if (empty) {
    empty.id = id;
  } else {
    const row = blankModel({ id, images: true });
    // Fresh from server list → dirty so the user can save limits/name.
    row._saved = "";
    form.models.push(row);
  }
  pickRemote.value = "";
}

async function removeModel(idx) {
  const m = form.models[idx];
  if (!m || form.models.length <= 1) return;
  const id = String(m.id || "").trim();
  const wasSaved = id && m._saved && JSON.parse(m._saved || "{}").id === id;
  form.models.splice(idx, 1);
  if (!wasSaved || !providerId.value || !form.base_url) return;
  // Persist removal: rewrite provider models list without this id.
  try {
    const models = form.models
      .map((row) => ({
        id: String(row.id || "").trim(),
        name: String(row.name || "").trim(),
        images: !!row.images,
        max_images: normNum(row.max_images),
        context_window: normNum(row.context_window),
        max_tokens: normNum(row.max_tokens),
      }))
      .filter((row) => !!row.id);
    if (!models.length) return;
    view.value = await api.saveSetupLlm({
      provider: providerId.value,
      base_url: form.base_url,
      api_key: form.api_key,
      models,
    });
    form.provider = view.value.providers[0]?.provider || form.provider;
    fillFrom(form.provider);
    refreshSetup(true);
  } catch (e) {
    loadError.value = e.message;
  }
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
  } catch (e) {
    remoteModels.value = [];
    fetchError.value = e.message;
  } finally {
    fetching.value = false;
  }
}

async function saveProvider() {
  if (!providerDirty.value || !canSaveProvider.value) return;
  providerSaving.value = true;
  providerError.value = "";
  try {
    // Keep existing models; upsert first model as no-op anchor if list empty.
    const models = form.models
      .map((row) => ({
        id: String(row.id || "").trim(),
        name: String(row.name || "").trim(),
        images: !!row.images,
        max_images: normNum(row.max_images),
        context_window: normNum(row.context_window),
        max_tokens: normNum(row.max_tokens),
      }))
      .filter((row) => !!row.id);
    if (!models.length) {
      providerError.value = t("llm.noModels");
      return;
    }
    view.value = await api.saveSetupLlm({
      provider: providerId.value,
      base_url: form.base_url,
      api_key: form.api_key,
      models,
    });
    form.provider = view.value.providers[0]?.provider || form.provider;
    fillFrom(form.provider);
    refreshSetup(true);
  } catch (e) {
    providerError.value = e.message;
  } finally {
    providerSaving.value = false;
  }
}

async function saveModel(m) {
  if (!isModelDirty(m) || !canSaveModel(m)) return;
  m._saving = true;
  m._error = "";
  try {
    view.value = await api.saveSetupLlm({
      provider: providerId.value,
      base_url: form.base_url,
      api_key: form.api_key,
      model: String(m.id || "").trim(),
      model_name: String(m.name || "").trim(),
      images: !!m.images,
      max_images: normNum(m.max_images),
      context_window: normNum(m.context_window),
      max_tokens: normNum(m.max_tokens),
    });
    form.provider = view.value.providers[0]?.provider || form.provider;
    form.api_key = "";
    rememberProviderClean();
    // Refresh this card from server payload so fingerprint matches.
    const prov = (view.value.providers || []).find((p) => p.provider === form.provider);
    const saved = (prov?.models || []).find((x) => x.id === String(m.id || "").trim());
    if (saved) {
      m.id = saved.id || m.id;
      m.name = saved.name || "";
      m.images = saved.images !== false;
      m.max_images = saved.max_images ?? null;
      m.context_window = saved.context_window ?? null;
      m.max_tokens = saved.max_tokens ?? null;
    }
    markClean(m);
    refreshSetup(true);
  } catch (e) {
    m._error = e.message;
  } finally {
    m._saving = false;
  }
}

onMounted(load);
</script>
