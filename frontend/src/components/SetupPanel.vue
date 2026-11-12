<template>
  <div class="setup-panel" :class="{ 'is-home': !showChecklist }">
    <img class="setup-logo" src="/logo.png" :alt="t('brand')" />
    <template v-if="showChecklist && !setup">
      <p class="hint">{{ t("setup.loading") }}</p>
    </template>
    <template v-else-if="showChecklist">
      <h2 class="setup-title">{{ setup.ready ? t("setup.titleReady") : t("setup.title") }}</h2>
      <p class="hint">{{ setup.ready ? t("setup.introReady") : t("setup.intro") }}</p>
      <div class="setup-toolbar">
        <button class="btn" type="button" :disabled="checking" @click="recheck">
          {{ checking ? t("setup.checking") : t("setup.recheck") }}
        </button>
        <router-link v-if="setup.ready" class="btn primary" to="/" @click="forceList = false">
          {{ t("setup.done") }}
        </router-link>
      </div>

      <h3 class="setup-section">{{ t("setup.required") }}</h3>
      <ul class="setup-list">
        <SetupItem v-for="c in required" :key="c.id" :check="c" :log="itemLog(c)" @job="runJob" />
      </ul>
      <h3 class="setup-section">{{ t("setup.optional") }}</h3>
      <ul class="setup-list">
        <SetupItem v-for="c in optional" :key="c.id" :check="c" :log="itemLog(c)" @job="runJob" />
      </ul>
      <div v-if="showFirstChatCta" class="setup-first-chat">
        <button
          class="btn primary"
          type="button"
          :disabled="!canStartFirstChat || starting"
          :title="canStartFirstChat ? undefined : t('setup.firstChatLocked')"
          @click="startFirstChat"
        >
          {{ starting ? t("setup.firstChatBusy") : t("setup.firstChat") }}
        </button>
        <p class="hint">{{ t("setup.firstChatHint") }}</p>
      </div>
      <p v-if="error" class="vault-error">{{ error }}</p>
    </template>
    <template v-else>
      <p class="tagline">{{ t("tagline") }}</p>
      <div class="home-hero">
        <div class="home-hero-copy">
          <h2 class="home-title">{{ t("home.welcome") }}</h2>
          <template v-if="showFirstChatCta">
            <p class="hint">{{ t("setup.firstChatHintReady") }}</p>
            <button
              class="home-cta"
              type="button"
              :disabled="starting"
              @click="startFirstChat"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path fill="currentColor" d="M5 5.8A2.8 2.8 0 0 1 7.8 3h8.4A2.8 2.8 0 0 1 19 5.8v6.2a2.8 2.8 0 0 1-2.8 2.8H11l-3.8 2.6c-.7.48-1.7-.05-1.7-.9V14.8H7.8A2.8 2.8 0 0 1 5 12V5.8Z" />
              </svg>
              {{ starting ? t("setup.firstChatBusy") : t("setup.firstChat") }}
            </button>
          </template>
          <p v-else-if="firstChatGateReady" class="home-greeting">{{ t("home.greeting") }}</p>
        </div>
        <img class="home-fox" src="/home-fox.png" alt="" />
      </div>
      <p v-if="error" class="vault-error">{{ error }}</p>
      <section class="home-card">
        <router-link class="home-card-head" to="/setup">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 3.2v2.1M12 18.7v2.1M4.9 6.6l1.5 1.5M17.6 15.9l1.5 1.5M3.2 12h2.1M18.7 12h2.1M4.9 17.4l1.5-1.5M17.6 8.1l1.5-1.5" />
          </svg>
          {{ t("setup.link") }}
        </router-link>
        <div v-if="brokenOptional.length" class="setup-banner" role="status">
          {{ t("setup.optionalBroken", { items: brokenOptional.map((c) => t(c.label)).join(", ") }) }}
          <router-link to="/setup">{{ t("setup.open") }}</router-link>
        </div>
        <div v-if="showUpdateUi" class="home-status" role="status">
          <span class="home-status-name">
            {{ t("home.updateLine", { channel: updateInfo.channel, version: updateInfo.version || "—" }) }}
            <span v-if="updateJump" class="home-status-jump">→ {{ updateJump }}</span>
          </span>
          <span class="home-status-side">
            <button
              type="button"
              class="home-refresh"
              :class="{ 'is-busy': updateBusy && !updateApplying }"
              :disabled="updateBusy"
              :aria-label="t('update.check')"
              :title="t('update.check')"
              @click="forceCheckUpdate"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M21 12a9 9 0 0 0-9-9 9.2 9.2 0 0 0-6.4 2.6L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.2 9.2 0 0 0 6.4-2.6L21 16" />
                <path d="M21 21v-5h-5" />
              </svg>
            </button>
            <span v-if="updateUpToDate" class="home-pill">{{ t("update.upToDateShort") }}</span>
            <button
              v-else-if="canApplyUpdate || updateApplying"
              class="home-apply"
              type="button"
              :disabled="!canApplyUpdate || updateBusy"
              @click="runApplyUpdate"
            >
              {{ updateApplying ? t("update.applying") : t("update.apply") }}
            </button>
            <button
              v-if="showForceUpdate && !updateApplying"
              class="home-apply"
              type="button"
              :disabled="updateBusy"
              @click="runForceUpdate"
            >
              {{ t("update.force") }}
            </button>
          </span>
          <p v-if="updateNote" class="home-status-note">{{ updateNote }}</p>
          <pre v-if="updateLog.length" class="setup-log">{{ updateLog.join("\n") }}</pre>
          <p v-if="updateError" class="vault-error">{{ updateError }}</p>
        </div>
        <p v-if="piChecking && !piItems.length" class="home-quiet">{{ t("piPackages.checking") }}</p>
        <ul v-else-if="piItems.length" class="home-status-list" :aria-label="t('piPackages.title')">
          <li v-for="item in piItems" :key="item.id" class="home-status">
            <span class="home-status-name">
              {{ t("home.moduleLine", { name: item.label, version: item.current || "—" }) }}
              <span v-if="item.update && item.latest" class="home-status-jump">→ {{ item.latest }}</span>
            </span>
            <span class="home-status-side">
              <button
                type="button"
                class="home-refresh"
                :class="{ 'is-busy': piChecking }"
                :disabled="piBusy"
                :aria-label="t('update.check')"
                :title="t('update.check')"
                @click="loadPiPackages(true)"
              >
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path d="M21 12a9 9 0 0 0-9-9 9.2 9.2 0 0 0-6.4 2.6L3 8" />
                  <path d="M3 3v5h5" />
                  <path d="M3 12a9 9 0 0 0 9 9 9.2 9.2 0 0 0 6.4-2.6L21 16" />
                  <path d="M21 21v-5h-5" />
                </svg>
              </button>
              <span v-if="!item.update && !item.error" class="home-pill">{{ t("update.upToDateShort") }}</span>
              <button
                v-else-if="item.update"
                type="button"
                class="home-apply"
                :disabled="piBusy"
                @click="runPiUpdates([item.id])"
              >
                {{ piBusy ? t("piPackages.applying") : t("piPackages.apply") }}
              </button>
            </span>
            <p v-if="item.error" class="home-status-note">{{ item.error }}</p>
          </li>
        </ul>
        <p v-if="piError" class="vault-error">{{ piError }}</p>
        <pre v-if="piLog.length" class="setup-log">{{ piLog.join("\n") }}</pre>
      </section>
    </template>
    <!-- Updates must stay reachable during incomplete setup (checklist), not only on the ready home. -->
    <div
      v-if="showChecklist && setup && showUpdateUi"
      class="setup-update"
      :class="{
        'is-action': updateNeedsAction,
        'is-busy': updateApplying,
        'is-checklist': showChecklist,
      }"
      role="status"
    >
      <template v-if="updateNeedsAction">
        <div class="setup-update-card">
          <div class="setup-update-head">
            <span class="setup-update-ico" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 4v10" />
                <path d="m8 10 4 4 4-4" />
                <path d="M5 18h14" />
              </svg>
            </span>
            <div class="setup-update-copy">
              <p class="setup-update-title">{{ updateTitle }}</p>
              <p v-if="updateMeta" class="setup-update-meta">{{ updateMeta }}</p>
            </div>
          </div>
          <button
            v-if="canApplyUpdate || updateApplying"
            class="btn primary setup-update-apply"
            type="button"
            :disabled="!canApplyUpdate || updateBusy"
            @click="runApplyUpdate"
          >
            {{ updateApplying ? t("update.applying") : t("update.apply") }}
          </button>
          <button
            v-if="showForceUpdate && !updateApplying"
            class="btn setup-update-apply setup-update-force"
            type="button"
            :disabled="updateBusy"
            @click="runForceUpdate"
          >
            {{ t("update.force") }}
          </button>
        </div>
        <pre v-if="updateLog.length" class="setup-log">{{ updateLog.join("\n") }}</pre>
        <p v-if="updateError" class="vault-error">{{ updateError }}</p>
      </template>
      <template v-else>
        <span class="setup-update-quiet">
          <span>{{ updateSummary }}</span>
          <button
            type="button"
            class="setup-update-check"
            :disabled="updateBusy"
            @click="forceCheckUpdate"
          >
            {{ updateBusy ? t("update.checking") : t("update.checkShort") }}
          </button>
        </span>
        <p v-if="updateError" class="vault-error">{{ updateError }}</p>
        <button
          v-if="showForceUpdate && !updateApplying"
          class="btn setup-update-force"
          type="button"
          :disabled="updateBusy"
          @click="runForceUpdate"
        >
          {{ t("update.force") }}
        </button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api";
