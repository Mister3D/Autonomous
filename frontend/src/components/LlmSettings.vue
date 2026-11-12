<template>
  <div class="llm-settings">
  <UiCard :title="t('llm.defaultModelTitle')" :hint="t('llm.defaultModelHint')">
    <template #icon>
      <UiIcon name="spark" :size="18" />
    </template>
    <p v-if="loadError" class="vault-error">{{ loadError }}</p>
    <div class="llm-default-model">
      <ModelPicker field :model="defaultModel" @update:model="onDefaultModel" />
      <span v-if="defaultModelSaving" class="hint">…</span>
      <span v-else-if="defaultModelOk" class="setup-ok">{{ defaultModelOk }}</span>
      <span v-else-if="defaultModelError" class="vault-error">{{ defaultModelError }}</span>
    </div>
  </UiCard>

  <UiCard :title="t('llm.providersTitle')" :hint="t('llm.providersHint')">
    <template #icon>
      <UiIcon name="link" :size="18" />
    </template>
    <p class="hint">
      {{ t("llm.docsLead") }}
      <a :href="docsModels" target="_blank" rel="noopener noreferrer">{{ t("llm.docsModels") }}</a>
      ·
      <a :href="docsProviders" target="_blank" rel="noopener noreferrer">{{ t("llm.docsProviders") }}</a>
      ·
      <a :href="docsConfig" target="_blank" rel="noopener noreferrer">{{ t("llm.docsConfig") }}</a>
    </p>

    <ul v-if="providerDrafts.length" class="llm-provider-list">
      <li
        v-for="p in providerDrafts"
        :key="p._key"
        class="llm-provider-card"
        :class="{ 'is-collapsed': !p._open }"
      >
        <span
          class="llm-trash-wrap"
          @pointerenter="p._tip = true"
          @pointerleave="p._tip = false"
          @focusin="p._tip = true"
          @focusout="p._tip = false"
        >
          <button
            class="vault-trash"
            type="button"
            :disabled="providerInUse(p) || p._saving"
            :aria-label="providerTip(p)"
            @click.stop="removeProvider(p)"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path d="M5 7.5h14" />
              <path d="M9.5 7.5V5.8A1.3 1.3 0 0 1 10.8 4.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
              <path d="M8 7.5l.7 11a1.4 1.4 0 0 0 1.4 1.3h4.8a1.4 1.4 0 0 0 1.4-1.3l.7-11" />
            </svg>
          </button>
          <span v-if="p._tip" class="llm-provider-tip" role="tooltip">{{ providerTip(p) }}</span>
        </span>
        <button
          class="llm-provider-toggle"
          type="button"
          :aria-expanded="p._open ? 'true' : 'false'"
          :aria-label="t('llm.toggleProvider', { name: providerLabel(p) })"
          @click="p._open = !p._open"
        >
          <svg
            class="llm-provider-caret"
            :class="{ open: p._open }"
            viewBox="0 0 12 12"
            width="12"
            height="12"
            aria-hidden="true"
          >
            <path
              d="M2.5 4.2 6 7.8 9.5 4.2"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <strong>{{ providerLabel(p) }}</strong>
        </button>
        <div v-show="p._open" class="llm-provider-body">
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
        </div>
      </li>
    </ul>
    <p v-else class="hint">{{ t("llm.providersEmpty") }}</p>
    <div class="setup-toolbar">
      <button class="btn" type="button" :disabled="addingProvider" @click="startAddProvider">
        {{ t("llm.addProvider") }}
      </button>
    </div>
  </UiCard>

  <UiCard :title="t('llm.modelsTitle')">
    <template #icon>
      <UiIcon name="cpu" :size="18" />
    </template>

    <ul v-if="modelRows.length" class="llm-provider-list">
      <li
        v-for="m in modelRows"
        :key="m._key"
        class="llm-provider-card"
        :class="{ 'is-collapsed': !m._open }"
      >
        <span
          class="llm-trash-wrap"
          @pointerenter="m._tip = true"
          @pointerleave="m._tip = false"
          @focusin="m._tip = true"
          @focusout="m._tip = false"
        >
          <button
            class="vault-trash"
            type="button"
            :disabled="m._saving"
            :aria-label="t('llm.deleteModel')"
            @click.stop="removeModel(m)"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
              <path d="M5 7.5h14" />
              <path d="M9.5 7.5V5.8A1.3 1.3 0 0 1 10.8 4.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7" />
              <path d="M8 7.5l.7 11a1.4 1.4 0 0 0 1.4 1.3h4.8a1.4 1.4 0 0 0 1.4-1.3l.7-11" />
            </svg>
          </button>
          <span v-if="m._tip" class="llm-provider-tip" role="tooltip">{{ t("llm.deleteModel") }}</span>
        </span>
        <button
          class="llm-provider-toggle"
          type="button"
          :aria-expanded="m._open ? 'true' : 'false'"
          :aria-label="t('llm.toggleModel', { name: modelLabel(m) })"
          @click="toggleModel(m)"
        >
          <svg
            class="llm-provider-caret"
            :class="{ open: m._open }"
            viewBox="0 0 12 12"
            width="12"
            height="12"
            aria-hidden="true"
          >
            <path
              d="M2.5 4.2 6 7.8 9.5 4.2"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <strong>{{ modelLabel(m) }}</strong>
        </button>
        <div v-show="m._open" class="llm-provider-body">
          <label class="settings-field">
            <span>{{ t("llm.modelName") }}</span>
            <input v-model.trim="m.name" type="text" :placeholder="t('llm.modelNamePlaceholder')" />
            <small>{{ t("llm.modelNameHint") }}</small>
          </label>
          <label class="settings-field">
            <span>{{ t("llm.provider") }}</span>
            <MenuSelect
              :model-value="m.provider"
              :options="providerOptions"
              :placeholder="t('llm.pickProvider')"
              :aria-label="t('llm.provider')"
              :disabled="!savedProviders.length"
              field
              @update:model-value="(v) => onModelProvider(m, v)"
            />
          </label>
          <small v-if="m._fetchError" class="vault-error">{{ m._fetchError }}</small>
          <small v-else-if="m._fetched && !m._fetching">{{ t("llm.modelsFound", { count: m._remote.length }) }}</small>
          <label class="settings-field">
            <span>{{ t("llm.model") }}</span>
            <MenuSelect
              v-model="m.id"
              :options="m._remote"
              :placeholder="modelPlaceholder(m)"
              :aria-label="t('llm.model')"
              :disabled="!m.provider || m._fetching"
              field
            />
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
          <div class="setup-toolbar">
            <button
              class="btn primary"
              type="button"
              :disabled="!isModelDirty(m) || m._saving || !canSaveModel(m)"
              @click="saveModel(m)"
            >
              {{ m._saving ? "…" : t("llm.saveModel") }}
            </button>
            <span v-if="m._ok" class="setup-ok">{{ m._ok }}</span>
            <span v-if="m._error" class="vault-error">{{ m._error }}</span>
          </div>
        </div>
      </li>
    </ul>
    <p v-else class="hint">{{ t("llm.modelsEmpty") }}</p>
    <div class="setup-toolbar">
      <button class="btn" type="button" :disabled="addingModel || !savedProviders.length" @click="startAddModel">
        {{ t("llm.addModel") }}
      </button>
    </div>
  </UiCard>

  <UiCard :title="t('llm.otherTitle')" :hint="t('llm.otherHint')">
    <template #icon>
      <UiIcon name="database" :size="18" />
    </template>
    <div v-if="catalogModels.length" class="llm-catalog">
      <div class="llm-catalog-head" role="row">
        <span role="columnheader">{{ t("llm.model") }}</span>
        <span role="columnheader">{{ t("llm.otherContext") }}</span>
        <span role="columnheader">{{ t("llm.otherOutput") }}</span>
        <span role="columnheader">{{ t("llm.otherThinking") }}</span>
        <span role="columnheader">{{ t("llm.otherImages") }}</span>
      </div>
      <div class="llm-catalog-body">
        <div v-for="m in catalogModels" :key="m.ref" class="llm-catalog-row" role="row">
          <span class="llm-catalog-id" role="cell">{{ m.provider }} · {{ m.id }}</span>
          <span role="cell">{{ m.context || "—" }}</span>
          <span role="cell">{{ m.max_output || "—" }}</span>
          <span role="cell">{{ m.thinking ? t("llm.yes") : t("llm.no") }}</span>
          <span role="cell">{{ m.images ? t("llm.yes") : t("llm.no") }}</span>
        </div>
      </div>
    </div>
    <p v-else class="hint">{{ t("llm.otherEmpty") }}</p>
  </UiCard>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { refreshSetup } from "../store";
