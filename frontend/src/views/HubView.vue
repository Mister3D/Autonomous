<template>
  <div
    class="app-shell"
    :class="{
      'is-mobile-list': mobileListMode,
      'is-mobile-chat': mobileChatMode,
      'is-mobile-setup': mobileSetupMode,
      'is-mobile-home': mobileHomeMode,
    }"
  >
    <aside class="sidebar">
      <div class="rail-top">
        <router-link
          class="rail-logo"
          to="/"
          :title="t('brand')"
          :aria-label="t('brand')"
          @click="onRailLogoClick"
        >
          <img src="/favicon-192.png" alt="" />
        </router-link>
        <button
          class="settings-orb"
          type="button"
          :aria-label="t('search.label')"
          :aria-expanded="searchOpen"
          @click="toggleSearch"
        >
          <UiIcon name="search" />
        </button>
        <button
          class="settings-orb"
          type="button"
          :aria-label="t('nav.create')"
          :title="canCreate ? t('nav.create') : t('setup.createBlocked')"
          :disabled="!canCreate"
          :aria-disabled="!canCreate"
          @click="openCreate"
        >
          <UiIcon name="plus" />
        </button>
      </div>
      <input
        v-if="searchOpen"
        ref="searchInput"
        v-model="query"
        class="rail-search"
        type="search"
        :placeholder="t('search.placeholder')"
        @keydown.esc="closeSearch"
        @keydown.enter.prevent="runSearch(true)"
      />

      <div v-if="searchOpen && query.trim()" class="rail-search-panel">
        <p v-if="searchLoading" class="rail-search-status">{{ t("search.searching") }}</p>
        <p v-else-if="searchError" class="rail-search-status error">{{ searchError }}</p>
        <template v-else>
          <p v-if="msgHits.length" class="rail-search-heading">
            {{ t("search.messagesHeading") }}
            <span class="rail-search-mode">{{ searchModeLabel }}</span>
          </p>
          <ul v-if="msgHits.length" class="msg-hit-list">
            <li v-for="h in msgHits" :key="`${h.bot}-${h.message_id}`">
              <button type="button" @click="openMessageHit(h)">
                <span class="msg-hit-meta">
                  <span class="msg-hit-bot">{{ h.bot_label || h.bot }}</span>
                  <span class="msg-hit-role">{{ h.role }}</span>
                </span>
                <span class="msg-hit-snippet">{{ h.snippet }}</span>
              </button>
            </li>
          </ul>
          <p v-else-if="query.trim().length >= 2" class="rail-search-status">
            {{ t("search.noMessages") }}
          </p>
          <p
            v-if="railManagers.length || railWorkers.length"
            class="rail-search-heading"
          >
            {{ t("search.botsHeading") }}
          </p>
        </template>
      </div>

      <div v-if="railManagers.length" class="rail-managers">
        <button
          v-for="b in railManagers"
          :key="b.name"
          type="button"
          class="rail-manager"
          :class="{
            active: state.currentBot === b.name,
            waiting: b.status === 'waiting',
          }"
          :title="b.label || b.name"
          @click="selectBot(b.name)"
        >
          <BotAvatar :bot="b" size="md" />
          <span class="rail-manager-name">{{ b.label || b.name }}</span>
        </button>
      </div>

      <ul class="bot-list">
        <li v-if="!railManagers.length && !railWorkers.length" class="rail-empty">
          {{ t("nav.bots") }}
        </li>
        <li v-for="b in railWorkers" :key="b.name">
          <button
            type="button"
            :class="{
              active: state.currentBot === b.name,
              waiting: b.status === 'waiting',
            }"
            @click="selectBot(b.name)"
          >
            <BotAvatar :bot="b" size="sm" />
            <span class="bot-copy">
              <span class="bot-name">{{ b.label || b.name }}</span>
              <span class="bot-preview">{{ previewOf(b) }}</span>
            </span>
          </button>
        </li>
      </ul>

      <div class="rail-foot">
        <SettingsMenu />
      </div>
    </aside>

    <div
      class="stage"
      :class="{
        'with-inspector': !!bot && !inspectorCollapsed,
        'inspector-collapsed': !!bot && inspectorCollapsed,
      }"
    >
      <section class="main">
        <template v-if="bot">
          <div class="stage-toolbar">
            <button
              v-if="mobileLayout"
              type="button"
              class="icon-btn mobile-back"
              :aria-label="t('nav.back')"
              :title="t('nav.back')"
              @click="backToBotList"
            >
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M15 6 9 12l6 6" />
              </svg>
            </button>
            <button
              v-if="!mobileLayout"
              type="button"
              class="split-toggle"
              :class="{ active: splitWanted }"
              :aria-pressed="splitWanted"
              :aria-label="splitTitle"
              :title="splitTitle"
              @click="toggleSplit"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
                <rect x="3.5" y="5" width="7" height="14" rx="1.4" />
                <rect x="13.5" y="5" width="7" height="14" rx="1.4" />
              </svg>
            </button>
            <div v-if="splitActive" class="split-pickers">
              <label class="split-picker">
                <select
                  :value="leftPane"
                  :aria-label="t('tabs.sideLeft')"
                  @change="onPickSide('left', $event)"
                >
                  <option v-for="opt in paneOptions" :key="opt.id" :value="opt.id">
                    {{ opt.label }}
                  </option>
                </select>
              </label>
              <button
                type="button"
                class="split-swap"
                :title="t('tabs.splitSwap')"
                :aria-label="t('tabs.splitSwap')"
                @click="swapSides"
              >
                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
                  <path d="M7 7h11M15 4l3 3-3 3" />
                  <path d="M17 17H6M9 14l-3 3 3 3" />
                </svg>
              </button>
              <label class="split-picker">
                <select
                  :value="rightPane"
                  :aria-label="t('tabs.sideRight')"
                  @change="onPickSide('right', $event)"
                >
                  <option v-for="opt in paneOptions" :key="`r-${opt.id}`" :value="opt.id">
                    {{ opt.label }}
                  </option>
                </select>
              </label>
            </div>
            <div v-else class="stage-tabs seg" role="tablist">
              <button
                type="button"
                role="tab"
                :class="{ active: state.tab === 'discussion' }"
                :aria-selected="state.tab === 'discussion'"
                @click="selectTab('discussion')"
              >
                {{ t("tabs.conversation") }}
              </button>
              <button
                type="button"
                role="tab"
                :class="{ active: state.tab === 'terminal', locked: !terminalReady }"
                :aria-selected="state.tab === 'terminal'"
                :title="terminalReady ? undefined : t('tabs.lockedHint')"
                @click="selectTab('terminal')"
              >
                {{ t("tabs.terminal") }}
              </button>
              <button
                type="button"
                role="tab"
                :class="{ active: state.tab === 'screen', locked: !screenReady }"
                :aria-selected="state.tab === 'screen'"
                :title="screenReady ? undefined : t('tabs.lockedHint')"
                @click="selectTab('screen')"
              >
                {{ t("tabs.screen") }}
              </button>
            </div>
            <button
              class="icon-btn inspector-toggle"
              type="button"
              :aria-label="inspectorToggleLabel"
              :title="inspectorToggleLabel"
              :aria-expanded="inspectorToggleExpanded"
              @click="onInspectorToggle"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
                <rect x="4" y="5" width="16" height="14" rx="2" />
                <path d="M14 5v14" />
              </svg>
            </button>
          </div>

          <div class="stage-body" :class="{ 'is-split': splitActive }" :style="splitStyle">
            <ChatPane
              v-show="paneShown('discussion')"
              :class="paneSideClass('discussion')"
              :bot="bot"
            />
            <div
              v-if="splitActive"
              class="split-handle"
              role="separator"
              aria-orientation="vertical"
              tabindex="0"
              :aria-label="t('tabs.splitResize')"
              :aria-valuemin="28"
              :aria-valuemax="62"
              :aria-valuenow="Math.round(splitRatio * 100)"
              @pointerdown="onSplitDrag"
              @keydown="onSplitKey"
            />
            <TerminalPane
              v-show="paneShown('terminal')"
              :class="paneSideClass('terminal')"
              :bot="bot"
              :active="paneShown('terminal')"
            />
            <!-- Keep ScreenPane mounted so the desk/noVNC session stays alive off-tab. -->
            <ScreenPane
              v-show="paneShown('screen')"
              :class="paneSideClass('screen')"
              :bot="bot"
              :active="paneShown('screen')"
            />
          </div>

          <CreateDeskModal
            v-if="deskCreateOpen"
            :bot="bot"
            @close="onDeskModalClose"
            @done="onDeskCreated"
          />
        </template>
        <div v-else class="empty brand-empty">
          <button
            v-if="mobileHomeMode"
            type="button"
            class="icon-btn mobile-back mobile-home-back"
            :aria-label="t('nav.back')"
            :title="t('nav.back')"
            @click="backToBotList"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M15 6 9 12l6 6" />
            </svg>
          </button>
          <SetupPanel />
        </div>
      </section>

      <aside v-if="bot" class="inspector" :class="{ 'is-open': state.inspectorOpen }">
        <button
          type="button"
          class="icon-btn inspector-collapse"
          :aria-label="t('inspector.collapse')"
          :title="t('inspector.collapse')"
          @click="collapseInspector"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
        <header class="inspector-head">
          <BotAvatar
            :bot="bot"
            size="lg"
            editable
            :edit-title="t('avatar.editHint')"
            @edit="avatarEditOpen = true"
          />
          <form
            v-if="renaming"
            class="inspector-rename"
            @submit.prevent="commitRename"
          >
            <input
              ref="renameInput"
              v-model="renameDraft"
              class="inspector-rename-input"
              type="text"
              maxlength="64"
              :aria-label="t('inspector.rename')"
              :disabled="renameBusy"
              @keydown.esc.prevent="cancelRename"
              @blur="commitRename"
            />
          </form>
          <button
            v-else
            type="button"
            class="inspector-title"
            :title="t('inspector.renameHint')"
            @click="startRename"
          >
            <h2>{{ bot.label || bot.name }}</h2>
          </button>
          <p v-if="renameError" class="inspector-rename-error">{{ renameError }}</p>
        </header>
        <nav class="inspector-tabs">
          <button type="button" :class="{ active: state.panel === 'details' }" @click="state.panel = 'details'">
            {{ t("panel.details") }}
          </button>
          <button type="button" :class="{ active: state.panel === 'events' }" @click="state.panel = 'events'">
            {{ t("panel.events") }}
          </button>
          <button type="button" :class="{ active: state.panel === 'library' }" @click="state.panel = 'library'">
            {{ t("panel.files") }}
          </button>
        </nav>
        <div class="inspector-body" :class="state.panel">
          <DetailsPane v-if="state.panel === 'details'" :bot="bot" />
          <EventsPane v-else-if="state.panel === 'events'" :bot="bot" />
          <LibraryPane v-else :bot="bot" />
        </div>
      </aside>
    </div>

    <CreateBotModal v-if="state.createOpen" />
    <AvatarEditModal
      v-if="avatarEditOpen && bot"
      :bot="bot"
      @close="avatarEditOpen = false"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { refreshFirstChatPrefsPending } from "../firstChatPrefs";
