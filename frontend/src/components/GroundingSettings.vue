<template>
  <section class="settings-block">
    <h3>{{ t("groundingCfg.title") }}</h3>
    <p class="hint">{{ t("groundingCfg.hint") }}</p>
    <p v-if="loadError" class="vault-error">{{ loadError }}</p>
    <label v-if="fields" class="toggle-row" :class="{ muted: fields.enabled.readonly }">
      <span>
        <strong>{{ t("groundingCfg.enabled") }}</strong>
        <small v-if="fields.enabled.readonly">{{ t("setup.fromEnv", { name: "AUTONOMOUS_GROUNDING_ENABLED" }) }}</small>
      </span>
      <input
        v-model="form.enabled"
        type="checkbox"
        role="switch"
        :disabled="fields.enabled.readonly"
        :aria-label="t('groundingCfg.enabled')"
      />
    </label>
  </section>

  <template v-if="fields">
  <section v-for="kind in kinds" :key="kind" class="settings-block">
    <h3>{{ t(`groundingCfg.${kind}`) }}</h3>
    <SetupField
      v-for="f in ['url', 'token', 'model']"
      :key="f"
      :id="`${kind}_${f}`"
      :field="fields[`${kind}_${f}`]"
      v-model="form[`${kind}_${f}`]"
      :options="modelOptions(kind)"
      :fetching="models[kind].loading"
      :fetched="models[kind].done"
      :fetch-error="models[kind].error"
      @fetch="fetchModels(kind)"
    >
      <template v-if="f === 'model'" #aside>
        <button
          class="btn"
          :class="{ 'is-ok': testOk(kind) }"
          type="button"
          :disabled="testing"
          @click="test"
        >
          {{ testing ? "…" : t("groundingCfg.test") }}
        </button>
      </template>
    </SetupField>
    <p v-if="testError(kind)" class="hint vault-error">{{ testError(kind) }}</p>
  </section>

  <section class="settings-block">
    <h3>{{ t("guard.limitsTitle") }}</h3>
    <label class="settings-field">
      <span>{{ t("guard.groundingLoops") }}</span>
      <input v-model.number="loops" type="number" min="1" max="8" step="1" />
    </label>
  </section>
  <div class="settings-save-bar">
    <span v-if="saved" class="setup-ok">{{ t("llm.saved") }}</span>
    <span v-if="saveError" class="vault-error">{{ saveError }}</span>
    <button class="btn primary" type="button" :disabled="saving" @click="save">{{ saving ? "…" : t("llm.save") }}</button>
  </div>
  </template>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { refreshSetup } from "../store";
import SetupField from "./SetupField.vue";

const { t } = useI18n();
const kinds = ["grounder"];
const allFields = kinds.flatMap((k) => [`${k}_url`, `${k}_model`, `${k}_token`]);
const fields = ref(null);
const form = reactive({});
const models = reactive({
  grounder: { list: [], loading: false, done: false, error: "" },
});
const loadError = ref("");
const testing = ref(false);
const tested = ref(null);
const saving = ref(false);
const saved = ref(false);
const saveError = ref("");
const loops = ref(2);

function apply(view) {
  fields.value = view.fields;
  form.enabled = !!view.fields.enabled.value;
  for (const f of allFields) {
    form[f] = f.endsWith("_token") ? "" : view.fields[f].value || "";
  }
}

function modelOptions(kind) {
  const list = models[kind].list || [];
  const current = form[`${kind}_model`];
  if (current && !list.includes(current)) return [current, ...list];
  return list;
}

function payload() {
  const body = {};
  if (!fields.value.enabled.readonly) body.enabled = form.enabled;
  for (const f of allFields) {
    if (!fields.value[f].readonly) body[f] = form[f];
  }
  return body;
}

async function fetchModels(kind) {
  const m = models[kind];
  m.loading = true;
  m.done = false;
  m.error = "";
  try {
    const r = await api.setupGroundingModels({ kind, url: form[`${kind}_url`], token: form[`${kind}_token`] });
    m.list = r.models || [];
    m.done = true;
  } catch (e) {
    m.list = [];
    m.error = e.message;
  } finally {
    m.loading = false;
  }
}

function testOk(kind) {
  const sig = tested.value;
  return !!(
    sig &&
    sig.kind === kind &&
    sig.ok &&
    form[`${kind}_url`] === sig.url &&
    form[`${kind}_token`] === sig.token
  );
}

function testError(kind) {
  const sig = tested.value;
  if (!sig || sig.kind !== kind || sig.ok) return "";
  if (form[`${kind}_url`] !== sig.url || form[`${kind}_token`] !== sig.token) return "";
  return sig.error || "";
}

async function test() {
  testing.value = true;
  const kind = "grounder";
  const url = form[`${kind}_url`];
  const token = form[`${kind}_token`];
  try {
    const row = (await api.testSetupGrounding(payload()))?.[kind];
    tested.value = { kind, url, token, ok: !!row?.ok, error: row?.ok ? "" : row?.error || "" };
  } catch (e) {
    tested.value = { kind, url, token, ok: false, error: e.message };
  } finally {
    testing.value = false;
  }
}

async function save() {
  saving.value = true;
  saved.value = false;
  saveError.value = "";
  try {
    apply(await api.saveSetupGrounding(payload()));
    const n = Math.max(1, Math.min(8, Math.round(Number(loops.value) || 1)));
    loops.value = n;
    await api.putSettings({ "grounding.max_loops": n });
    saved.value = true;
    refreshSetup(true);
  } catch (e) {
    saveError.value = e.message;
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  try {
    apply(await api.setupGrounding());
    const settings = await api.settings();
    if (settings["grounding.max_loops"] != null) loops.value = Number(settings["grounding.max_loops"]);
  } catch (e) {
    loadError.value = e.message;
  }
});
</script>
