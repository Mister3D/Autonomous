<template>
  <button
    class="btn ui-btn"
    :class="[
      variantClass,
      {
        'is-ok': ok,
        'is-block': block,
        'is-icon-only': iconOnly,
      },
    ]"
    :type="type"
    :disabled="disabled"
  >
    <span v-if="$slots.icon" class="ui-btn-icon" aria-hidden="true">
      <slot name="icon" />
    </span>
    <span v-if="$slots.default" class="ui-btn-label"><slot /></span>
  </button>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  variant: {
    type: String,
    default: "secondary", // primary | secondary | success | danger | ghost | danger-ghost
  },
  type: { type: String, default: "button" },
  disabled: { type: Boolean, default: false },
  ok: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  iconOnly: { type: Boolean, default: false },
});

const variantClass = computed(() => {
  if (props.variant === "secondary") return "";
  if (props.variant === "success") return "is-ok";
  return props.variant;
});
</script>