import {
  rawMessage,
  refreshFirstChatPrefsPending,
  resumeFirstChatPrefsIfStuck,
} from "../firstChatPrefs";
import { botPath } from "../router";
import { dropOptimisticDupes, isOptimisticMessageId, refreshSetup, setupReady, state } from "../store";
import { refreshBots } from "../sync";
import {
  forgetUpdateStatus,
  readUpdateStatus,
  writeUpdateStatus,
} from "../updateStatusCache";
import SetupItem from "./SetupItem.vue";

const FIRST_AVATAR = "renard";
const FIRST_AVATAR_COLOR = 0; // Original drawing swatch

const { t, locale } = useI18n();
const route = useRoute();
const router = useRouter();
const checking = ref(false);
const starting = ref(false);
const error = ref("");
const forceList = ref(false);
const firstChatDone = ref(false);
const hasMemoryPrefs = ref(false);
const firstChatGateReady = ref(false);
const updateInfo = ref(readUpdateStatus());
const updateBusy = ref(false);
const updateApplying = ref(false);
const updateError = ref("");
const updateLog = ref([]);
let updateJobId = "";
const piPackages = ref(null);
const piBusy = ref(false);
const piChecking = ref(false);
const piError = ref("");
const piLog = ref([]);
let piJobId = "";
const piItems = computed(() => piPackages.value?.items || []);
/** job kind → { id, state, log[] } */
const logs = reactive({});
let timer = 0;