import MenuSelect from "./MenuSelect.vue";
import ModelPicker from "./ModelPicker.vue";
import SecretInput from "./SecretInput.vue";
import UiCard from "./ui/UiCard.vue";
import UiIcon from "./ui/UiIcon.vue";

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
    _isNew: false,
    _open: false,
    _originProvider: "",
    _originId: "",
    _remote: [],
    _fetching: false,
    _fetched: false,
    _fetchError: "",
    _saving: false,
    _error: "",
    _ok: "",
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
    _open: false,
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
const catalogModels = ref([]);
const defaultModel = ref("");
const defaultModelSaving = ref(false);
const defaultModelOk = ref("");
const defaultModelError = ref("");
let defaultModelTimer = 0;

const savedProviders = computed(() => (view.value?.providers || []).filter((p) => p.provider));
const providerOptions = computed(() =>
  savedProviders.value.map((p) => ({ value: p.provider, label: p.provider })),
);
const addingProvider = computed(() => providerDrafts.value.some((p) => p._isNew));
const addingModel = computed(() => modelRows.value.some((m) => m._isNew));
const docsModels = computed(
  () => view.value?.docs?.models || "https://pi.dev/docs/latest/models",
);
const docsConfig = computed(
  () => view.value?.docs?.configuration || "https://pi.dev/docs/latest/models-configuration",
);
const docsProviders = computed(
  () => view.value?.docs?.providers || "https://pi.dev/docs/latest/providers",
);
function modelPlaceholder(m) {
  return m?._fetching ? t("llm.fetching") : t("llm.modelPlaceholder");
}

