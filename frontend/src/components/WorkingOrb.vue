<template>
  <canvas
    ref="canvas"
    class="working-orb"
    role="img"
    :aria-label="label"
    :style="{ width: `${orbSize}px`, height: `${orbSize}px` }"
  />
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { MODE_FRAMES, paintFrame, resolvePreset } from "thinking-orbs/engine";

const props = defineProps({
  state: { type: String, default: "working" },
  size: { type: Number, default: 20 },
  speed: { type: Number, default: 1 },
  dark: { type: Boolean, default: false },
  paused: { type: Boolean, default: false },
  label: { type: String, default: "Working" },
});

const canvas = ref(null);
const orbSize = computed(() => (props.size === 64 ? 64 : 20));

let cleanup = () => {};

async function start() {
  cleanup();
  await nextTick();
  const el = canvas.value;
  if (!el) return;

  const size = orbSize.value;
  const dpr = Math.min(2, typeof devicePixelRatio !== "undefined" ? devicePixelRatio || 1 : 1);
  el.width = Math.round(size * dpr);
  el.height = Math.round(size * dpr);

  const ctx = el.getContext("2d");
  if (!ctx) return;

  const { mode, speed: baseSpeed, opts } = resolvePreset(props.state, size);
  const frameFn = MODE_FRAMES[mode];
  if (typeof frameFn !== "function") return;
  const effSpeed = baseSpeed * props.speed;
  const reduced =
    typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  const paint = (tSec) => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    paintFrame(ctx, frameFn(size, tSec, opts), !!props.dark, null);
  };

  if (reduced || props.paused) {
    paint(0.6);
    cleanup = () => {};
    return;
  }

  let raf = 0;
  let running = false;

  const tick = () => {
    paint((performance.now() / 1000) * effSpeed);
    if (running) raf = requestAnimationFrame(tick);
  };

  const resume = () => {
    if (running) return;
    running = true;
    raf = requestAnimationFrame(tick);
  };

  const pause = () => {
    running = false;
    cancelAnimationFrame(raf);
  };

  paint((performance.now() / 1000) * effSpeed);
  resume();

  const onVis = () => {
    if (document.visibilityState === "hidden") pause();
    else resume();
  };
  document.addEventListener("visibilitychange", onVis);

  cleanup = () => {
    pause();
    document.removeEventListener("visibilitychange", onVis);
  };
}

onMounted(() => {
  start();
});
onBeforeUnmount(() => cleanup());
watch(
  () => [props.state, props.size, props.speed, props.dark, props.paused],
  () => start()
);
</script>
