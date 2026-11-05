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
      :options="models[kind].list"
      :fetching="models[kind].loading"
      :fetched="models[kind].done"
      :fetch-error="models[kind].error"
      @fetch="fetchModels(kind)"
    />
    <p v-if="testResult && testResult[kind]" class="hint" :class="testResult[kind].ok ? 'ok' : 'vault-error'">
      {{ testResult[kind].ok ? t("groundingCfg.reachable") : testResult[kind].error }}
    </p>
  </section>

  <section class="settings-block">
    <div class="setup-toolbar">
      <button class="btn" type="button" :disabled="testing" @click="test">{{ testing ? "…" : t("groundingCfg.test") }}</button>
      <button class="btn primary" type="button" :disabled="saving" @click="save">{{ saving ? "…" : t("llm.save") }}</button>
      <span v-if="saved" class="setup-ok">{{ t("llm.saved") }}</span>
      <span v-if="saveError" class="vault-error">{{ saveError }}</span>
    </div>
    <p class="hint">{{ t("groundingCfg.fileNote") }}</p>
  </section>
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
const testResult = ref(null);
const saving = ref(false);
const saved = ref(false);
const saveError = ref("");

function apply(view) {
  fields.value = view.fields;
  form.enabled = !!view.fields.enabled.value;
  for (const f of allFields) {
    form[f] = f.endsWith("_token") ? "" : view.fields[f].value || "";
  }
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

async function test() {
  testing.value = true;
  try {
    testResult.value = await api.testSetupGrounding(payload());
  } catch (e) {
    testResult.value = { grounder: { ok: false, error: e.message } };
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
  } catch (e) {
    loadError.value = e.message;
  }
});
</script>