function modelLabel(m) {
  const name = String(m?.name || "").trim();
  return name || t("llm.newModel");
}

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

function providerInUse(p) {
  if (!p || p._isNew) return false;
  const name = String(p.provider || "").trim();
  if (!name) return false;
  return modelRows.value.some((m) => m.provider === name && String(m.id || "").trim());
}

function providerTip(p) {
  return providerInUse(p) ? t("llm.providerInUse") : t("llm.deleteProvider");
}

function providerLabel(p) {
  const name = String(p?.provider || "").trim();
  return name || t("llm.newProviderCard");
}

async function removeProvider(p) {
  if (!p || providerInUse(p) || p._saving) return;
  if (p._isNew) {
    cancelNewProvider(p);
    return;
  }
  const name = String(p.provider || "").trim();
  if (!name) return;
  p._saving = true;
  p._error = "";
  try {
    applyView(await api.deleteSetupLlm(name));
    refreshSetup(true);
  } catch (e) {
    p._error = e.message;
    p._saving = false;
  }
}

function canSaveModel(m) {
  return !!m.provider && !!providerBaseUrl(m.provider) && !!String(m.id || "").trim();
}

function applyView(data) {
  view.value = data;
  const providers = data?.providers || [];
  const keepOpen = new Set(
    providerDrafts.value.filter((p) => p._open && p.provider).map((p) => p.provider),
  );
  providerDrafts.value = providers.map((p) => {
    const row = blankProvider({
      provider: p.provider,
      base_url: p.base_url || "",
      _isNew: false,
      _open: keepOpen.has(p.provider),
      _keyInfo: p.api_key || { set: false, hint: "", source: "none" },
    });
    markProviderClean(row);
    return row;
  });
  const keepModelOpen = new Set(
    modelRows.value
      .filter((m) => m._open && m.provider && m.id)
      .map((m) => `${m.provider}\n${m.id}`),
  );
  const pendingModels = modelRows.value.filter((m) => m._isNew);
  const rows = [];
  for (const p of providers) {
    for (const m of p.models || []) {
      const id = m.id || "";
      const row = blankModel({
        provider: p.provider,
        id,
        name: m.name || "",
        images: m.images !== false,
        max_images: m.max_images ?? null,
        context_window: m.context_window ?? null,
        max_tokens: m.max_tokens ?? null,
        _originProvider: p.provider,
        _originId: id,
        _open: keepModelOpen.has(`${p.provider}\n${id}`),
      });
      markModelClean(row);
      rows.push(row);
    }
  }
  modelRows.value = [...rows, ...pendingModels];
  catalogModels.value = (data?.catalog || [])
    .filter((m) => m?.provider && m?.id)
    .slice()
    .sort((a, b) =>
      `${a.provider} · ${a.id}`.localeCompare(`${b.provider} · ${b.id}`, undefined, { sensitivity: "base" }),
    );
}