import {
  state,
  currentBotObj,
  isOptimisticMessageId,
  markBotRead,
  preferLiveStreamingMessage,
  refreshSetup,
  setupReady,
} from "../store";
import { api } from "../api";
import { botPath, normalizeTab } from "../router";
import ChatPane from "../components/ChatPane.vue";
import TerminalPane from "../components/TerminalPane.vue";
import ScreenPane from "../components/ScreenPane.vue";
import BotAvatar from "../components/BotAvatar.vue";
import DetailsPane from "../components/DetailsPane.vue";
import EventsPane from "../components/EventsPane.vue";
import LibraryPane from "../components/LibraryPane.vue";
import CreateBotModal from "../components/CreateBotModal.vue";
import SetupPanel from "../components/SetupPanel.vue";
import AvatarEditModal from "../components/AvatarEditModal.vue";
import CreateDeskModal from "../components/CreateDeskModal.vue";
import SettingsMenu from "../components/SettingsMenu.vue";
import UiIcon from "../components/ui/UiIcon.vue";

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const bot = computed(() => currentBotObj());
const avatarEditOpen = ref(false);
const renaming = ref(false);
const renameDraft = ref("");
const renameBusy = ref(false);
const renameError = ref("");
const renameInput = ref(null);
const query = ref("");
const searchOpen = ref(false);
const searchInput = ref(null);
const msgHits = ref([]);
const searchLoading = ref(false);
const searchError = ref("");
const searchMode = ref("");
const previewLoaded = new Set();
const deskCreateOpen = ref(false);
const pendingTab = ref(null);
const SPLIT_KEY = "autonomous.splitScreen";
const SPLIT_RATIO_KEY = "autonomous.splitScreenRatio";
const INSPECTOR_KEY = "autonomous.inspectorCollapsed";
const PANE_IDS = ["discussion", "terminal", "screen"];