const setup = computed(() => state.setup);
const showChecklist = computed(() => {
  if (route.name === "setup" || forceList.value) return true;
  // Home stays on screen while the status request is in flight.
  if (!setup.value) return false;
  return !setup.value.ready || (setup.value.checks || []).some((c) => c.status === "running");
});
const required = computed(() => (setup.value?.checks || []).filter((c) => c.required));
const optional = computed(() => (setup.value?.checks || []).filter((c) => !c.required));
const brokenOptional = computed(() => optional.value.filter((c) => c.status === "error"));
const canStartFirstChat = computed(() => setupReady());
/** Show the setup conversation only once we know memory is empty and nothing is waiting. */
const showFirstChatCta = computed(
  () => firstChatGateReady.value && !hasMemoryPrefs.value,
);
const canApplyUpdate = computed(() => {
  const u = updateInfo.value;
  return !!(u?.available && !u?.dirty && !u?.applying && u?.git !== false);
});
const showForceUpdate = computed(() => {
  const u = updateInfo.value;
  const err = String(updateError.value || "").toLowerCase();
  if (u?.dirty || u?.code === "dirty") return true;
  // Rewritten history with commits to take is a normal Update (it matches the tip).
  // Force stays for a diverged copy that has nothing new on the remote, or a failed fast-forward.
  if (u?.code === "diverged" && !u?.available) return true;
  return (
    err.includes("local changes") ||
    err.includes("fast-forward") ||
    err.includes("diverged")
  );
});
const showUpdateUi = computed(() => {
  const u = updateInfo.value;
  if (!u) return false;
  if (u.git === false || u.code === "no_git") return false;
  return true;
});
const updateNeedsAction = computed(() => {
  const u = updateInfo.value;
  if (!u) return false;
  if (updateApplying.value || updateLog.value.length) return true;
  if (u.code === "fetch_failed" || u.code === "diverged" || u.dirty) return true;
  if (u.available) return true;
  return false;
});
const updateUpToDate = computed(() => showUpdateUi.value && !updateNeedsAction.value);
const updateJump = computed(() => {
  const u = updateInfo.value;
  if (!u?.available) return "";
  const latest = String(u.latest_version || "");
  const current = String(u.version || "");
  if (!latest || latest === current) return "";
  return latest;
});
const updateNote = computed(() => {
  const u = updateInfo.value;
  if (!u || updateUpToDate.value) return "";
  if (u.code === "fetch_failed") return t("update.fetchFailed", { detail: u.message || "" });
  if (u.code === "diverged" && u.available) return t("update.rewritten");
  if (u.dirty && u.available) return t("update.dirty", { channel: u.channel, n: u.behind || 0 });
  if (u.available && !updateJump.value) {
    return t("update.available", { channel: u.channel, n: u.behind || 0 });
  }
  return "";
});

