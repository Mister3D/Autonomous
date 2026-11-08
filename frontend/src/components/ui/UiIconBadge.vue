<template>
  <span class="ui-icon-badge" :class="[`is-${tone}`, `is-${size}`]" aria-hidden="true">
    <slot />
  </span>
</template>

<script setup>
defineProps({
  tone: { type: String, default: "accent" }, // accent | muted | ok | danger
  size: { type: String, default: "md" }, // sm | md | lg
});
</script>
