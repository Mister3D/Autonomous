<template>
  <span
    class="action-confirm-wrap"
    @pointerenter="tipOpen = true"
    @pointerleave="tipOpen = false"
    @focusin="tipOpen = true"
    @focusout="tipOpen = false"
  >
    <button
      class="action-confirm"
      :class="buttonClass"
      type="button"
      :disabled="disabled"
      :aria-label="label"
      @click="$emit('confirm')"
    >
      <UiIcon name="check" :size="14" />
    </button>
    <span v-if="tipOpen" class="action-confirm-tip" role="tooltip">{{ label }}</span>
  </span>
</template>

<script setup>
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import UiIcon from "./UiIcon.vue";

defineProps({
  disabled: { type: Boolean, default: false },
  /** Extra classes on the check button (e.g. file-icon-btn). */
  buttonClass: { type: [String, Object, Array], default: "" },
});

defineEmits(["confirm"]);

const { t } = useI18n();
const tipOpen = ref(false);
const label = t("confirm.confirmAction");
</script>
