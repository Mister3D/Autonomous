<template>
  <UiCard :title="t('groundingCfg.title')" :hint="t('groundingCfg.hint')">
    <template #icon>
      <UiIcon name="crosshair" :size="18" />
    </template>
    <p v-if="loadError" class="vault-error">{{ loadError }}</p>
    <UiToggleRow
      v-if="fields"
      v-model="form.enabled"
      :title="t('groundingCfg.enabled')"
      :hint="fields.enabled.readonly ? t('setup.fromEnv', { name: 'AUTONOMOUS_GROUNDING_ENABLED' }) : ''"
      :disabled="fields.enabled.readonly"
      :muted="fields.enabled.readonly"
    >
      <template #icon>
        <UiIcon name="crosshair" :size="16" />
      </template>
    </UiToggleRow>
  </UiCard>

  <template v-if="fields">
    <UiCard
      v-for="kind in kinds"
      :key="kind"
      :title="t(`groundingCfg.${kind}`)"
    >
      <template #icon>
        <UiIcon name="cpu" :size="18" />
      </template>
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
          <UiButton
            :ok="testOk(kind)"
            :disabled="testing"
            @click="test"
          >
            <template #icon>
              <UiIcon name="play" :size="14" />
            </template>
            {{ testing ? "…" : t("groundingCfg.test") }}
          </UiButton>
        </template>
      </SetupField>
      <p v-if="testError(kind)" class="hint vault-error">{{ testError(kind) }}</p>
    </UiCard>

    <UiCard :title="t('guard.limitsTitle')">
      <template #icon>
        <UiIcon name="update" :size="18" />
      </template>
      <label class="settings-field">
        <span>{{ t("guard.groundingLoops") }}</span>
        <input v-model.number="loops" type="number" min="1" max="8" step="1" />
      </label>
      <template #footer>
        <span v-if="saved" class="setup-ok">{{ t("llm.saved") }}</span>
        <span v-if="saveError" class="vault-error">{{ saveError }}</span>
        <UiButton variant="primary" :disabled="saving" @click="save">
          <template #icon>
            <UiIcon name="save" :size="16" />
          </template>
          {{ saving ? "…" : t("llm.save") }}
        </UiButton>
      </template>
    </UiCard>
  </template>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { refreshSetup } from "../store";
import SetupField from "./SetupField.vue";
import UiButton from "./ui/UiButton.vue";
import UiCard from "./ui/UiCard.vue";
import UiIcon from "./ui/UiIcon.vue";
import UiToggleRow from "./ui/UiToggleRow.vue";

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
