<template>
  <span
    ref="host"
    class="companion-avatar"
    :class="[`is-${size}`]"
    :data-character="character"
    :data-avatar-stage="''"
  />
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from "vue";
import { Avatar } from "./engine.js";
import { getCharacter, CHARACTER_IDS } from "./catalog.js";
import "./styles.css";

const props = defineProps({
  /** Catalog id (renard, chat, …) */
  character: { type: String, required: true },
  /** Swatch index 0..17 */
  color: { type: Number, default: 0 },
  /**
   * work | notify | await | idle
   * (wait accepted as alias of await)
   */
  state: { type: String, default: "idle" },
  /** sm fills parent; lg same — size is only a CSS hint */
  size: { type: String, default: "sm" },
  /**
   * Element that drives idle eye-tracking on hover.
   * HTMLElement, Vue ref, or null → host itself, then closest button/li.
   */
  trackZone: { type: [Object, null], default: null },
});

const host = ref(null);
let avatar = null;

function resolveZone() {
  const z = props.trackZone;
  if (z && z.nodeType === 1) return z;
  if (z && z.value && z.value.nodeType === 1) return z.value;
  const el = host.value;
  if (!el) return null;
  return el.closest("button") || el.closest("li") || el;
}

function mountAvatar() {
  const el = host.value;
  if (!el) return;
  const entry = getCharacter(props.character) || getCharacter(CHARACTER_IDS[0]);
  if (!entry) return;
  if (avatar) {
    avatar.destroy();
    avatar = null;
  }
  avatar = new Avatar(entry.id, el, entry);
  avatar.setColor(props.color);
  avatar.setState(props.state);
  avatar.bindIdleTracking(resolveZone());
}

onMounted(async () => {
  await nextTick();
  mountAvatar();
});

onBeforeUnmount(() => {
  if (avatar) {
    avatar.destroy();
    avatar = null;
  }
});

watch(
  () => props.character,
  () => mountAvatar()
);

watch(
  () => props.color,
  (v) => {
    if (avatar) avatar.setColor(v);
  }
);

watch(
  () => props.state,
  (v) => {
    if (avatar) avatar.setState(v);
  }
);

watch(
  () => props.trackZone,
  () => {
    if (avatar) avatar.bindIdleTracking(resolveZone());
  }
);
</script>

<style scoped>
.companion-avatar {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
  border-radius: 0;
}
.companion-avatar :deep(svg.avatar-svg) {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}
</style>
