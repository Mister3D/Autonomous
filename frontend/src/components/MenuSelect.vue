<template>
  <div class="model-picker" :class="{ open, 'is-field': field }" ref="root">
    <button
      class="model-trigger"
      type="button"
      :aria-label="ariaLabel || currentLabel"
      :aria-expanded="open"
      aria-haspopup="listbox"
      :disabled="disabled"
      @click="toggle"
    >
      <span class="model-trigger-copy">
        <span class="model-trigger-label">{{ currentLabel }}</span>
        <span v-if="currentMeta" class="model-trigger-meta">{{ currentMeta }}</span>
      </span>
      <svg class="model-caret" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
        <path
          d="M2.5 4.2 6 7.8 9.5 4.2"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>
    <ul v-if="open" class="model-menu" role="listbox">
      <li v-for="row in rows" :key="row.value || '__empty'">
        <button
          type="button"
          role="option"
          :aria-selected="row.value === modelValue"
          :class="{ active: row.value === modelValue }"
          @click="choose(row.value)"
        >
          <span class="model-option-copy">
            <span class="model-option-label">{{ row.label }}</span>
            <span v-if="row.meta" class="model-option-meta">{{ row.meta }}</span>
          </span>
          <svg
            v-if="row.value === modelValue && row.value !== ''"
            class="model-check"
            viewBox="0 0 16 16"
            width="14"
            height="14"
            aria-hidden="true"
          >
            <path
              d="M3.2 8.2 6.4 11.4 12.8 4.6"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
  /** { value, label, meta? } or a plain string. */
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "" },
  ariaLabel: { type: String, default: "" },
  disabled: { type: Boolean, default: false },
  /** First row clears the value (inspector model picker). */
  allowEmpty: { type: Boolean, default: false },
  /** Drop the inspector top margin when the control sits under a field label. */
  field: { type: Boolean, default: false },
});
const emit = defineEmits(["update:modelValue"]);

const open = ref(false);
const root = ref(null);

const rows = computed(() => {
  const list = props.options.map((option) => {
    if (typeof option === "string") return { value: option, label: option, meta: "" };
    return {
      value: String(option?.value ?? ""),
      label: option?.label || String(option?.value ?? ""),
      meta: option?.meta || "",
    };
  });
  if (!props.allowEmpty) return list;
  return [{ value: "", label: props.placeholder, meta: "" }, ...list];
});

const current = computed(() => rows.value.find((row) => row.value === props.modelValue) || null);
const currentLabel = computed(() => {
  if (current.value && (props.allowEmpty || current.value.value !== "")) return current.value.label;
  if (props.modelValue) return props.modelValue;
  return props.placeholder;
});
const currentMeta = computed(() => (current.value && current.value.value ? current.value.meta : ""));

function toggle() {
  if (props.disabled) return;
  open.value = !open.value;
}

function choose(value) {
  emit("update:modelValue", value);
  open.value = false;
}

function onDoc(ev) {
  if (!root.value?.contains(ev.target)) open.value = false;
}

function onKey(ev) {
  if (ev.key === "Escape") open.value = false;
}

watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) open.value = false;
  },
);

onMounted(() => {
  document.addEventListener("pointerdown", onDoc);
  document.addEventListener("keydown", onKey);
});

onUnmounted(() => {
  document.removeEventListener("pointerdown", onDoc);
  document.removeEventListener("keydown", onKey);
});
</script>