function pairOrDefault(left, right) {
  if (!PANE_IDS.includes(left)) left = "discussion";
  if (!PANE_IDS.includes(right) || right === left) {
    right = PANE_IDS.find((id) => id !== left);
  }
  return { left, right };
}

function readSplitLayouts() {
  try {
    const raw = JSON.parse(localStorage.getItem(SPLIT_KEY) || "{}");
    const out = {};
    if (Array.isArray(raw)) {
      for (const name of raw) {
        if (typeof name === "string") {
          out[name] = { on: true, left: "discussion", right: "screen" };
        }
      }
      return out;
    }
    if (!raw || typeof raw !== "object") return out;
    for (const [name, val] of Object.entries(raw)) {
      if (!val || typeof val !== "object") continue;
      out[name] = { on: !!val.on, ...pairOrDefault(val.left, val.right) };
    }
    return out;
  } catch {
    return {};
  }
}

function readSplitRatio() {
  try {
    const n = Number(localStorage.getItem(SPLIT_RATIO_KEY));
    if (!Number.isFinite(n)) return 0.4;
    return Math.min(0.62, Math.max(0.28, n));
  } catch {
    return 0.4;
  }
}

function readInspectorCollapsed() {
  try {
    return localStorage.getItem(INSPECTOR_KEY) === "1";
  } catch {
    return false;
  }
}

