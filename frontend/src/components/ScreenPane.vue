<template>
  <div class="screen-pane">
    <CreateDeskModal
      v-if="showCreate"
      :bot="bot"
      @close="showCreate = false"
      @done="onCreated"
    />

    <template v-if="running">
      <div class="screen-scroll">
        <div
          ref="frameEl"
          class="screen-frame"
          :class="{ control: state.humanControl }"
        >
          <iframe
            v-if="novncUrl"
            :src="novncUrl"
            title="Desktop"
            @load="onIframeLoad"
          />
          <div v-if="linkState !== 'connected'" class="novnc-status" :class="linkState">
            <p>{{ statusLabel }}</p>
            <button
              v-if="linkState === 'error' || linkState === 'disconnected'"
              type="button"
              class="btn"
              @click="retryNovnc"
            >
              {{ t("screen.reconnect") }}
            </button>
          </div>
          <button
            v-if="!state.humanControl && linkState === 'connected'"
            type="button"
            class="takeover-veil"
            @pointerdown.prevent.stop="takeControl"
          >
            <span class="takeover-hint">{{ t("screen.takeControl") }}</span>
            <span class="takeover-sub">{{ t("screen.takeControlHint") }}</span>
          </button>
        </div>
      </div>
    </template>

    <div v-else-if="creating" class="desk-status">
      <h3>{{ t("desk.creating") }}</h3>
      <p class="desk-step">{{ latestLog || t("desk.waitingLogs") }}</p>
      <div class="job-progress-bar">
        <div class="job-progress-fill" :style="{ width: `${activeJob?.progress || 10}%` }" />
      </div>
      <p class="desk-status-meta">
        {{ activeJob?.progress || 0 }}% — {{ t("desk.working") }}
      </p>
      <p v-if="createStuck" class="desk-stuck">{{ t("desk.stuckHint") }}</p>
      <ul class="job-log">
        <li v-if="!(activeJob?.log || []).length" class="muted">{{ t("desk.waitingLogs") }}</li>
        <li v-for="(line, i) in activeJob?.log || []" :key="i">{{ line }}</li>
      </ul>
    </div>

    <div v-else-if="waking && active" class="desk-status">
      <h3>{{ t("desk.waking") }}</h3>
      <p v-if="wakeError" style="color: var(--danger)">{{ wakeError }}</p>
      <button
        v-if="wakeError"
        class="btn primary"
        type="button"
        :disabled="waking"
        @click="wake"
      >
        {{ t("desk.wakeRetry") }}
      </button>
    </div>

    <div v-else-if="sleeping && active" class="desk-status is-center">
      <h3>{{ t("desk.asleep") }}</h3>
      <button class="btn primary" type="button" :disabled="waking" @click="wake">
        {{ t("desk.wake") }}
      </button>
      <p v-if="wakeError" class="desk-wake-error">{{ wakeError }}</p>
    </div>
    <!-- Keep a quiet placeholder while sleeping but tab not visible (v-show mount). -->
    <div v-else-if="sleeping || waking" class="empty" aria-hidden="true" />

    <div v-else-if="errored" class="desk-status">
      <h3>{{ t("status.error") }}</h3>
      <p style="color: var(--danger)">{{ bot.desk?.last_error || t("desk.createFailed") }}</p>
      <button class="btn primary" @click="showCreate = true">{{ t("screen.create") }}</button>
    </div>

    <div v-else class="empty">
      <p>{{ t("screen.empty") }}</p>
      <button class="btn primary" type="button" @click="showCreate = true">
        {{ t("screen.create") }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { wakeBotDesk } from "../deskWake";
import { state } from "../store";
import CreateDeskModal from "./CreateDeskModal.vue";

const props = defineProps({
  bot: { type: Object, required: true },
  /** True when the Screen tab is visible. Does not wake a sleeping desk. */
  active: { type: Boolean, default: false },
});
const { t } = useI18n();
const novncUrl = ref("");
const showCreate = ref(false);
const waking = ref(false);
const wakeError = ref("");
const frameEl = ref(null);
/** idle | loading | connected | disconnected | error */
const linkState = ref("idle");
/** Ignore outside-click release right after taking control (same gesture). */
let releaseArmedAt = 0;
let connectWatchdog = 0;
let retryTimer = 0;
/** While the user holds the desktop, ping often enough that the 5 min clock stays at zero. */
let activityTimer = 0;

const running = computed(
  () => props.bot.desk?.state === "running" && !!props.bot.desk?.vnc_port,
);
const sleeping = computed(() => props.bot.desk?.state === "sleeping");
const creating = computed(() => props.bot.desk?.state === "creating");
const errored = computed(() => props.bot.desk?.state === "error");

const activeJob = computed(() => {
  const jobs = Object.values(state.jobs || {}).filter((j) => j.bot === props.bot.name);
  jobs.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  return jobs[0] || null;
});

const latestLog = computed(() => {
  const log = activeJob.value?.log || [];
  return log[log.length - 1] || "";
});

const createStuck = computed(() => {
  const j = activeJob.value;
  if (!j || (j.state !== "running" && j.state !== "pending")) return false;
  const updated = Date.parse(j.updated_at || "");
  if (!Number.isFinite(updated)) return false;
  return Date.now() - updated > 20000;
});

const statusLabel = computed(() => {
  if (linkState.value === "loading") return t("screen.connecting");
  if (linkState.value === "disconnected") return t("screen.disconnected");
  if (linkState.value === "error") return t("screen.connectFailed");
  return "";
});

function clearTimers() {
  if (connectWatchdog) {
    clearTimeout(connectWatchdog);
    connectWatchdog = 0;
  }
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = 0;
  }
}

