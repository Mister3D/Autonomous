<template>
  <label class="ui-switch" :class="{ 'is-compact': compact, muted }">
    <input
      type="checkbox"
      role="switch"
      :checked="modelValue"
      :disabled="disabled"
      :aria-label="ariaLabel"
      @change="onChange"
    />
  </label>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
  muted: { type: Boolean, default: false },
  ariaLabel: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue", "change"]);

function onChange(ev) {
  emit("update:modelValue", !!ev.target.checked);
  emit("change", ev);
}
</script>