function setInspectorCollapsed(on) {
  inspectorCollapsed.value = !!on;
  try {
    localStorage.setItem(INSPECTOR_KEY, on ? "1" : "0");
  } catch {
    /* preference stays in memory for this session */
  }
  nextTick(() => window.dispatchEvent(new Event("resize")));
}

function collapseInspector() {
  if (window.matchMedia("(max-width: 1080px)").matches) {
    state.inspectorOpen = false;
    return;
  }
  setInspectorCollapsed(true);
}

function onInspectorToggle() {
  if (window.matchMedia("(max-width: 1080px)").matches) {
    state.inspectorOpen = !state.inspectorOpen;
    return;
  }
  setInspectorCollapsed(false);
}

const inspectorToggleLabel = computed(() => {
  if (narrowLayout.value) {
    return state.inspectorOpen ? t("inspector.collapse") : t("inspector.expand");
  }
  return t("inspector.expand");
});

const inspectorToggleExpanded = computed(() =>
  narrowLayout.value ? state.inspectorOpen : false
);

/** Per bot: split off by default. When on, left/right are discussion | terminal | screen. */
const splitLayouts = ref(readSplitLayouts());
const splitRatio = ref(readSplitRatio());
const inspectorCollapsed = ref(readInspectorCollapsed());
const narrowLayout = ref(false);
const mobileLayout = ref(false);
let narrowMq = null;
let mobileMq = null;
const piBanner = computed(() => state.piStatus);
const canCreate = computed(() => setupReady());

/** Mobile master–detail: list XOR conversation XOR home (logo) / setup. */
const mobileShowHome = ref(false);
const mobileChatMode = computed(() => mobileLayout.value && !!bot.value);
const mobileSetupMode = computed(
  () => mobileLayout.value && !bot.value && !canCreate.value
);
const mobileHomeMode = computed(
  () =>
    mobileLayout.value &&
    !bot.value &&
    canCreate.value &&
    mobileShowHome.value
);
const mobileListMode = computed(
  () =>
    mobileLayout.value &&
    !bot.value &&
    canCreate.value &&
    !mobileShowHome.value
);

/** Bot creation stays locked until the setup checklist on / is complete. */
function openCreate() {
  if (!canCreate.value) {
    router.push("/");
    return;
  }
  state.createOpen = true;
}
refreshSetup();
refreshFirstChatPrefsPending();
let applyingRoute = false;
let searchTimer = null;
let searchSeq = 0;

const searchModeLabel = computed(() => {
  const m = searchMode.value;
  if (m === "nl" || m === "nl_llm" || m === "nl_semantic") return t("search.modeNl");
  if (m === "lexical") return t("search.modeLexical");
  return "";
});

async function startRename() {
  if (!bot.value || renameBusy.value) return;
  renaming.value = true;
  renameDraft.value = bot.value.label || bot.value.name || "";
  renameError.value = "";
  await nextTick();
  renameInput.value?.focus();
  renameInput.value?.select();
}

function cancelRename() {
  renaming.value = false;
  renameError.value = "";
  renameBusy.value = false;
}

async function commitRename() {
  if (!renaming.value || renameBusy.value) return;
  const b = bot.value;
  if (!b) {
    cancelRename();
    return;
  }
  const next = renameDraft.value.trim();
  const prev = (b.label || b.name || "").trim();
  if (!next || next === prev) {
    cancelRename();
    return;
  }
  renameBusy.value = true;
  renameError.value = "";
  try {
    const updated = await api.patchBot(b.name, { label: next });
    const i = state.bots.findIndex((x) => x.name === b.name);
    if (i >= 0) state.bots[i] = { ...state.bots[i], ...updated };
    renaming.value = false;
  } catch (e) {
    renameError.value = e.message || String(e);
    await nextTick();
    renameInput.value?.focus();
    renameInput.value?.select();
  } finally {
    renameBusy.value = false;
  }
}

