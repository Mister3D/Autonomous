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

    <h3 class="llm-subhead">{{ t("llm.providersTitle") }}</h3>
    <p class="hint">{{ t("llm.providersHint") }}</p>

    <ul v-if="providerDrafts.length" class="llm-provider-list">
      <li v-for="p in providerDrafts" :key="p._key" class="llm-provider-card">
        <div class="llm-model-card-top">
          <strong>{{ p._isNew ? t("llm.newProviderCard") : p.provider }}</strong>
          <button
            v-if="p._isNew"
            class="btn danger-ghost"
            type="button"
            @click="cancelNewProvider(p)"
          >
            {{ t("llm.cancel") }}
          </button>
        </div>
        <label v-if="p._isNew" class="settings-field">
          <span>{{ t("llm.providerId") }}</span>
          <input v-model.trim="p.provider" type="text" placeholder="autonomous" spellcheck="false" />
        </label>
        <label class="settings-field">
          <span>{{ t("llm.baseUrl") }}</span>
          <input
            v-model.trim="p.base_url"
            type="url"
            placeholder="https://api.example.com/v1"
            spellcheck="false"
          />
          <small>{{ t("llm.baseUrlHint") }}</small>
        </label>
        <label class="settings-field">
          <span>{{ t("llm.apiKey") }}</span>
          <SecretInput
            v-model="p.api_key"
            :placeholder="providerKeyPlaceholder(p)"
            autocomplete="new-password"
          />
          <small>{{ providerKeyHint(p) }}</small>
        </label>
        <div class="setup-toolbar">
          <button
            class="btn primary"
            type="button"
            :disabled="!isProviderDirty(p) || p._saving || !canSaveProvider(p)"
            @click="saveProvider(p)"
          >
            {{ p._saving ? "…" : t("llm.saveProvider") }}
          </button>
          <span v-if="p._ok" class="setup-ok">{{ p._ok }}</span>
          <span v-if="p._error" class="vault-error">{{ p._error }}</span>
        </div>
      </li>
    </ul>
    <p v-else class="hint">{{ t("llm.providersEmpty") }}</p>
    <div class="setup-toolbar">
      <button class="btn" type="button" :disabled="addingProvider" @click="startAddProvider">
        {{ t("llm.addProvider") }}
      </button>
    </div>

    <h3 class="llm-subhead">{{ t("llm.modelsTitle") }}</h3>
    <p class="hint">{{ t("llm.modelsHint") }}</p>

    <div class="llm-add-model">
      <label class="settings-field">
        <span>{{ t("llm.provider") }}</span>
        <select v-model="add.provider" :disabled="!savedProviders.length" @change="onAddProviderChange">
          <option disabled value="">{{ t("llm.pickProvider") }}</option>
          <option v-for="p in savedProviders" :key="p.provider" :value="p.provider">
            {{ p.provider }}
          </option>
        </select>
      </label>
      <div class="settings-field-row">
        <button
          class="btn"
          type="button"
          :disabled="!add.provider || fetching"
          @click="fetchModels"
        >
          {{ fetching ? t("llm.fetching") : t("llm.fetchModels") }}
        </button>
      </div>
      <small v-if="fetchError" class="vault-error">{{ fetchError }}</small>
      <small v-else-if="fetched">{{ t("llm.modelsFound", { count: remoteModels.length }) }}</small>
      <div v-if="remoteModels.length" class="llm-remote-pick">
        <ModelCombo
          v-model.trim="add.id"
          :options="remoteModels"
          :placeholder="t('llm.modelPlaceholder')"
        />
      </div>
      <label v-else class="settings-field">
        <span>{{ t("llm.model") }}</span>
        <input
          v-model.trim="add.id"
          type="text"
          :placeholder="t('llm.modelPlaceholder')"
          spellcheck="false"
          :disabled="!add.provider"
        />
      </label>
      <label class="settings-field">
        <span>{{ t("llm.modelName") }}</span>
        <input
          v-model.trim="add.name"
          type="text"
          :placeholder="add.id || t('llm.modelNamePlaceholder')"
          :disabled="!add.provider"
        />
        <small>{{ t("llm.modelNameHint") }}</small>
      </label>
      <label class="toggle-row">
        <span>
          <strong>{{ t("llm.images") }}</strong>
          <small>{{ t("llm.imagesHint") }}</small>
        </span>
        <input
          v-model="add.images"
          type="checkbox"
          role="switch"
          :aria-label="t('llm.images')"
          :disabled="!add.provider"
        />
      </label>
      <div class="llm-limits-grid">
        <label class="settings-field">
          <span>{{ t("llm.maxImages") }}</span>
          <input
            v-model.number="add.max_images"
            type="number"
            min="1"
            max="32"
            step="1"
            placeholder="—"
            :disabled="!add.provider"
          />
          <small>{{ t("llm.maxImagesHint") }}</small>
        </label>
        <label class="settings-field">
          <span>{{ t("llm.contextWindow") }}</span>
          <input
            v-model.number="add.context_window"
            type="number"
            min="1024"
            step="1024"
            placeholder="128000"
            :disabled="!add.provider"
          />
          <small>{{ t("llm.contextWindowHint") }}</small>
        </label>
        <label class="settings-field">
          <span>{{ t("llm.maxTokens") }}</span>
          <input
            v-model.number="add.max_tokens"
            type="number"
            min="256"
            step="256"
            placeholder="16384"
            :disabled="!add.provider"
          />
          <small>{{ t("llm.maxTokensHint") }}</small>
        </label>
      </div>
      <div class="setup-toolbar">
        <button
          class="btn primary"
          type="button"
          :disabled="!canAddModel || addSaving"
          @click="saveNewModel"
        >
          {{ addSaving ? "…" : t("llm.saveModel") }}
        </button>
        <span v-if="addError" class="vault-error">{{ addError }}</span>
      </div>
    </div>

    <ul v-if="modelRows.length" class="llm-model-list">
      <li v-for="(m, idx) in modelRows" :key="m._key" class="llm-model-card">
        <div class="llm-model-card-top">
          <strong>
            <span class="llm-provider-badge">{{ m.provider }}</span>
            {{ m.name || m.id || t("llm.newModel") }}
          </strong>
          <button
            class="btn danger-ghost"
            type="button"
            :disabled="m._saving"
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
            <input
              v-model.number="m.context_window"
              type="number"
              min="1024"
              step="1024"
              placeholder="128000"
            />
            <small>{{ t("llm.contextWindowHint") }}</small>
          </label>
          <label class="settings-field">
            <span>{{ t("llm.maxTokens") }}</span>
            <input
              v-model.number="m.max_tokens"
              type="number"
              min="256"
              step="256"
              placeholder="16384"
            />
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
    <p v-else class="hint">{{ t("llm.modelsEmpty") }}</p>

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
    provider: String(m.provider || "").trim(),
    id: String(m.id || "").trim(),
    name: String(m.name || "").trim(),
    images: !!m.images,
    max_images: normNum(m.max_images),
    context_window: normNum(m.context_window),
    max_tokens: normNum(m.max_tokens),
  });
}

