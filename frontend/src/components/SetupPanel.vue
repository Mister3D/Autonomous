<template>
  <div class="setup-panel">
    <img class="setup-logo" src="/logo.png" :alt="t('brand')" />
    <template v-if="!setup">
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
        <SetupItem v-for="c in required" :key="c.id" :check="c" :log="logs[c.action?.job]" @job="runJob" />
      </ul>
      <h3 class="setup-section">{{ t("setup.optional") }}</h3>
      <ul class="setup-list">
        <SetupItem v-for="c in optional" :key="c.id" :check="c" :log="logs[c.action?.job]" @job="runJob" />
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
      <div v-if="brokenOptional.length" class="setup-banner" role="status">
        {{ t("setup.optionalBroken", { items: brokenOptional.map((c) => t(c.label)).join(", ") }) }}
        <router-link to="/setup">{{ t("setup.open") }}</router-link>
      </div>
      <div v-if="showFirstChatCta" class="setup-first-chat setup-first-chat-home">
        <button
          class="btn primary"
          type="button"
          :disabled="starting"
          @click="startFirstChat"
        >
          {{ starting ? t("setup.firstChatBusy") : t("setup.firstChat") }}
        </button>
        <p class="hint">{{ t("setup.firstChatHintReady") }}</p>
      </div>
      <p v-if="error" class="vault-error">{{ error }}</p>
      <router-link class="setup-link" to="/setup">{{ t("setup.link") }}</router-link>
    </template>
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
/** job kind → { id, state, log[] } */
const logs = reactive({});
let timer = 0;

const setup = computed(() => state.setup);
const showChecklist = computed(
  () => route.name === "setup" || forceList.value || !setup.value?.ready ||
    (setup.value?.checks || []).some((c) => c.status === "running"),
);
const required = computed(() => (setup.value?.checks || []).filter((c) => c.required));
const optional = computed(() => (setup.value?.checks || []).filter((c) => !c.required));
const brokenOptional = computed(() => optional.value.filter((c) => c.status === "error"));
const canStartFirstChat = computed(() => setupReady());
/** Only rule: 0 shared-memory entries → show the setup conversation CTA. */
const showFirstChatCta = computed(() => !hasMemoryPrefs.value);

async function refreshFirstChatGate() {
  try {
    const [settings, memory] = await Promise.all([
      api.settings(),
      api.memoryEntries(),
    ]);
    const entries = Array.isArray(memory) ? memory : memory?.entries || [];
    hasMemoryPrefs.value = entries.length > 0;
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

async function poll() {
  clearTimeout(timer);
  attachRunning();
  const active = Object.entries(logs).filter(([, j]) => j.state === "pending" || j.state === "running");
  for (const [kind, j] of active) {
    try {
      const job = await api.getJob(j.id);
      logs[kind] = { id: job.id, state: job.state, log: job.log || [], error: job.error };
      if (job.state === "done" || job.state === "failed") await refreshSetup(true);
    } catch {
      /* retry next tick */
    }
  }
  const still = Object.values(logs).some((j) => j.state === "pending" || j.state === "running");
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
  await Promise.all([refreshSetup(route.name === "setup"), refreshFirstChatGate()]);
  poll();
});
onUnmounted(() => clearTimeout(timer));
</script>