watch(
  () => bot.value?.name,
  () => {
    if (renaming.value) cancelRename();
  }
);

function goBot(name, tab = "discussion") {
  const path = botPath(name, tab);
  if (route.fullPath !== path) router.replace(path);
}

const terminalReady = computed(() => {
  const b = bot.value;
  if (!b) return false;
  if (b.capability === "terminal" || b.capability === "screen") return true;
  const st = b.desk?.state;
  return st === "creating" || st === "running" || st === "sleeping";
});

const screenReady = computed(() => {
  const b = bot.value;
  if (!b) return false;
  const desk = b.desk || {};
  if (desk.state === "creating") return true;
  return !!desk.vnc_port;
});

function layoutOf(name) {
  if (!name) return { on: false, left: "discussion", right: "screen" };
  return splitLayouts.value[name] || { on: false, left: "discussion", right: "screen" };
}

const splitWanted = computed(() => layoutOf(bot.value?.name).on);

/** Opt-in. Each side is chosen independently; single-pane tabs stay the default.
 *  Split is desktop-only — on mobile we always show one pane. */
const splitActive = computed(() => splitWanted.value && !mobileLayout.value);

const leftPane = computed(() => layoutOf(bot.value?.name).left);
const rightPane = computed(() => layoutOf(bot.value?.name).right);

const paneOptions = computed(() => [
  { id: "discussion", label: t("tabs.conversation") },
  { id: "terminal", label: t("tabs.terminal") },
  { id: "screen", label: t("tabs.screen") },
]);

const splitStyle = computed(() =>
  splitActive.value
    ? { "--split-screen": `${(splitRatio.value * 100).toFixed(2)}%` }
    : undefined
);

const splitTitle = computed(() =>
  splitWanted.value ? t("tabs.splitOff") : t("tabs.splitOn")
);

function paneShown(id) {
  if (splitActive.value) return leftPane.value === id || rightPane.value === id;
  return state.tab === id;
}

function paneSideClass(id) {
  if (!splitActive.value) return "";
  if (leftPane.value === id) return "pane-left";
  if (rightPane.value === id) return "pane-right";
  return "";
}

function saveLayout(name, layout) {
  if (!name) return;
  splitLayouts.value = { ...splitLayouts.value, [name]: layout };
  try {
    localStorage.setItem(SPLIT_KEY, JSON.stringify(splitLayouts.value));
  } catch {
    /* preference stays in memory for this session */
  }
}

function companionPane(current) {
  if (current !== "discussion") return "discussion";
  if (screenReady.value) return "screen";
  if (terminalReady.value) return "terminal";
  return "screen";
}

function persistSplitRatio() {
  try {
    localStorage.setItem(SPLIT_RATIO_KEY, String(splitRatio.value));
  } catch {
    /* ignore */
  }
}

function toggleSplit() {
  const name = state.currentBot;
  if (!name) return;
  const cur = layoutOf(name);
  if (cur.on) {
    saveLayout(name, { ...cur, on: false });
    return;
  }
  const left = PANE_IDS.includes(state.tab) ? state.tab : "discussion";
  saveLayout(name, { on: true, ...pairOrDefault(left, companionPane(left)) });
  nextTick(() => window.dispatchEvent(new Event("resize")));
}

function onPickSide(side, ev) {
  const name = state.currentBot;
  const value = ev?.target?.value;
  if (!name || !PANE_IDS.includes(value)) return;
  const cur = layoutOf(name);
  let left = cur.left;
  let right = cur.right;
  if (side === "left") {
    if (value === right) right = left;
    left = value;
  } else {
    if (value === left) left = right;
    right = value;
  }
  const pair = pairOrDefault(left, right);
  saveLayout(name, { on: true, ...pair });
  if (state.tab !== pair.left) {
    state.tab = pair.left;
    goBot(name, pair.left);
  }
  nextTick(() => window.dispatchEvent(new Event("resize")));
}

function swapSides() {
  const name = state.currentBot;
  if (!name) return;
  const cur = layoutOf(name);
  onPickSide("left", { target: { value: cur.right } });
}

function clampSplitRatio(ratio) {
  return Math.min(0.62, Math.max(0.28, ratio));
}

