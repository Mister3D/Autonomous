<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="modal-backdrop"
      @click.self="onBackdrop"
    >
      <component
        :is="as"
        class="modal"
        :class="panelClass"
        role="dialog"
        aria-modal="true"
        :aria-label="ariaLabel || undefined"
        :aria-labelledby="ariaLabelledby || undefined"
        @submit="onSubmit"
      >
        <slot />
      </component>
    </div>
  </Teleport>
</template>

<script setup>
import { onMounted, onUnmounted, watch } from "vue";

const props = defineProps({
  open: { type: Boolean, default: true },
  /** Panel element: div (default) or form. */
  as: { type: String, default: "div" },
  panelClass: { type: [String, Object, Array], default: "" },
  ariaLabel: { type: String, default: "" },
  ariaLabelledby: { type: String, default: "" },
  /** Close when the backdrop is clicked (default true). */
  closeOnBackdrop: { type: Boolean, default: true },
  /** Close on Escape (default true). */
  closeOnEscape: { type: Boolean, default: true },
});

const emit = defineEmits(["close", "submit"]);

function onBackdrop() {
  if (props.closeOnBackdrop) emit("close");
}

function onSubmit(ev) {
  emit("submit", ev);
}

function onKey(ev) {
  if (ev.key === "Escape" && props.open && props.closeOnEscape) {
    emit("close");
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) document.addEventListener("keydown", onKey);
    else document.removeEventListener("keydown", onKey);
  },
);

onMounted(() => {
  if (props.open) document.addEventListener("keydown", onKey);
});

onUnmounted(() => {
  document.removeEventListener("keydown", onKey);
});
</script>