function armConnectWatchdog() {
  if (connectWatchdog) clearTimeout(connectWatchdog);
  connectWatchdog = window.setTimeout(() => {
    if (linkState.value === "loading") {
      linkState.value = "error";
    }
  }, 20000);
}

async function refreshNovnc({ bust = false } = {}) {
  clearTimers();
  if (!running.value) {
    novncUrl.value = "";
    linkState.value = "idle";
    return;
  }
  // Already showing this desktop: opening the tab again must not cover it.
  if (!bust && linkState.value === "connected" && novncUrl.value) return;
  linkState.value = "loading";
  try {
    const info = await api.novnc(props.bot.name);
    if (info.vnc_port) {
      const base =
        info.url ||
        info.direct_url ||
        `/novnc/${props.bot.name}/vnc_lite.html?autoconnect=1&scale=true&path=novnc/${props.bot.name}/&v=8`;
      novncUrl.value = bust ? `${base}${base.includes("?") ? "&" : "?"}r=${Date.now()}` : base;
      armConnectWatchdog();
    } else {
      novncUrl.value = "";
      linkState.value = "error";
      retryTimer = window.setTimeout(() => refreshNovnc({ bust: true }), 2500);
    }
  } catch {
    novncUrl.value = "";
    linkState.value = "error";
    retryTimer = window.setTimeout(() => refreshNovnc({ bust: true }), 2500);
  }
}

function retryNovnc() {
  refreshNovnc({ bust: true });
}

function onIframeLoad() {
  // RFB connect is reported via postMessage; iframe load alone ≠ desktop ready.
  if (linkState.value === "idle") linkState.value = "loading";
}

function onNovncMessage(ev) {
  const data = ev?.data;
  if (!data || data.source !== "autonomous-novnc") return;
  if (data.bot && data.bot !== props.bot.name) return;
  if (data.state === "connected") {
    if (connectWatchdog) {
      clearTimeout(connectWatchdog);
      connectWatchdog = 0;
    }
    linkState.value = "connected";
  } else if (data.state === "disconnected") {
    linkState.value = data.clean ? "disconnected" : "error";
  }
}

function takeControl() {
  state.humanControl = true;
  state.keepControl = false;
  releaseArmedAt = performance.now() + 350;
  nextTick(() => {
    const iframe = frameEl.value?.querySelector("iframe");
    try {
      iframe?.focus?.();
    } catch {
      /* cross-origin ok */
    }
  });
}

/** Relâche dès qu'on clique en dehors de la zone écran (pas de bouton). */
function onDocPointerDown(ev) {
  if (!state.humanControl) return;
  if (performance.now() < releaseArmedAt) return;
  const frame = frameEl.value;
  if (!frame) return;
  const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
  if (path.includes(frame) || frame.contains(ev.target)) return;
  state.humanControl = false;
}

async function onCreated() {
  showCreate.value = false;
  await refreshNovnc({ bust: true });
}

async function wake() {
  if (waking.value || !sleeping.value) return;
  waking.value = true;
  wakeError.value = "";
  try {
    await wakeBotDesk(props.bot.name);
  } catch (e) {
    wakeError.value = e.message || String(e);
  } finally {
    waking.value = false;
  }
}

function stopActivityHold() {
  if (activityTimer) {
    clearInterval(activityTimer);
    activityTimer = 0;
  }
}

function holdActivity() {
  if (!props.active || !state.humanControl || !running.value) return;
  api.deskActivity(props.bot.name).catch(() => {});
}