const updateSummary = computed(() => {
  const u = updateInfo.value;
  if (!u) return "";
  if (u.code === "fetch_failed") return t("update.fetchFailed", { detail: u.message || "" });
  if (u.code === "diverged" && u.available) return t("update.rewritten");
  if (u.dirty && u.available) return t("update.dirty", { channel: u.channel, n: u.behind || 0 });
  if (u.available) {
    return t("update.available", {
      channel: u.channel,
      n: u.behind || 0,
    });
  }
  return t("update.upToDate", { channel: u.channel });
});

const updateTitle = computed(() => {
  const u = updateInfo.value;
  if (!u) return "";
  if (u.code === "fetch_failed") return t("update.fetchFailedTitle");
  if (u.code === "diverged") return t("update.divergedTitle");
  if (u.dirty) return t("update.dirtyTitle");
  if (u.available) return t("update.availableTitle");
  return updateSummary.value;
});

const updateMeta = computed(() => {
  const u = updateInfo.value;
  if (!u) return "";
  if (u.code === "fetch_failed") return (u.message || "").trim();
  if (u.code === "diverged") return t("update.divergedMeta", { channel: u.channel });
  if (u.dirty) {
    return t("update.dirtyMeta", { channel: u.channel });
  }
  if (u.available) {
    return t("update.availableMeta", { channel: u.channel });
  }
  return "";
});

async function loadPiPackages(force = false) {
  piChecking.value = true;
  try {
    const data = force ? await api.checkPiPackages() : await api.piPackages(false);
    piPackages.value = data;
    piError.value = "";
  } catch (e) {
    piError.value = e.message || String(e);
  } finally {
    piChecking.value = false;
  }
}

async function runPiUpdates(ids) {
  const wanted = (Array.isArray(ids) ? ids : []).filter(Boolean);
  if (piBusy.value || !wanted.length) return;
  piBusy.value = true;
  piError.value = "";
  piLog.value = [];
  try {
    const job = await api.applyPiPackages(wanted);
    piJobId = job.id;
    piLog.value = job.log || [];
    pollPiJob();
  } catch (e) {
    piError.value = e.message || String(e);
    piBusy.value = false;
  }
}

async function pollPiJob() {
  if (!piJobId) return;
  try {
    const job = await api.getJob(piJobId);
    piLog.value = job.log || [];
    if (job.state === "pending" || job.state === "running") {
      setTimeout(pollPiJob, 1200);
      return;
    }
    piBusy.value = false;
    const failed = job.state === "failed" ? job.error || t("piPackages.failed") : "";
    await loadPiPackages(true);
    if (failed) piError.value = failed;
  } catch {
    setTimeout(pollPiJob, 2000);
  }
}

async function loadUpdate(force = false) {
  if (!force) {
    const cached = readUpdateStatus();
    if (cached) {
      updateInfo.value = cached;
      return;
    }
  }
  try {
    const next = force ? await api.checkUpdate() : await api.updateStatus(false);
    updateInfo.value = next;
    updateError.value = "";
    writeUpdateStatus(next);
  } catch (e) {
    updateError.value = e.message || String(e);
  }
}

