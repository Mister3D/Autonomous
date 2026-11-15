<template>
  <button
    class="settings-orb ui-orb"
    type="button"
    :aria-label="label"
    :aria-expanded="expanded || undefined"
  >
    <slot />
  </button>
</template>

<script setup>
defineProps({
  label: { type: String, default: "" },
  /** "true" or "false" when the orb opens something. Omit otherwise. */
  expanded: { type: String, default: "" },
});
</script>
