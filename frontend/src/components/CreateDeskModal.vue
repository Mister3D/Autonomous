<template>
  <div class="modal-backdrop" @click.self="onCancel">
    <div class="modal desk-modal">
      <h2>{{ t("desk.createTitle") }}</h2>
      <p v-if="replacing && !job" class="field-hint" style="margin-top: -0.35rem; margin-bottom: 0.85rem">
        {{ t("desk.replaceHint") }}
      </p>

      <template v-if="!job">
        <label class="choice" style="margin: 1rem 0">
          <input v-model="internet" type="checkbox" />
          <span>
            <strong>{{ t("desk.internet") }}</strong>
          </span>
        </label>

        <p v-if="error" style="color: var(--danger)">{{ error }}</p>
        <div style="display: flex; gap: 0.5rem; justify-content: flex-end">
          <button class="btn ghost" type="button" @click="onCancel">{{ t("create.cancel") }}</button>
          <button class="btn primary" type="button" :disabled="busy" @click="start">
            {{ t("desk.createSubmit") }}
          </button>
        </div>
      </template>

      <template v-else>
        <div class="job-progress">
          <p class="job-step">{{ currentStep }}</p>
          <div class="job-progress-bar">
            <div class="job-progress-fill" :style="{ width: `${job.progress || 0}%` }" />
          </div>
          <div class="job-meta">
            <strong>{{ statusLabel }}</strong>
            <span>{{ job.progress || 0 }}% · {{ elapsedLabel }}</span>
          </div>
          <p v-if="maybeStuck" class="job-stuck">{{ t("desk.stuckHint") }}</p>
          <ul ref="logEl" class="job-log">
            <li v-if="!(job.log || []).length" class="muted">{{ t("desk.waitingLogs") }}</li>
            <li v-for="(line, i) in job.log || []" :key="i">{{ line }}</li>
          </ul>
          <p v-if="job.error" class="job-error">{{ job.error }}</p>
        </div>
        <div style="display: flex; justify-content: flex-end; margin-top: 1rem; gap: 0.5rem">
          <button
            v-if="job.state === 'done' || job.state === 'error'"
            class="btn primary"
            type="button"
            @click="close"
          >
            {{ t("ok") }}
          </button>
          <button v-else class="btn ghost" type="button" disabled>
            {{ t("desk.working") }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { state } from "../store";

const props = defineProps({
  bot: { type: Object, required: true },
});
const emit = defineEmits(["close", "done"]);

const { t } = useI18n();
/** Recreate keeps ~/files. One VM always includes the shell and the desktop. */
const replacing = computed(() => {
  const st = props.bot.desk?.state;
  return st === "running" || st === "sleeping" || st === "creating";
});
const internet = ref(props.bot.internet !== false);
const busy = ref(false);
const error = ref("");
const job = ref(null);
const logEl = ref(null);
const nowTick = ref(Date.now());
let pollTimer = null;
let tickTimer = null;

const statusLabel = computed(() => {
  const s = job.value?.state;
  if (s === "pending" || s === "running") return t("desk.creating");
  if (s === "done") return t("desk.running");
  if (s === "error") return t("status.error");
  return s || "";
});

const currentStep = computed(() => {
  const log = job.value?.log || [];
  if (log.length) return log[log.length - 1];
  return t("desk.waitingLogs");
});

const elapsedLabel = computed(() => {
  const created = job.value?.created_at;
  if (!created) return "0s";
  const start = Date.parse(created);
  if (!Number.isFinite(start)) return "0s";
  const sec = Math.max(0, Math.floor((nowTick.value - start) / 1000));
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
});

const maybeStuck = computed(() => {
  const j = job.value;
  if (!j || (j.state !== "running" && j.state !== "pending")) return false;
  const updated = Date.parse(j.updated_at || "");
  if (!Number.isFinite(updated)) return false;
  return nowTick.value - updated > 20000;
});

function onCancel() {
  if (job.value && (job.value.state === "pending" || job.value.state === "running")) return;
  close();
}

function close() {
  stopPoll();
  emit("close");
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (tickTimer) {
    clearInterval(tickTimer);
    tickTimer = null;
  }
}

async function scrollLog() {
  await nextTick();
  const el = logEl.value;
  if (el) el.scrollTop = el.scrollHeight;
}

async function refreshJob() {
  if (!job.value?.id) return;
  try {
    const latest = await api.getJob(job.value.id);
    job.value = latest;
    state.jobs[latest.id] = latest;
    scrollLog();
    if (latest.state === "done") {
      stopPoll();
      try {
        const bot = await api.getBot(props.bot.name);
        const i = state.bots.findIndex((b) => b.name === bot.name);
        if (i >= 0) state.bots[i] = bot;
      } catch {
        /* ignore */
      }
      emit("done", latest);
    } else if (latest.state === "error") {
      stopPoll();
    }
  } catch {
    /* keep last known */
  }
}

async function start() {
  busy.value = true;
  error.value = "";
  try {
    const created = await api.deskCreate(props.bot.name, {
      internet: internet.value,
    });
    job.value = created;
    state.jobs[created.id] = created;
    const i = state.bots.findIndex((b) => b.name === props.bot.name);
    if (i >= 0) {
      state.bots[i] = {
        ...state.bots[i],
        internet: internet.value,
        capability: "screen",
        desk: {
          ...(state.bots[i].desk || {}),
          state: "creating",
          mode: "screen",
          internet: internet.value,
        },
        status: "waiting",
      };
    }
    tickTimer = setInterval(() => {
      nowTick.value = Date.now();
    }, 1000);
    pollTimer = setInterval(refreshJob, 500);
    await refreshJob();
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}

watch(
  () => state.jobs[job.value?.id],
  (j) => {
    if (j) {
      job.value = j;
      scrollLog();
    }
  }
);

onUnmounted(stopPoll);
</script>

<style scoped>
.desk-modal {
  width: min(560px, calc(100vw - 2rem));
}
.choice {
  display: flex;
  gap: 0.65rem;
  align-items: flex-start;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  margin-bottom: 0.45rem;
  cursor: pointer;
}
.choice input {
  margin-top: 0.25rem;
}
.choice strong {
  display: block;
}
.job-step {
  margin: 0 0 0.75rem;
  font-size: 0.92rem;
  font-weight: 600;
  line-height: 1.35;
  color: var(--ink);
  word-break: break-word;
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
.job-meta {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  margin: 0.6rem 0;
  font-size: 0.9rem;
}
.job-stuck {
  margin: 0 0 0.55rem;
  padding: 0.45rem 0.6rem;
  border-radius: 8px;
  background: #fff6e8;
  border: 1px solid #f0d7a8;
  color: #8a5a00;
  font-size: 0.82rem;
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
.job-error {
  margin: 0.65rem 0 0;
  color: var(--danger);
  font-size: 0.88rem;
  white-space: pre-wrap;
}
</style>