async function forceCheckUpdate() {
  if (updateBusy.value) return;
  updateBusy.value = true;
  updateError.value = "";
  try {
    await loadUpdate(true);
  } finally {
    updateBusy.value = false;
  }
}

async function runApplyUpdate() {
  if (!canApplyUpdate.value || updateBusy.value) return;
  await startUpdate(false);
}

async function runForceUpdate() {
  if (updateBusy.value) return;
  await startUpdate(true);
}

async function startUpdate(force) {
  updateBusy.value = true;
  updateApplying.value = true;
  updateError.value = "";
  updateLog.value = [];
  try {
    const job = await api.applyUpdate(force);
    updateJobId = job.id;
    updateLog.value = job.log || [];
    pollUpdateJob();
  } catch (e) {
    // Apply may return just as the process dies for restart — treat as success path.
    if (isNetworkDrop(e)) {
      scheduleReloadAfterUpdate();
      return;
    }
    updateError.value = e.message || String(e);
    updateBusy.value = false;
    updateApplying.value = false;
  }
}

function isNetworkDrop(err) {
  const msg = String(err?.message || err || "").toLowerCase();
  return (
    err?.name === "TypeError" ||
    msg.includes("networkerror") ||
    msg.includes("failed to fetch") ||
    msg.includes("load failed") ||
    msg.includes("network request failed")
  );
}

function scheduleReloadAfterUpdate() {
  forgetUpdateStatus();
  updateError.value = "";
  updateBusy.value = true;
  updateApplying.value = true;
  const note = t("update.restarting");
  if (!updateLog.value.includes(note)) updateLog.value = [...updateLog.value, note];
  const started = Date.now();
  const tick = async () => {
    if (Date.now() - started > 90000) {
      window.location.reload();
      return;
    }
    try {
      const res = await fetch("/api/v1/health", {
        credentials: "include",
        cache: "no-store",
      });
      // Any response means the hub is back (health is open).
      if (res.ok || res.status === 401 || res.status === 403) {
        window.location.reload();
        return;
      }
    } catch {
      /* still restarting */
    }
    setTimeout(tick, 1500);
  };
  setTimeout(tick, 2000);
}

async function pollUpdateJob() {
  if (!updateJobId) return;
  try {
    const job = await api.getJob(updateJobId);
    updateLog.value = job.log || [];
    if (job.state === "pending" || job.state === "running") {
      setTimeout(pollUpdateJob, 1200);
      return;
    }
    if (job.state === "failed") {
      updateApplying.value = false;
      updateBusy.value = false;
      updateError.value = job.error || t("update.failed");
      await loadUpdate(true);
      return;
    }
    // done → systemd restart drops the socket; reload when /health answers again.
    scheduleReloadAfterUpdate();
  } catch (e) {
    if (updateApplying.value || isNetworkDrop(e)) {
      scheduleReloadAfterUpdate();
      return;
    }
    setTimeout(pollUpdateJob, 2000);
  }
}

async function refreshFirstChatGate() {
  try {
    const [settings, memory, pendingCount] = await Promise.all([
      api.settings(),
      api.memoryEntries(),
      api.memoryPendingCount(),
    ]);
    const entries = Array.isArray(memory) ? memory : memory?.entries || [];
    const waiting = Number(pendingCount?.count) || 0;
    // Saved facts or a proposal still waiting both mean preferences already exist.
    hasMemoryPrefs.value = entries.length > 0 || waiting > 0;
    const pending = settings?.first_chat_prefs_pending;
    state.firstChatPrefsPending =
      typeof pending === "string" && pending.trim() ? pending.trim() : null;
    firstChatDone.value = !!settings?.first_chat_done;

    // Empty memory: clear stale onboarding flags so the CTA is usable again.
    if (!hasMemoryPrefs.value) {
      const patch = {};
      if (state.firstChatPrefsPending) {
        state.firstChatPrefsPending = null;
        patch.first_chat_prefs_pending = null;
      }
      if (firstChatDone.value) {
        firstChatDone.value = false;
        patch.first_chat_done = false;
      }
      if (settings?.first_chat_onboarding) {
        patch.first_chat_onboarding = false;
      }
      if (Object.keys(patch).length) {
        try {
          await api.putSettings(patch);
        } catch {
          /* CTA already shown from local state */
        }
      }
      return;
    }
    // Prefs largely saved → end silent auto-memory mode.
    const keys = new Set(entries.map((e) => e?.key).filter(Boolean));
    if (
      settings?.first_chat_onboarding &&
      keys.has("preferred_name") &&
      (keys.has("work_style") || keys.has("notify_preference"))
    ) {
      try {
        await api.putSettings({ first_chat_onboarding: false });
      } catch {
        /* ignore */
      }
    }

    // Language saved but prefs never sent (e.g. Deutsch) → resume phase 2.
    if (state.firstChatPrefsPending) {
      await resumeFirstChatPrefsIfStuck();
    }
  } catch {
    /* keep last known gate */
  } finally {
    firstChatGateReady.value = true;
  }
}

