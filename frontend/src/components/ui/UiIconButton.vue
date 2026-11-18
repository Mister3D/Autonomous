<template>
  <button
    class="ui-icon-btn"
    :class="[{ danger, 'is-file': sizeVariant === 'file' }, buttonClass]"
    type="button"
    :disabled="disabled"
    :aria-label="label"
    :title="title || undefined"
  >
    <UiIcon :name="icon" :size="iconSize" />
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
  /** default (32px) | file (30px, Files pane). */
  sizeVariant: { type: String, default: "default" },
  buttonClass: { type: [String, Object, Array], default: "" },
  iconSize: { type: [Number, String], default: 16 },
});

const iconSize = computed(() => Number(props.iconSize) || 16);
</script>
