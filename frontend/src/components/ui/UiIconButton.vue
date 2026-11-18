<template>
  <button
    class="ui-icon-btn"
    :class="[
      {
        danger,
        'is-file': sizeVariant === 'file',
        'is-compact': sizeVariant === 'compact',
        'is-chrome': sizeVariant === 'chrome',
      },
      buttonClass,
    ]"
    type="button"
    :disabled="disabled"
    :aria-label="label"
    :aria-expanded="expandedAttr"
    :title="title || undefined"
  >
    <slot>
      <UiIcon :name="icon" :size="resolvedIconSize" />
    </slot>
  </button>
</template>

<script setup>
import { computed } from "vue";
import UiIcon from "./UiIcon.vue";

const props = defineProps({
  icon: { type: String, default: "trash" },
  label: { type: String, default: "" },
  /** Optional native title; prefer custom tips when possible. */
  title: { type: String, default: "" },
  disabled: { type: Boolean, default: false },
  danger: { type: Boolean, default: false },
  /** default (32px) | file (30px) | compact (Events) | chrome (Hub 36px). */
  sizeVariant: { type: String, default: "default" },
  buttonClass: { type: [String, Object, Array], default: "" },
  iconSize: { type: [Number, String], default: 0 },
  /** Optional aria-expanded for toggles. */
  expanded: { type: [Boolean, String], default: undefined },
});

const resolvedIconSize = computed(() => {
  if (Number(props.iconSize) > 0) return Number(props.iconSize);
  if (props.sizeVariant === "compact") return 15;
  if (props.sizeVariant === "chrome") return 18;
  return 16;
});

const expandedAttr = computed(() => {
  if (props.expanded === undefined || props.expanded === "") return undefined;
  return props.expanded === true || props.expanded === "true" ? "true" : "false";
});
</script>
