<template>
  <section class="ui-card" :class="{ 'has-head': !!title || $slots.head || $slots.icon }">
    <header v-if="title || $slots.head || $slots.icon" class="ui-card-head">
      <UiIconBadge v-if="$slots.icon" :tone="iconTone" :size="iconSize">
        <slot name="icon" />
      </UiIconBadge>
      <div class="ui-card-titles">
        <slot name="head">
          <h3 v-if="title">{{ title }}</h3>
          <p v-if="hint" class="hint">{{ hint }}</p>
        </slot>
      </div>
      <div v-if="$slots.aside" class="ui-card-aside">
        <slot name="aside" />
      </div>
    </header>
    <div v-if="$slots.default" class="ui-card-body" :class="{ flush }">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="ui-card-foot">
      <slot name="footer" />
    </footer>
  </section>
</template>

<script setup>
import UiIconBadge from "./UiIconBadge.vue";

defineProps({
  title: { type: String, default: "" },
  hint: { type: String, default: "" },
  iconTone: { type: String, default: "accent" },
  iconSize: { type: String, default: "md" },
  /** Drop body padding when the slot already manages spacing (lists, toggles). */
  flush: { type: Boolean, default: false },
});
</script>