function onSplitDrag(ev) {
  if (ev.button != null && ev.button !== 0) return;
  const body = ev.currentTarget?.parentElement;
  if (!body) return;
  ev.preventDefault();
  const rect = body.getBoundingClientRect();
  let resizeTick = 0;
  const move = (e) => {
    if (!rect.width) return;
    splitRatio.value = clampSplitRatio((rect.right - e.clientX) / rect.width);
    const now = Date.now();
    if (now - resizeTick > 80) {
      resizeTick = now;
      window.dispatchEvent(new Event("resize"));
    }
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    persistSplitRatio();
    window.dispatchEvent(new Event("resize"));
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function onSplitKey(ev) {
  if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
  ev.preventDefault();
  const delta = ev.key === "ArrowRight" ? 0.03 : -0.03;
  splitRatio.value = clampSplitRatio(splitRatio.value + delta);
  persistSplitRatio();
}

function lastActivityAt(b) {
  let t = b.last_message_at || b.created_at || "";
  for (const m of state.messages[b.name] || []) {
    if (m.created_at && m.created_at > t) t = m.created_at;
  }
  return t;
}

function matchesQuery(b, q) {
  if (!q) return true;
  const blob = `${b.label || ""} ${b.name} ${previewOf(b)}`.toLowerCase();
  return blob.includes(q);
}

/** Managers featured above the list (mockup « Manager » en haut). */
const railManagers = computed(() => {
  const q = query.value.trim().toLowerCase();
  return state.bots
    .filter((b) => b.is_manager && matchesQuery(b, q))
    .sort((a, b) => (a.label || a.name).localeCompare(b.label || b.name, "fr"));
});

/** Autres bots dans la liste classique. */
const railWorkers = computed(() => {
  const q = query.value.trim().toLowerCase();
  return state.bots
    .filter((b) => !b.is_manager && matchesQuery(b, q))
    .sort((a, b) => lastActivityAt(b).localeCompare(lastActivityAt(a)));
});

/** Compat recherche / anciens usages. */
const visibleBots = computed(() => [...railManagers.value, ...railWorkers.value]);

function previewOf(b) {
  const msgs = state.messages[b.name] || [];
  const last = [...msgs].reverse().find((m) => !m?.meta?.hidden_prompt);
  const raw = last ? last.content : "";
  return String(raw || "").replace(/\s+/g, " ").trim();
}

function selectBot(name) {
  mobileShowHome.value = false;
  state.currentBot = name;
  markBotRead(name);
  const layout = splitLayouts.value[name];
  // Mobile: always open the conversation first (no split).
  const tab =
    mobileLayout.value || !layout?.on ? "discussion" : layout.left;
  state.tab = tab;
  goBot(name, tab);
}

function backToBotList() {
  state.currentBot = null;
  state.inspectorOpen = false;
  mobileShowHome.value = false;
  if (route.fullPath !== "/") router.push("/");
}

/** Mobile: logo opens the brand/home pane (updates, tagline) — unreachable via the list alone. */
function onRailLogoClick(ev) {
  if (!mobileLayout.value) {
    mobileShowHome.value = false;
    return;
  }
  ev.preventDefault();
  state.currentBot = null;
  state.inspectorOpen = false;
  mobileShowHome.value = true;
  if (route.fullPath !== "/") router.push("/");
}

function selectTab(tab) {
  const name = state.currentBot;
  if (!name) return;
  if (tab === "discussion") {
    state.tab = "discussion";
    goBot(name, "discussion");
    return;
  }
  if (tab === "terminal" && !terminalReady.value) {
    openDeskCreate("terminal");
    return;
  }
  if (tab === "screen" && !screenReady.value) {
    openDeskCreate("screen");
    return;
  }
  state.tab = tab;
  goBot(name, tab);
}

function openDeskCreate(tab) {
  pendingTab.value = tab === "screen" ? "screen" : "terminal";
  deskCreateOpen.value = true;
}

function onDeskModalClose() {
  deskCreateOpen.value = false;
}

function onDeskCreated() {
  deskCreateOpen.value = false;
  state.deskAuthRequest = null;
  const wanted = pendingTab.value;
  pendingTab.value = null;
  const name = state.currentBot;
  let tab = "discussion";
  if (wanted === "screen" && screenReady.value) tab = "screen";
  else if (terminalReady.value) tab = "terminal";
  state.tab = tab;
  if (name) goBot(name, tab);
}

function applyRoute() {
  if (route.name !== "bot" && route.name !== "hub") return;
  applyingRoute = true;
  try {
    const name = route.params.name ? String(route.params.name) : null;
    let tab = normalizeTab(route.params.tab);
    if (name && !state.bots.some((b) => b.name === name)) {
      const next = state.bots[0]?.name || null;
      state.currentBot = next;
      if (next) markBotRead(next);
      state.tab = "discussion";
      router.replace(next ? botPath(next, "discussion") : "/");
      return;
    }
    if (name) {
      state.currentBot = name;
      markBotRead(name);
    } else {
      // `/` and `/setup`: brand / checklist home — never auto-open a bot.
      state.currentBot = null;
    }

    const splitOn = !!(name && splitLayouts.value[name]?.on);
    if (!splitOn && tab === "terminal" && !terminalReady.value) {
      openDeskCreate("terminal");
      tab = "discussion";
    } else if (!splitOn && tab === "screen" && !screenReady.value) {
      openDeskCreate("screen");
      tab = "discussion";
    }
    state.tab = tab;

    if (name && splitLayouts.value[name]?.on) {
      const cur = splitLayouts.value[name];
      const right = cur.right === tab ? cur.left : cur.right;
      const pair = pairOrDefault(tab, right);
      if (pair.left !== cur.left || pair.right !== cur.right) {
        saveLayout(name, { on: true, ...pair });
      }
    }

    if (state.currentBot && route.name === "bot") {
      const canonical = botPath(state.currentBot, tab);
      const pathOnly = route.path;
      // Ne pas écraser ?msg=… (deep-link mention inter-bots).
      if (pathOnly !== canonical) {
        router.replace({ path: canonical, query: route.query, hash: route.hash });
      }
    }
  } finally {
    applyingRoute = false;
  }
}

async function toggleSearch() {
  searchOpen.value = !searchOpen.value;
  if (!searchOpen.value) {
    query.value = "";
    resetSearchHits();
  } else {
    await nextTick();
    searchInput.value?.focus();
  }
}

function closeSearch() {
  searchOpen.value = false;
  query.value = "";
  resetSearchHits();
}

function resetSearchHits() {
  msgHits.value = [];
  searchError.value = "";
  searchMode.value = "";
  searchLoading.value = false;
  if (searchTimer) {
    clearTimeout(searchTimer);
    searchTimer = null;
  }
}

async function runSearch(forceNl = false) {
  const q = query.value.trim();
  if (q.length < 2) {
    msgHits.value = [];
    searchMode.value = "";
    searchError.value = "";
    return;
  }
  const seq = ++searchSeq;
  searchLoading.value = true;
  searchError.value = "";
  try {
    const mode = forceNl ? "nl" : "auto";
    const data = await api.searchMessages(q, { limit: 20, mode });
    if (seq !== searchSeq) return;
    msgHits.value = Array.isArray(data?.hits) ? data.hits : [];
    searchMode.value = data?.mode || mode;
  } catch (e) {
    if (seq !== searchSeq) return;
    msgHits.value = [];
    searchError.value = e?.message || String(e);
  } finally {
    if (seq === searchSeq) searchLoading.value = false;
  }
}

async function openMessageHit(h) {
  if (!h?.bot || !h?.message_id) return;
  const name = h.bot;
  state.currentBot = name;
  markBotRead(name);
  state.tab = "discussion";
  try {
    if (!state.messages[name]?.length) {
      state.messages[name] = await api.listMessages(name);
    }
  } catch {
    /* ChatPane will retry */
  }
  closeSearch();
  router.push({
    path: botPath(name, "discussion"),
    query: { msg: h.message_id },
  });
}

watch(query, (q) => {
  if (!searchOpen.value) return;
  if (searchTimer) clearTimeout(searchTimer);
  if (!String(q || "").trim()) {
    resetSearchHits();
    return;
  }
  searchTimer = setTimeout(() => runSearch(false), 220);
});

const loadMessagesSeq = new Map();

async function loadMessages(name) {
  if (!name) return;
  if (!state.bots.some((b) => b.name === name)) return;
  const seq = (loadMessagesSeq.get(name) || 0) + 1;
  loadMessagesSeq.set(name, seq);
  try {
    const remote = await api.listMessages(name);
    // Ignore stale responses that would wipe a message just sent.
    if (loadMessagesSeq.get(name) !== seq) return;
    const local = state.messages[name] || [];
    const byId = new Map(remote.map((m) => [m.id, m]));
    for (const m of local) {
      if (!m?.id) continue;
      if (byId.has(m.id)) {
        // Keep SSE-accumulated streaming text when the HTTP snapshot is shorter.
        byId.set(m.id, preferLiveStreamingMessage(m, byId.get(m.id)));
        continue;
      }
      // Keep in-flight optimistic bubbles only if the server has not echoed them yet.
      if (isOptimisticMessageId(m.id)) {
        const echoed = remote.some(
          (r) =>
            r.role === m.role &&
            String(r.content || "") === String(m.content || "")
        );
        if (echoed) continue;
      }
      byId.set(m.id, m);
    }
    state.messages[name] = [...byId.values()].sort((a, b) =>
      String(a.created_at || "").localeCompare(String(b.created_at || ""))
    );
    previewLoaded.add(name);
  } catch {
    if (loadMessagesSeq.get(name) === seq) previewLoaded.delete(name);
    return;
  }
  try {
    state.terminal[name] = await api.terminalLog(name);
  } catch {
    state.terminal[name] = [];
  }
}

async function loadPreviews() {
  await Promise.all(
    state.bots.map(async (b) => {
      if (previewLoaded.has(b.name) || state.messages[b.name]) {
        previewLoaded.add(b.name);
        return;
      }
      previewLoaded.add(b.name);
      try {
        state.messages[b.name] = await api.listMessages(b.name);
      } catch {
        previewLoaded.delete(b.name);
      }
    })
  );
}

watch(
  () => state.currentBot,
  (name) => {
    if (name) {
      loadMessages(name);
      return;
    }
    if (route.name === "bot") router.replace("/");
  }
);

watch(
  () => state.bots.map((b) => b.name).join("\n"),
  () => loadPreviews()
);

watch(
  () => state.panel,
  (panel) => {
    if (panel === "computer") state.panel = "details";
  },
  { immediate: true }
);

watch([terminalReady, screenReady], () => {
  if (applyingRoute || splitActive.value) return;
  const name = state.currentBot;
  if (state.tab === "terminal" && !terminalReady.value) {
    state.tab = "discussion";
    if (name) goBot(name, "discussion");
  }
  if (state.tab === "screen" && !screenReady.value) {
    state.tab = "discussion";
    if (name) goBot(name, "discussion");
  }
});

watch(
  () => [route.name, route.params.name, route.params.tab],
  () => applyRoute(),
);

// Keep URL in sync if tab changes outside selectTab (ex. ManageMenu).
watch(
  () => state.tab,
  (tab) => {
    if (applyingRoute || !state.currentBot) return;
    goBot(state.currentBot, tab);
  },
);

async function loadPiStatus() {
  try {
    state.piStatus = await api.piStatus();
  } catch {
    state.piStatus = {
      ready: false,
      doc_url: "https://pi.dev/docs/latest/models",
      models_count: 0,
    };
  }
}

watch(
  () => bot.value?.label || state.currentBot || "",
  (label) => {
    document.title = label ? `${label} · Autonomous` : "Autonomous";
  },
  { immediate: true }
);

let focusTimer = 0;
function onCompanionFocus(ev) {
  const path = ev.detail?.path;
  if (typeof path !== "string" || !path.startsWith("/b/")) return;
  const go = () => {
    if (router.currentRoute.value.fullPath !== path) {
      router.push(path).catch(() => {});
    }
    window.focus();
  };
  if (document.visibilityState === "visible") {
    localStorage.setItem("autonomous-focus-at", String(Date.now()));
    go();
    return;
  }
  window.clearTimeout(focusTimer);
  focusTimer = window.setTimeout(() => {
    const at = Number(localStorage.getItem("autonomous-focus-at") || 0);
    if (Date.now() - at < 400) return;
    localStorage.setItem("autonomous-focus-at", String(Date.now()));
    go();
  }, 150);
}

onMounted(() => {
  applyRoute();
  if (state.currentBot) loadMessages(state.currentBot);
  loadPreviews();
  loadPiStatus();
  window.addEventListener("autonomous-focus", onCompanionFocus);
  narrowMq = window.matchMedia("(max-width: 1080px)");
  narrowLayout.value = narrowMq.matches;
  narrowMq.addEventListener("change", onNarrowChange);
  mobileMq = window.matchMedia("(max-width: 720px)");
  mobileLayout.value = mobileMq.matches;
  mobileMq.addEventListener("change", onMobileChange);
});

function onNarrowChange() {
  narrowLayout.value = !!(narrowMq && narrowMq.matches);
}

function onMobileChange() {
  mobileLayout.value = !!(mobileMq && mobileMq.matches);
  if (mobileLayout.value) state.inspectorOpen = false;
}

onUnmounted(() => {
  window.removeEventListener("autonomous-focus", onCompanionFocus);
  window.clearTimeout(focusTimer);
  narrowMq?.removeEventListener("change", onNarrowChange);
  mobileMq?.removeEventListener("change", onMobileChange);
});
</script>