async function recheck() {
  checking.value = true;
  error.value = "";
  try {
    await refreshSetup(true);
  } finally {
    checking.value = false;
  }
}

async function clearOtherManagers(keepName) {
  for (const bot of state.bots) {
    if (!bot.is_manager) continue;
    if (keepName && bot.name === keepName) continue;
    try {
      await api.patchBot(bot.name, { is_manager: false });
      bot.is_manager = false;
    } catch {
      /* continue — create/patch may still fail and surface the error */
    }
  }
}

async function applyFirstBotProfile(bot) {
  const patch = {};
  if (bot.memory_access === false) patch.memory_access = true;
  if (!bot.is_manager) patch.is_manager = true;
  if (bot.avatar !== FIRST_AVATAR) patch.avatar = FIRST_AVATAR;
  if (Number(bot.avatar_color) !== FIRST_AVATAR_COLOR) {
    patch.avatar_color = FIRST_AVATAR_COLOR;
  }
  if (!Object.keys(patch).length) return bot;
  if (patch.is_manager) await clearOtherManagers(bot.name);
  const saved = await api.patchBot(bot.name, patch);
  Object.assign(bot, saved);
  return bot;
}

async function ensureBot() {
  const wanted = t("setup.firstBotName").trim().toLowerCase();
  const existing = state.bots.find((b) => {
    const name = String(b.name || "").toLowerCase();
    const label = String(b.label || "").toLowerCase();
    return name === "assistant" || name === wanted || label === wanted;
  });
  if (existing) {
    try {
      return await applyFirstBotProfile(existing);
    } catch {
      return existing;
    }
  }
  let model = "";
  try {
    const models = await api.piModels();
    model = models[0]?.ref || "";
  } catch {
    /* keep empty — server picks a default when possible */
  }
  await clearOtherManagers("");
  const bot = await api.createBot({
    name: t("setup.firstBotName"),
    internet: true,
    memory_access: true,
    is_manager: true,
    model: model || null,
    avatar: FIRST_AVATAR,
    avatar_color: FIRST_AVATAR_COLOR,
  });
  await refreshBots();
  return state.bots.find((b) => b.name === bot.name) || bot;
}

function rememberMessage(botName, saved) {
  if (!saved?.id) return;
  if (!state.messages[botName]) state.messages[botName] = [];
  dropOptimisticDupes(botName, saved);
  if (!state.messages[botName].some((m) => m.id === saved.id)) {
    state.messages[botName].push(saved);
  }
}

