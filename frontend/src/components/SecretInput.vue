<template>
  <div class="secret-input">
    <input
      :id="id"
      :value="modelValue"
      :type="revealed ? 'text' : 'password'"
      :autocomplete="autocomplete"
      :required="required"
      :disabled="disabled"
      :placeholder="placeholder"
      @input="$emit('update:modelValue', $event.target.value)"
    />
    <button
      class="secret-toggle"
      type="button"
      :aria-label="revealed ? t('vault.hideValue') : t('vault.showValue')"
      :aria-pressed="revealed"
      :disabled="disabled"
      @click="revealed = !revealed"
    >
      <!-- eye open -->
      <svg v-if="!revealed" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
        <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="12" cy="12" r="3" />
      </svg>
      <!-- eye off -->
      <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
        <path d="M3 3l18 18" stroke-linecap="round" />
        <path d="M10.6 10.6a3 3 0 0 0 4.2 4.2" stroke-linecap="round" />
        <path d="M9.4 5.7A9.5 9.5 0 0 1 12 5.5C18 5.5 21.5 12 21.5 12a17 17 0 0 1-3.1 4.1" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M6.2 6.2C4.1 7.7 2.5 12 2.5 12a17.4 17.4 0 0 0 7.2 6.3" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { useI18n } from "vue-i18n";

defineProps({
  modelValue: { type: String, default: "" },
  id: { type: String, default: undefined },
  autocomplete: { type: String, default: "off" },
  required: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: "" },
});

defineEmits(["update:modelValue"]);

const { t } = useI18n();
const revealed = ref(false);
</script>
