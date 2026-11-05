<template>
  <div class="desk-req-card" :class="cardClass">
    <header class="desk-req-head">
      <strong>{{ t("desk.requestTitle") }}</strong>
      <span class="desk-req-state">{{ stateLabel }}</span>
    </header>
    <template v-if="creating">
      <p class="desk-req-step">{{ currentStep }}</p>
      <div class="desk-req-progress-bar">
        <div class="desk-req-progress-fill" :style="{ width: `${job.progress || 0}%` }" />
      </div>
      <p v-if="job?.error" class="desk-req-error">{{ job.error }}</p>
    </template>

    <template v-else-if="pending">
      <p class="desk-req-hint">{{ t("desk.requestHint") }}</p>
      <p v-if="error" class="desk-req-error">{{ error }}</p>
      <div class="desk-req-actions">
        <button type="button" class="btn ghost" :disabled="busy" @click="deny">
          {{ t("desk.requestDeny") }}
        </button>
        <button type="button" class="btn primary" :disabled="busy" @click="approve">
          {{ busy ? t("desk.working") : t("desk.requestApprove") }}
        </button>
      </div>
    </template>

    <p v-else class="desk-req-resolved">{{ resolvedText }}</p>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { state } from "../store";

const props = defineProps({
  message: { type: Object, required: true },
});

const { t } = useI18n();
const busy = ref(false);
const error = ref("");
const job = ref(null);
let pollTimer = null;

const meta = computed(() => props.message.meta || {});
const stateName = computed(() => meta.value.state || "pending");
const pending = computed(() => stateName.value === "pending");
const creating = computed(
  () =>
    !!job.value &&
    (job.value.state === "pending" || job.value.state === "running"),
);

const botRow = computed(
  () => state.bots.find((b) => b.name === props.message.bot) || null,
);

const cardClass = computed(() => {
  if (creating.value) return "creating";
  return stateName.value;
});

const stateLabel = computed(() => {
  if (creating.value) return t("desk.creating");
  if (stateName.value === "approved") return t("desk.requestApproved");
  if (stateName.value === "denied") return t("desk.requestDenied");
  return t("desk.requestPending");
});

const resolvedText = computed(() =>
  stateName.value === "denied" ? t("desk.requestDenied") : t("desk.requestApproved"),
);

const currentStep = computed(() => {
  const log = job.value?.log || [];
  if (log.length) return log[log.length - 1];
  return t("desk.waitingLogs");
});

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function refreshJob() {
  if (!job.value?.id) return;
  try {
    const latest = await api.getJob(job.value.id);
    job.value = latest;
    state.jobs[latest.id] = latest;
    if (latest.state === "done") {
      stopPoll();
      try {
        const bot = await api.getBot(props.message.bot);
        const i = state.bots.findIndex((b) => b.name === bot.name);
        if (i >= 0) state.bots[i] = bot;
      } catch {
        /* ignore */
      }
    } else if (latest.state === "error") {
      stopPoll();
    }
  } catch {
    /* keep last */
  }
}

/** Autoriser = créer la VM (terminal et écran) sans modale. */
async function approve() {
  const name = props.message.bot;
  if (!name || busy.value) return;
  busy.value = true;
  error.value = "";
  const internet = botRow.value?.internet !== false;
  try {
    const created = await api.deskCreate(name, { internet });
    job.value = created;
    state.jobs[created.id] = created;
    const i = state.bots.findIndex((b) => b.name === name);
    if (i >= 0) {
      state.bots[i] = {
        ...state.bots[i],
        internet,
        capability: "screen",
        desk: {
          ...(state.bots[i].desk || {}),
          state: "creating",
          mode: "screen",
          internet,
        },
        // Stay on waiting until the VM is running — agent resumes server-side after.
        status: "waiting",
      };
    }
    pollTimer = setInterval(refreshJob, 500);
    await refreshJob();
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}

async function deny() {
  busy.value = true;
  error.value = "";
  try {
    await api.deskRequestResolve(props.message.bot, "deny");
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    busy.value = false;
  }
}

watch(
  () => state.jobs[job.value?.id],
  (j) => {
    if (j) job.value = j;
  },
);

onUnmounted(stopPoll);
</script>