async function startFirstChat() {
  if (!showFirstChatCta.value || !canStartFirstChat.value || starting.value) return;
  starting.value = true;
  error.value = "";
  try {
    const bot = await ensureBot();
    const loc = locale.value === "fr" ? "fr" : "en";
    const visible = rawMessage("setup.firstChatVisible", loc);
    // Raw: language script contains `|` between choices — `t()` would plural-slice it.
    const script = rawMessage("setup.firstChatLanguageScript", loc);
    // Optimistic bubble + open the thread before HTTP returns so the message
    // never looks stuck in the composer while the agent is already thinking.
    const tempId = `tmp-first-${Date.now()}`;
    rememberMessage(bot.name, {
      id: tempId,
      bot: bot.name,
      conversation_id: "main",
      role: "user",
      content: visible,
      attachments: [],
      meta: {},
      created_at: new Date().toISOString(),
    });
    state.currentBot = bot.name;
    state.tab = "discussion";
    forceList.value = false;
    state.firstChatPrefsPending = bot.name;
    try {
      // Do not set first_chat_done yet — empty memory must keep the CTA available
      // if the user abandons before any preference is saved.
      await api.putSettings({
        first_chat_prefs_pending: bot.name,
        first_chat_onboarding: true,
      });
    } catch {
      /* pending is already in local state */
    }
    await router.push(botPath(bot.name, "discussion"));
    const saved = await api.sendMessage(bot.name, visible, [], { prompt: script });
    const list = state.messages[bot.name] || [];
    for (let i = list.length - 1; i >= 0; i--) {
      const m = list[i];
      if (m?.id === tempId || (isOptimisticMessageId(m?.id) && m.content === visible)) {
        list.splice(i, 1);
      }
    }
    if (saved?.id) rememberMessage(bot.name, saved);
    await refreshFirstChatPrefsPending();
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    starting.value = false;
  }
}

function itemLog(check) {
  return logs[check?.action?.job] || logs[check?.id] || null;
}

async function runJob(kind) {
  error.value = "";
  try {
    const job = await api.startSetupJob(kind);
    logs[kind] = { id: job.id, state: job.state, log: job.log || [] };
    poll();
  } catch (e) {
    error.value = e.message;
  }
}

function attachRunning() {
  // Jobs started elsewhere (other tab / before reload) → follow their log too.
  for (const [kind, id] of Object.entries(setup.value?.jobs || {})) {
    if (!logs[kind] || logs[kind].id !== id) logs[kind] = { id, state: "running", log: [] };
  }
}

const COMPANION_BG_ID = "companion-bg";

/** Background companion builds (serve startup) have no setup.jobs row — tail build.log via API. */
async function pollCompanionBuildLog() {
  const row = (setup.value?.checks || []).find((c) => c.id === "companion");
  const tracked = logs.companion;
  const need =
    row?.status === "running" ||
    tracked?.state === "pending" ||
    tracked?.state === "running" ||
    (tracked?.log?.length && tracked?.state === "failed");
  if (!need) return;
  // Real setup job (UUID) already polled via getJob — don't overwrite.
  if (tracked && tracked.id && tracked.id !== COMPANION_BG_ID) return;
  try {
    const st = await api.companionBuild();
    const building = st.state === "building";
    logs.companion = {
      id: COMPANION_BG_ID,
      state: building ? "running" : st.state === "failed" || st.error ? "failed" : "done",
      log: st.log || [],
      error: st.error || "",
    };
    if (!building && row?.status === "running") await refreshSetup(true);
  } catch {
    /* retry next tick */
  }
}

async function poll() {
  clearTimeout(timer);
  attachRunning();
  const active = Object.entries(logs).filter(([, j]) => j.state === "pending" || j.state === "running");
  for (const [kind, j] of active) {
    if (j.id === COMPANION_BG_ID) continue;
    try {
      const job = await api.getJob(j.id);
      logs[kind] = { id: job.id, state: job.state, log: job.log || [], error: job.error };
      if (job.state === "done" || job.state === "failed") await refreshSetup(true);
    } catch {
      /* retry next tick */
    }
  }
  await pollCompanionBuildLog();
  const still =
    Object.values(logs).some((j) => j.state === "pending" || j.state === "running") ||
    (setup.value?.checks || []).some((c) => c.id === "companion" && c.status === "running");
  timer = setTimeout(poll, still ? 1200 : 10000);
  if (!still && showChecklist.value) refreshSetup();
}

watch(() => setup.value?.jobs, () => attachRunning(), { deep: true });

watch(
  () => setup.value?.ready,
  (ready, prev) => {
    // Keep the checklist open when the last required item flips to OK,
    // so the first-chat button is still on screen.
    if (ready && prev === false) forceList.value = true;
  },
);

onMounted(async () => {
  await Promise.all([
    refreshSetup(route.name === "setup"),
    refreshFirstChatGate(),
    loadUpdate(false),
    loadPiPackages(false),
  ]);
  poll();
});
onUnmounted(() => clearTimeout(timer));
</script>