function syncActivityHold() {
  stopActivityHold();
  if (!props.active || !state.humanControl || !running.value) return;
  holdActivity();
  activityTimer = window.setInterval(holdActivity, 60_000);
}

async function ensureVisible() {
  if (!props.active) return;
  if (running.value) await refreshNovnc({ bust: false });
}

watch(running, (isRunning) => {
  if (isRunning && props.active) refreshNovnc({ bust: true });
  else if (!isRunning) {
    clearTimers();
    novncUrl.value = "";
    linkState.value = "idle";
  }
});

watch(
  () => [props.active, state.humanControl, running.value],
  () => syncActivityHold(),
);

watch(
  () => props.active,
  (on) => {
    if (on) ensureVisible();
  },
);

watch(
  () => props.bot.name,
  () => {
    state.humanControl = false;
    wakeError.value = "";
    ensureVisible();
  },
);

onMounted(() => {
  ensureVisible();
  document.addEventListener("pointerdown", onDocPointerDown, true);
  window.addEventListener("message", onNovncMessage);
});

onUnmounted(() => {
  clearTimers();
  stopActivityHold();
  document.removeEventListener("pointerdown", onDocPointerDown, true);
  window.removeEventListener("message", onNovncMessage);
});
</script>

<style scoped>
.desk-status {
  padding: 2rem 1.5rem;
  max-width: 520px;
}
.desk-status.is-center {
  flex: 1;
  align-self: stretch;
  max-width: none;
  width: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 0.85rem;
}
.desk-status h3 {
  margin: 0 0 1rem;
}
.desk-status.is-center h3 {
  margin: 0;
}
.desk-wake-error {
  margin: 0;
  color: var(--danger);
}
.desk-step {
  margin: 0 0 0.75rem;
  font-weight: 600;
  font-size: 0.92rem;
  line-height: 1.35;
  word-break: break-word;
}
.desk-status-meta {
  color: var(--muted);
  margin: 0.75rem 0;
}
.desk-stuck {
  margin: 0 0 0.65rem;
  padding: 0.45rem 0.6rem;
  border-radius: 8px;
  background: #fff6e8;
  border: 1px solid #f0d7a8;
  color: #8a5a00;
  font-size: 0.82rem;
}
.job-progress-bar {
  height: 8px;
  background: #ececef;
  border-radius: 999px;
  overflow: hidden;
  border: 1px solid var(--line);
}
.job-progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.25s ease;
}
.job-log {
  list-style: none;
  margin: 0;
  padding: 0.65rem 0.75rem;
  max-height: 240px;
  overflow: auto;
  background: #1c1c1e;
  border: 1px solid #2c2c2e;
  border-radius: 8px;
  font-family: var(--mono);
  font-size: 0.78rem;
  color: #d4d4d8;
}
.job-log li {
  margin: 0.2rem 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.job-log .muted {
  color: #8e8e93;
}
.novnc-status {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: grid;
  place-content: center;
  gap: 0.75rem;
  margin: 0;
  padding: 1.25rem;
  text-align: center;
  background: color-mix(in srgb, var(--bg, #f4f4f6) 82%, transparent);
  color: var(--text);
  font-size: 0.92rem;
  font-weight: 600;
}
.novnc-status.loading {
  inset: auto;
  top: 0.65rem;
  left: 50%;
  transform: translateX(-50%);
  place-content: center;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--bg, #fff) 90%, var(--accent));
  border: 1px solid color-mix(in srgb, var(--line, #ddd) 80%, transparent);
  box-shadow: 0 4px 14px color-mix(in srgb, #000 10%, transparent);
  font-size: 0.78rem;
  pointer-events: none;
}
.novnc-status p {
  margin: 0;
}
.novnc-status.error,
.novnc-status.disconnected {
  color: var(--danger, #b42318);
}
.takeover-veil {
  position: absolute;
  inset: 0;
  z-index: 2;
  border: 0;
  border-radius: inherit;
  margin: 0;
  padding: 0 1rem 1.1rem;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 0.2rem;
  background: transparent;
  color: var(--text);
  font: inherit;
}
.takeover-veil:hover {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.takeover-veil:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -3px;
}
.takeover-hint {
  display: inline-block;
  padding: 0.45rem 0.85rem;
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg, #fff) 88%, var(--accent));
  border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--line, #ddd));
  box-shadow: 0 6px 18px color-mix(in srgb, #000 12%, transparent);
  font-size: 0.88rem;
  font-weight: 650;
  letter-spacing: 0.01em;
}
.takeover-sub {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--muted, #6b6b70);
  text-shadow: 0 1px 0 color-mix(in srgb, var(--bg, #fff) 80%, transparent);
}
</style>
