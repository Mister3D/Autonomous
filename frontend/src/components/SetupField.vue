<template>
  <label v-if="!isModel" class="settings-field">
    <span>{{ t(`groundingCfg.${id}`) }}</span>
    <SecretInput
      v-if="secret"
      :model-value="modelValue"
      :disabled="field.readonly"
      :placeholder="field.set ? t('secret.keepCurrent', { hint: field.hint || '' }) : ''"
      autocomplete="new-password"
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <input
      v-else
      :value="modelValue"
      :disabled="field.readonly"
      type="text"
      spellcheck="false"
      @input="$emit('update:modelValue', $event.target.value)"
    />
    <small v-if="field.readonly">{{ t("setup.fromEnv", { name: field.env }) }}</small>
    <small v-else-if="field.source === 'fallback'">{{ t("groundingCfg.fallback") }}</small>
  </label>
  <div v-else class="settings-field">
    <span>{{ t(`groundingCfg.${id}`) }}</span>
    <div class="settings-field-row">
      <ModelCombo
        :model-value="modelValue"
        :options="options"
        :disabled="field.readonly"
        :placeholder="t('llm.modelPlaceholder')"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <button class="btn" type="button" :disabled="fetching || field.readonly" @click="$emit('fetch')">
        {{ fetching ? t("llm.fetching") : t("llm.fetchModels") }}
      </button>
    </div>
    <small v-if="field.readonly">{{ t("setup.fromEnv", { name: field.env }) }}</small>
    <small v-else-if="fetchError" class="vault-error">{{ fetchError }}</small>
    <small v-else-if="fetched">{{ t("llm.modelsFound", { count: options.length }) }}</small>
    <small v-else-if="field.source === 'fallback'">{{ t("groundingCfg.fallback") }}</small>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import ModelCombo from "./ModelCombo.vue";
import SecretInput from "./SecretInput.vue";

const props = defineProps({
  id: { type: String, required: true },
  field: { type: Object, required: true },
  modelValue: { type: String, default: "" },
  options: { type: Array, default: () => [] },
  fetching: { type: Boolean, default: false },
  fetched: { type: Boolean, default: false },
  fetchError: { type: String, default: "" },
});
defineEmits(["update:modelValue", "fetch"]);
const { t } = useI18n();
const secret = computed(() => props.id.endsWith("_token"));
const isModel = computed(() => props.id.endsWith("_model"));
</script>
