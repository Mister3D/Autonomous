<template>
  <div class="settings-tz">
    <input
      :value="modelValue"
      type="text"
      :placeholder="placeholder"
      :disabled="disabled"
      autocomplete="off"
      spellcheck="false"
      role="combobox"
      aria-autocomplete="list"
      :aria-expanded="open && matches.length > 0"
      @focus="onFocus"
      @input="onInput"
      @keydown="onKey"
      @blur="open = false"
    />
    <ul v-if="open && matches.length" class="tz-suggest" role="listbox">
      <li v-for="(m, i) in matches" :key="m">
        <button type="button" :class="{ active: i === active }" @mousedown.prevent="pick(m)">{{ m }}</button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "" },
  disabled: { type: Boolean, default: false },
});
const emit = defineEmits(["update:modelValue"]);
const open = ref(false);
const active = ref(0);
const typed = ref(false);

// On focus show every model; once the user types, filter (substring, case-insensitive).
const matches = computed(() => {
  const q = typed.value ? (props.modelValue || "").trim().toLowerCase() : "";
  const list = q ? props.options.filter((m) => m.toLowerCase().includes(q)) : props.options;
  return list.slice(0, 50);
});
watch(matches, () => (active.value = 0));
// A freshly fetched list opens the suggestions right away.
watch(
  () => props.options,
  (o) => {
    if (o.length) {
      typed.value = false;
      open.value = true;
    }
  },
);

function onFocus() {
  typed.value = false;
  open.value = true;
}
function onInput(ev) {
  typed.value = true;
  open.value = true;
  emit("update:modelValue", ev.target.value);
}
function onKey(ev) {
  if (ev.key === "ArrowDown") {
    ev.preventDefault();
    open.value = true;
    active.value = Math.min(active.value + 1, Math.max(matches.value.length - 1, 0));
  } else if (ev.key === "ArrowUp") {
    ev.preventDefault();
    active.value = Math.max(active.value - 1, 0);
  } else if (ev.key === "Enter" && open.value && matches.value[active.value]) {
    ev.preventDefault();
    pick(matches.value[active.value]);
  } else if (ev.key === "Escape") {
    open.value = false;
  }
}
function pick(m) {
  emit("update:modelValue", m);
  open.value = false;
}
</script>
