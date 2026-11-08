<template>
  <label
    class="toggle-row ui-toggle-row"
    :class="{ muted, 'has-icon': !!$slots.icon }"
    :title="disabled && disabledReason ? disabledReason : undefined"
  >
    <span class="ui-toggle-main">
      <UiIconBadge v-if="$slots.icon" size="sm">
        <slot name="icon" />
      </UiIconBadge>
      <span class="ui-toggle-copy">
        <strong>{{ title }}</strong>
        <small v-if="hint || $slots.hint">
          <slot name="hint">{{ hint }}</slot>
        </small>
      </span>
    </span>
    <input
      type="checkbox"
      role="switch"
      :checked="modelValue"
      :disabled="disabled"
      :aria-label="ariaLabel || title"
      :aria-description="disabled && disabledReason ? disabledReason : undefined"
      @change="onChange"
    />
  </label>
</template>

<script setup>
import UiIconBadge from "./UiIconBadge.vue";

defineProps({
  title: { type: String, required: true },
  hint: { type: String, default: "" },
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  muted: { type: Boolean, default: false },
  /** Shown as hover tooltip when the switch is disabled. */
  disabledReason: { type: String, default: "" },
  ariaLabel: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue", "change"]);

function onChange(ev) {
  emit("update:modelValue", !!ev.target.checked);
  emit("change", ev);
}
</script>
