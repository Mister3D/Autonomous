<template>
  <label
    class="toggle-row ui-toggle-row"
    :class="{ muted, 'has-icon': !!$slots.icon }"
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
    <span
      class="ui-toggle-switch"
      @pointerenter="showTip"
      @pointerleave="hideTip"
      @focusin="showTip"
      @focusout="hideTip"
    >
      <input
        type="checkbox"
        role="switch"
        :checked="modelValue"
        :disabled="disabled"
        :aria-label="ariaLabel || title"
        :aria-description="tipText || undefined"
        @change="onChange"
      />
      <span
        v-if="tipOpen && tipText"
        ref="tipEl"
        class="ui-toggle-tip"
        :class="{ 'is-below': tipBelow }"
        :style="tipShift ? { transform: `translateX(${tipShift}px)` } : undefined"
        role="tooltip"
      >{{ tipText }}</span>
    </span>
  </label>
</template>

<script setup>
import { computed, nextTick, ref } from "vue";
import UiIconBadge from "./UiIconBadge.vue";

const props = defineProps({
  title: { type: String, required: true },
  hint: { type: String, default: "" },
  /** Custom hover tip on the switch (same family as bot-avatar-tip). */
  tip: { type: String, default: "" },
  modelValue: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  muted: { type: Boolean, default: false },
  /** Prefer this tip text while the switch is disabled. */
  disabledReason: { type: String, default: "" },
  ariaLabel: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue", "change"]);
const tipOpen = ref(false);
const tipEl = ref(null);
const tipShift = ref(0);
const tipBelow = ref(false);
const tipText = computed(() => {
  if (props.disabled && props.disabledReason) return props.disabledReason;
  return props.tip || "";
});

function clampTip() {
  const el = tipEl.value;
  if (!el) return;
  const pad = 8;
  const r = el.getBoundingClientRect();
  let dx = 0;
  if (r.left < pad) dx = pad - r.left;
  else if (r.right > window.innerWidth - pad) dx = window.innerWidth - pad - r.right;
  tipShift.value = dx;
  if (!tipBelow.value && r.top < pad) {
    tipBelow.value = true;
    tipShift.value = 0;
    nextTick(clampTip);
  }
}

async function showTip() {
  if (!tipText.value) return;
  tipOpen.value = true;
  tipShift.value = 0;
  tipBelow.value = false;
  await nextTick();
  clampTip();
}

function hideTip() {
  tipOpen.value = false;
  tipShift.value = 0;
  tipBelow.value = false;
}

function onChange(ev) {
  emit("update:modelValue", !!ev.target.checked);
  emit("change", ev);
}
</script>