function providerFingerprint(p) {
  return JSON.stringify({
    provider: String(p.provider || "").trim(),
    base_url: String(p.base_url || "").trim(),
    // typed key always dirties via isProviderDirty
  });
}

function blankModel(partial = {}) {
  keySeq += 1;
  const row = {
    _key: `m-${keySeq}`,
    provider: "",
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

function blankProvider(partial = {}) {
  keySeq += 1;
  const row = {
    _key: `p-${keySeq}`,
    provider: "",
    base_url: "",
    api_key: "",
    _isNew: false,
    _saving: false,
    _error: "",
    _ok: "",
    _saved: "",
    _keyInfo: { set: false, hint: "", source: "none" },
    ...partial,
  };
  if (!row._saved) row._saved = providerFingerprint(row);
  return row;
}

function markModelClean(m) {
  m._saved = modelFingerprint(m);
  m._error = "";
}

function markProviderClean(p) {
  p._saved = providerFingerprint(p);
  p.api_key = "";
  p._error = "";
}

function isModelDirty(m) {
  return modelFingerprint(m) !== m._saved;
}

function isProviderDirty(p) {
  if (p.api_key) return true;
  return providerFingerprint(p) !== p._saved;
}

const { t } = useI18n();
const view = ref(null);
const loadError = ref("");
const providerDrafts = ref([]);
const modelRows = ref([]);
const remoteModels = ref([]);
const fetching = ref(false);
const fetched = ref(false);
const fetchError = ref("");
const addSaving = ref(false);
const addError = ref("");
const add = reactive({
  provider: "",
  id: "",
  name: "",
  images: true,
  max_images: null,
  context_window: null,
  max_tokens: null,
});

const savedProviders = computed(() => (view.value?.providers || []).filter((p) => p.provider));
const addingProvider = computed(() => providerDrafts.value.some((p) => p._isNew));
const docsModels = computed(
  () => view.value?.docs?.models || "https://pi.dev/docs/latest/models",
);
const docsConfig = computed(
  () => view.value?.docs?.configuration || "https://pi.dev/docs/latest/models-configuration",
);
const canAddModel = computed(
  () => !!add.provider && !!String(add.id || "").trim() && savedProviders.value.some((p) => p.provider === add.provider),
);

function providerBaseUrl(name) {
  const draft = providerDrafts.value.find((p) => !p._isNew && p.provider === name);
  if (draft?.base_url) return draft.base_url;
  const saved = savedProviders.value.find((p) => p.provider === name);
  return saved?.base_url || "";
}

function providerKeyPlaceholder(p) {
  const info = p._keyInfo || {};
  return info.set ? t("secret.keepCurrent", { hint: info.hint || "" }) : t("llm.apiKeyPlaceholder");
}

function providerKeyHint(p) {
  const src = p._keyInfo?.source || "";
  if (src.startsWith("env:")) return t("llm.keyFromEnv", { name: src.slice(4) });
  if (src === "command") return t("llm.keyFromCommand");
  return t("llm.apiKeyHint");
}

function canSaveProvider(p) {
  return !!String(p.provider || "").trim() && !!String(p.base_url || "").trim();
}

function canSaveModel(m) {
  return !!m.provider && !!providerBaseUrl(m.provider) && !!String(m.id || "").trim();
}

function applyView(data) {
  view.value = data;
  const providers = data?.providers || [];
  providerDrafts.value = providers.map((p) => {
    const row = blankProvider({
      provider: p.provider,
      base_url: p.base_url || "",
      _isNew: false,
      _keyInfo: p.api_key || { set: false, hint: "", source: "none" },
    });
    markProviderClean(row);
    return row;
  });
  const rows = [];
  for (const p of providers) {
    for (const m of p.models || []) {
      const row = blankModel({
        provider: p.provider,
        id: m.id || "",
        name: m.name || "",
        images: m.images !== false,
        max_images: m.max_images ?? null,
        context_window: m.context_window ?? null,
        max_tokens: m.max_tokens ?? null,
      });
      markModelClean(row);
      rows.push(row);
    }
  }
  modelRows.value = rows;
  if (!add.provider && providers[0]) add.provider = providers[0].provider;
  if (add.provider && !providers.some((p) => p.provider === add.provider)) {
    add.provider = providers[0]?.provider || "";
  }
}

async function load() {
  try {
    applyView(await api.setupLlm());
  } catch (e) {
    loadError.value = e.message;
  }
}

function startAddProvider() {
  if (addingProvider.value) return;
  const row = blankProvider({
    _isNew: true,
    provider: providerDrafts.value.length ? "" : "autonomous",
  });
  // New card starts dirty only once id+url are filled.
  row._saved = providerFingerprint(row);
  providerDrafts.value = [...providerDrafts.value, row];
}

function cancelNewProvider(p) {
  providerDrafts.value = providerDrafts.value.filter((x) => x._key !== p._key);
}

function onAddProviderChange() {
  remoteModels.value = [];
  fetched.value = false;
  fetchError.value = "";
  add.id = "";
  addError.value = "";
}

async function saveProvider(p) {
  if (!isProviderDirty(p) || !canSaveProvider(p)) return;
  p._saving = true;
  p._error = "";
  p._ok = "";
  try {
    // Credentials only — no models key → server keeps existing models.
    const data = await api.saveSetupLlm({
      provider: String(p.provider || "").trim(),
      base_url: String(p.base_url || "").trim(),
      api_key: p.api_key,
    });
    applyView(data);
    refreshSetup(true);
    const saved = providerDrafts.value.find((x) => x.provider === String(p.provider || "").trim());
    if (saved) saved._ok = t("llm.saved");
  } catch (e) {
    p._error = e.message;
  } finally {
    p._saving = false;
  }
}

async function fetchModels() {
  if (!add.provider) return;
  fetching.value = true;
  fetched.value = false;
  fetchError.value = "";
  try {
    const draft = providerDrafts.value.find((p) => p.provider === add.provider);
    const r = await api.setupLlmModels({
      provider: add.provider,
      base_url: providerBaseUrl(add.provider),
      api_key: draft?.api_key || "",
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

async function saveNewModel() {
  if (!canAddModel.value) return;
  addSaving.value = true;
  addError.value = "";
  try {
    const data = await api.saveSetupLlm({
      provider: add.provider,
      base_url: providerBaseUrl(add.provider),
      model: String(add.id || "").trim(),
      model_name: String(add.name || "").trim(),
      images: !!add.images,
      max_images: normNum(add.max_images),
      context_window: normNum(add.context_window),
      max_tokens: normNum(add.max_tokens),
    });
    applyView(data);
    add.id = "";
    add.name = "";
    add.images = true;
    add.max_images = null;
    add.context_window = null;
    add.max_tokens = null;
    remoteModels.value = [];
    fetched.value = false;
    refreshSetup(true);
  } catch (e) {
    addError.value = e.message;
  } finally {
    addSaving.value = false;
  }
}

async function saveModel(m) {
  if (!isModelDirty(m) || !canSaveModel(m)) return;
  m._saving = true;
  m._error = "";
  try {
    const data = await api.saveSetupLlm({
      provider: m.provider,
      base_url: providerBaseUrl(m.provider),
      model: String(m.id || "").trim(),
      model_name: String(m.name || "").trim(),
      images: !!m.images,
      max_images: normNum(m.max_images),
      context_window: normNum(m.context_window),
      max_tokens: normNum(m.max_tokens),
    });
    applyView(data);
    refreshSetup(true);
  } catch (e) {
    m._error = e.message;
  } finally {
    m._saving = false;
  }
}

async function removeModel(idx) {
  const m = modelRows.value[idx];
  if (!m) return;
  const provider = m.provider;
  const id = String(m.id || "").trim();
  const base_url = providerBaseUrl(provider);
  const remaining = modelRows.value
    .filter((row, i) => i !== idx && row.provider === provider)
    .map((row) => ({
      id: String(row.id || "").trim(),
      name: String(row.name || "").trim(),
      images: !!row.images,
      max_images: normNum(row.max_images),
      context_window: normNum(row.context_window),
      max_tokens: normNum(row.max_tokens),
    }))
    .filter((row) => !!row.id);
  // Unsaved draft card — drop locally.
  if (!id || !base_url) {
    modelRows.value.splice(idx, 1);
    return;
  }
  try {
    const data = await api.saveSetupLlm({
      provider,
      base_url,
      models: remaining,
    });
    applyView(data);
    refreshSetup(true);
  } catch (e) {
    loadError.value = e.message;
  }
}

onMounted(load);
</script>