async function load() {
  try {
    applyView(await api.setupLlm());
  } catch (e) {
    loadError.value = e.message;
  }
  try {
    const settings = await api.settings();
    defaultModel.value = String(settings?.["bots.default_model"] || "").trim();
  } catch {
    /* optional — picker still works */
  }
}

async function onDefaultModel(next) {
  const model = String(next || "").trim();
  if (!model || model === defaultModel.value) return;
  defaultModel.value = model;
  defaultModelSaving.value = true;
  defaultModelOk.value = "";
  defaultModelError.value = "";
  try {
    await api.putSettings({ "bots.default_model": model });
    defaultModelOk.value = t("llm.saved");
    clearTimeout(defaultModelTimer);
    defaultModelTimer = window.setTimeout(() => {
      defaultModelOk.value = "";
    }, 1800);
  } catch (e) {
    defaultModelError.value = e.message || String(e);
  } finally {
    defaultModelSaving.value = false;
  }
}

function startAddProvider() {
  if (addingProvider.value) return;
  const row = blankProvider({
    _isNew: true,
    _open: true,
    provider: providerDrafts.value.length ? "" : "autonomous",
  });
  // New card starts dirty only once id+url are filled.
  row._saved = providerFingerprint(row);
  providerDrafts.value = [...providerDrafts.value, row];
}

function cancelNewProvider(p) {
  providerDrafts.value = providerDrafts.value.filter((x) => x._key !== p._key);
}

function startAddModel() {
  if (addingModel.value || !savedProviders.value.length) return;
  const row = blankModel({ _isNew: true, _open: true, provider: "" });
  row._saved = modelFingerprint(row);
  modelRows.value = [...modelRows.value, row];
}

function toggleModel(m) {
  m._open = !m._open;
  if (m._open && m.provider && !m._fetched && !m._fetching) fetchModels(m);
}

function onModelProvider(m, name) {
  if (name === m.provider) return;
  m.provider = name || "";
  m.id = "";
  m._remote = [];
  m._fetched = false;
  m._fetchError = "";
  if (m.provider) fetchModels(m);
}

let fetchGen = 0;

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

async function fetchModels(m) {
  const name = m.provider;
  if (!name) return;
  const gen = ++fetchGen;
  m._fetchGen = gen;
  m._fetching = true;
  m._fetched = false;
  m._fetchError = "";
  try {
    const draft = providerDrafts.value.find((p) => p.provider === name);
    const r = await api.setupLlmModels({
      provider: name,
      base_url: providerBaseUrl(name),
      api_key: draft?.api_key || "",
    });
    if (m._fetchGen !== gen) return;
    m._remote = r.models || [];
    m._fetched = true;
  } catch (e) {
    if (m._fetchGen !== gen) return;
    m._remote = [];
    m._fetchError = e.message;
  } finally {
    if (m._fetchGen === gen) m._fetching = false;
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
    m._isNew = false;
    applyView(data);
    refreshSetup(true);
    const saved = modelRows.value.find(
      (row) => row.provider === String(m.provider || "").trim() && row.id === String(m.id || "").trim(),
    );
    if (saved) saved._ok = t("llm.saved");
  } catch (e) {
    m._error = e.message;
  } finally {
    m._saving = false;
  }
}

async function removeModel(m) {
  if (!m || m._saving) return;
  if (m._isNew) {
    modelRows.value = modelRows.value.filter((row) => row._key !== m._key);
    return;
  }
  const provider = m._originProvider || m.provider;
  const id = String(m._originId || m.id || "").trim();
  const base_url = providerBaseUrl(provider);
  if (!id || !base_url) {
    modelRows.value = modelRows.value.filter((row) => row._key !== m._key);
    return;
  }
  const remaining = modelRows.value
    .filter((row) => row !== m && !row._isNew && (row._originProvider || row.provider) === provider)
    .map((row) => ({
      id: String(row.id || "").trim(),
      name: String(row.name || "").trim(),
      images: !!row.images,
      max_images: normNum(row.max_images),
      context_window: normNum(row.context_window),
      max_tokens: normNum(row.max_tokens),
    }))
    .filter((row) => !!row.id);
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
