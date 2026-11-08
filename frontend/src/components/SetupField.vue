<template>
  <label v-if="!isModel" class="settings-field">
    <span>{{ t(`groundingCfg.${id}`) }}</span>
    <div v-if="secret" class="settings-field-row">
      <SecretInput
        :model-value="modelValue"
        :disabled="field.readonly"
        :placeholder="field.set ? t('secret.keepCurrent', { hint: field.hint || '' }) : ''"
        autocomplete="new-password"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <button class="btn" type="button" :disabled="fetching || field.readonly" @click="$emit('fetch')">
        {{ fetching ? t("llm.fetching") : t("llm.fetchModels") }}
      </button>
    </div>
    <input
      v-else
      :value="modelValue"
      :disabled="field.readonly"
      type="text"
      spellcheck="false"
      @input="$emit('update:modelValue', $event.target.value)"
    />
    <small v-if="field.readonly">{{ t("setup.fromEnv", { name: field.env }) }}</small>
    <small v-else-if="secret && fetchError" class="vault-error">{{ fetchError }}</small>
    <small v-else-if="secret && fetched">{{ t("llm.modelsFound", { count: options.length }) }}</small>
    <small v-else-if="field.source === 'fallback'">{{ t("groundingCfg.fallback") }}</small>
  </label>
  <div v-else class="settings-field">
    <span>{{ t(`groundingCfg.${id}`) }}</span>
    <div class="settings-field-row">
      <MenuSelect
        :model-value="modelValue"
        :options="options"
        :disabled="field.readonly"
        :placeholder="t('groundingCfg.modelPlaceholder')"
        :aria-label="t(`groundingCfg.${id}`)"
        field
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <slot name="aside" />
    </div>
    <small v-if="field.readonly">{{ t("setup.fromEnv", { name: field.env }) }}</small>
    <small v-else-if="field.source === 'fallback'">{{ t("groundingCfg.fallback") }}</small>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import MenuSelect from "./MenuSelect.vue";
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
