<template>
  <component
    :is="tag"
    class="btn ui-btn"
    :class="[
      variantClass,
      {
        'is-ok': ok,
        'is-block': block,
        'is-icon-only': iconOnly,
      },
    ]"
    v-bind="bindAttrs"
  >
    <span v-if="$slots.icon" class="ui-btn-icon" aria-hidden="true">
      <slot name="icon" />
    </span>
    <span v-if="$slots.default" class="ui-btn-label"><slot /></span>
  </component>
</template>

<script setup>
import { computed } from "vue";
import { RouterLink } from "vue-router";

const props = defineProps({
  variant: {
    type: String,
    default: "secondary", // primary | secondary | success | danger | ghost | danger-ghost
  },
  type: { type: String, default: "button" },
  disabled: { type: Boolean, default: false },
  ok: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  iconOnly: { type: Boolean, default: false },
  /** When set, renders a RouterLink. */
  to: { type: [String, Object], default: "" },
  /** When set (and no `to`), renders an `<a>`. */
  href: { type: String, default: "" },
  download: { type: String, default: "" },
  target: { type: String, default: "" },
  rel: { type: String, default: "" },
});

const variantClass = computed(() => {
  if (props.variant === "secondary") return "";
  if (props.variant === "success") return "is-ok";
  return props.variant;
});

const tag = computed(() => {
  if (props.to) return RouterLink;
  if (props.href) return "a";
  return "button";
});

const bindAttrs = computed(() => {
  if (props.to) {
    return {
      to: props.to,
      "aria-disabled": props.disabled || undefined,
    };
  }
  if (props.href) {
    return {
      href: props.disabled ? undefined : props.href,
      download: props.download || undefined,
      target: props.target || undefined,
      rel: props.rel || undefined,
      "aria-disabled": props.disabled || undefined,
      role: "button",
      tabindex: props.disabled ? -1 : undefined,
      onClick: props.disabled
        ? (ev) => {
            ev.preventDefault();
          }
        : undefined,
    };
  }
  return {
    type: props.type,
    disabled: props.disabled,
  };
});
</script>
