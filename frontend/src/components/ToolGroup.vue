<template>
  <div class="tool-group" :class="[groupStatus, { live: !sealed || groupStatus === 'running' }]">
    <button class="tool-group-summary" type="button" @click="onToggleList">
      <span class="tool-group-ico" aria-hidden="true">⚙</span>
      <span class="tool-group-title">{{ title }}</span>
      <span
        v-if="groupDurationLabel"
        class="tool-dur"
        :class="{ timeout: groupTimedOut }"
        :title="groupTimedOut ? t('chat.toolTimeout') : undefined"
      >{{ groupDurationLabel }}</span>
      <span
        v-if="groundingCount"
        class="tool-group-badge"
      >{{ t("chat.groundingGroup") }} · {{ groundingCount }}</span>
      <span
        v-if="statusSummary"
        class="tool-group-badge"
        :class="{ timeout: groupTimedOut }"
      >{{ statusSummary }}</span>
      <time
        v-if="groupTime"
        class="tool-group-time"
        :datetime="groupTimeIso"
      >{{ groupTime }}</time>
      <svg
        class="tool-group-caret"
        :class="{ open: listOpen }"
        viewBox="0 0 12 12"
        width="12"
        height="12"
        aria-hidden="true"
      >
        <path
          d="M2.5 4.2 6 7.8 9.5 4.2"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>

    <!-- Folded list only. Once the list is open, the running row at the bottom is enough. -->
    <div v-if="livePreview && !listOpen" class="tool-group-live tool-group-live-compact">
      <div class="tool-live-head">
        <span class="tool-live-name">{{ livePreview.name }}</span>
        <span
          v-if="livePreview.duration"
          class="tool-dur"
          :class="{ timeout: livePreview.timedOut, live: livePreview.running }"
        >{{ livePreview.duration }}</span>
        <span
          class="tool-live-status"
          :class="{ timeout: livePreview.timedOut }"
        >{{ livePreview.status }}</span>
        <button
          v-if="livePreview.running"
          type="button"
          class="tool-stop-btn"
          :disabled="stoppingTool"
          :title="t('chat.stopToolHint')"
          @click.stop="stopTool"
        >
          {{ t("chat.stopTool") }}
        </button>
        <span v-if="livePreview.hint" class="tool-live-hint">{{ livePreview.hint }}</span>
      </div>
    </div>

    <!-- Desk captures stay out of assistant bubbles: show the latest user-facing
         shot on the folded group so it is not buried under Expand → tool row. -->
    <figure
      v-if="foldedShotPreview && !listOpen"
      class="shot-card tool-shot tool-group-shot-preview"
    >
      <img
        :src="foldedShotPreview.meta?.url"
        :alt="firstLine(foldedShotPreview) || t('chat.screenshot')"
        loading="lazy"
      />
      <figcaption v-if="firstLine(foldedShotPreview)">{{ firstLine(foldedShotPreview) }}</figcaption>
    </figure>

    <!-- Liste d’outils (repliée) : pas de blocs séparés cible / pointeur. -->
    <ul v-if="listOpen" class="tool-group-list">
      <li
        v-for="m in detailEntries"
        :key="m.id"
        class="tool-row"
        :class="rowClass(m)"
        :data-answer="m.meta?.answer || ''"
      >
        <!-- Texte assistant au milieu du run (ordre chronologique). -->
        <template v-if="isRunText(m)">
          <p class="tool-run-text">{{ runTextBody(m) }}</p>
        </template>
        <!-- Orphan capture (API manuelle, sans outil). -->
        <template v-else-if="isShot(m)">
          <figure class="shot-card grounding tool-shot">
            <img
              :src="m.meta?.url"
              :alt="firstLine(m) || t('chat.screenshot')"
              loading="lazy"
            />
            <figcaption v-if="firstLine(m)">{{ firstLine(m) }}</figcaption>
          </figure>
        </template>
        <template v-else-if="isGrounding(m)">
          <p class="grounding-line">{{ firstLine(m) }}</p>
          <pre v-if="extraText(m)" class="grounding-extra">{{ extraText(m) }}</pre>
        </template>
        <template v-else-if="isLlmTurn(m)">
          <button
            class="tool-row-head llm-row-head"
            type="button"
            :title="t('chat.llmTurnHint')"
            @click="toggleLlmRow(m)"
          >
            <span class="tool-row-name">{{ llmTurnLabel(m) }}</span>
            <span v-if="llmTurnDurationLabel(m)" class="tool-dur">{{
              llmTurnDurationLabel(m)
            }}</span>
            <span v-if="llmTurnTokensLabel(m)" class="tool-row-pointer">{{
              llmTurnTokensLabel(m)
            }}</span>
            <time
              v-if="rowTime(m)"
              class="tool-row-time"
              :datetime="m.created_at"
            >{{ rowTime(m) }}</time>
            <svg
              class="tool-row-caret"
              :class="{ open: expanded[m.id] }"
              viewBox="0 0 12 12"
              width="11"
              height="11"
              aria-hidden="true"
            >
              <path
                d="M2.5 4.2 6 7.8 9.5 4.2"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </button>
          <div v-if="expanded[m.id]" class="tool-row-body">
            <p v-if="llmPayloadState(m.id)?.loading" class="tool-empty">
              {{ t("chat.llmTurnLoading") }}
            </p>
            <p
              v-else-if="llmPayloadState(m.id)?.error"
              class="tool-empty"
            >{{ t("chat.llmTurnLoadError") }}</p>
            <template v-else>
              <div
                v-if="llmPayloadState(m.id)?.requestText"
                class="tool-section"
              >
                <span class="tool-section-label">{{ t("chat.llmTurnRequestJson") }}</span>
                <pre class="llm-json-pre">{{ llmPayloadState(m.id).requestText }}</pre>
              </div>
              <div
                v-if="llmPayloadState(m.id)?.responseText"
                class="tool-section"
              >
                <span class="tool-section-label">{{ t("chat.llmTurnResponseJson") }}</span>
                <pre class="llm-json-pre">{{ llmPayloadState(m.id).responseText }}</pre>
              </div>
              <p
                v-else-if="isLlmTurnRunning(m)"
                class="tool-empty"
              >{{ t("chat.llmTurnWaiting") }}</p>
              <p
                v-else-if="
                  !llmPayloadState(m.id)?.requestText &&
                  !llmPayloadState(m.id)?.responseText
                "
                class="tool-empty"
              >{{ t("chat.llmTurnEmpty") }}</p>
            </template>
          </div>
        </template>
        <template v-else>
          <!-- div (not button): a nested stop <button> inside <button> breaks the flex layout. -->
          <div
            class="tool-row-head"
            role="button"
            tabindex="0"
            @click="toggle(m.id)"
            @keydown.enter.prevent="toggle(m.id)"
            @keydown.space.prevent="toggle(m.id)"
          >
            <span class="tool-row-name">{{ m.meta?.tool_name || t("chat.tool") }}</span>
            <span
              v-if="toolDurationLabel(m)"
              class="tool-dur"
              :class="{ timeout: isTimedOut(m), live: isRunning(m) }"
              :title="isTimedOut(m) ? t('chat.toolTimeout') : undefined"
            >{{ toolDurationLabel(m) }}</span>
            <span
              class="tool-row-status"
              :class="{ timeout: isTimedOut(m) }"
            >{{ statusLabel(m) }}</span>
            <button
              v-if="isRunning(m)"
              type="button"
              class="tool-stop-btn"
              :disabled="stoppingTool"
              :title="t('chat.stopToolHint')"
              @click.stop="stopTool"
            >
              {{ t("chat.stopTool") }}
            </button>
            <span v-if="rowHint(m)" class="tool-row-pointer">{{ rowHint(m) }}</span>
            <time
              v-if="rowTime(m)"
              class="tool-row-time"
              :datetime="m.created_at"
            >{{ rowTime(m) }}</time>
            <svg
              class="tool-row-caret"
              :class="{ open: expanded[m.id] }"
              viewBox="0 0 12 12"
              width="11"
              height="11"
              aria-hidden="true"
            >
              <path
                d="M2.5 4.2 6 7.8 9.5 4.2"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </div>
          <div v-if="expanded[m.id]" class="tool-row-body">
            <div v-if="argsText(m)" class="tool-section">
              <span class="tool-section-label">{{ t("chat.toolArgs") }}</span>
              <pre>{{ argsText(m) }}</pre>
            </div>
            <div v-if="resultText(m)" class="tool-section">
              <span class="tool-section-label">{{ t("chat.toolResult") }}</span>
              <pre>{{ resultText(m) }}</pre>
            </div>
            <!-- vm_ground : capture + croix sous l’outil déplié.
                 Les lignes « Grounding · boucle… » sont dans la liste, pas ici. -->
            <figure
              v-for="shot in targetShotFor(m) ? [targetShotFor(m)] : []"
              :key="`tgt-${m.id}`"
              class="shot-card grounding tool-shot tool-nested-shot target-shot"
            >
              <p class="shot-badge">
                {{ t("chat.groundingTarget") }}
                <span v-if="coordsOf(shot)" class="shot-coords">{{ coordsOf(shot) }}</span>
              </p>
              <div class="shot-frame">
                <img
                  :src="shot.meta?.url"
                  :alt="firstLine(shot) || t('chat.screenshot')"
                  loading="lazy"
                />
                <span
                  v-if="markStyle(shot)"
                  class="shot-mark"
                  :style="markStyle(shot)"
                  aria-hidden="true"
                />
              </div>
              <figcaption v-if="firstLine(shot)">{{ firstLine(shot) }}</figcaption>
            </figure>
            <!-- vm_screenshot : image seule (pas si déjà cible grounding) -->
            <figure
              v-for="shot in !targetShotFor(m) && shotForTool(m) ? [shotForTool(m)] : []"
              :key="`shot-${m.id}`"
              class="shot-card tool-shot tool-nested-shot"
            >
              <img
                :src="shot.meta?.url"
                :alt="firstLine(shot) || t('chat.screenshot')"
                loading="lazy"
              />
              <figcaption v-if="firstLine(shot)">{{ firstLine(shot) }}</figcaption>
            </figure>
            <!-- vm_click / drag / scroll : overlay sur la capture du run -->
            <figure
              v-for="ov in pointerOverlay(m) ? [pointerOverlay(m)] : []"
              :key="`ov-${m.id}`"
              class="shot-card tool-shot tool-nested-shot pointer-canvas"
            >
              <p class="shot-badge">{{ t("chat.pointerOverlay") }}</p>
              <div class="shot-frame">
                <img :src="ov.url" :alt="t('chat.pointerOverlay')" loading="lazy" />
                <span
                  v-if="ov.action.kind === 'vm_click' && pctOn(ov, ov.action.x, ov.action.y)"
                  class="shot-mark pointer-click"
                  :style="pctOn(ov, ov.action.x, ov.action.y)"
                  :title="ov.action.coordsText"
                  aria-hidden="true"
                />
                <svg
                  v-else-if="
                    ov.action.kind === 'vm_drag' &&
                    ov.action.x != null &&
                    ov.action.y != null &&
                    ov.action.x2 != null &&
                    ov.action.y2 != null
                  "
                  class="pointer-drag-svg"
                  :viewBox="`0 0 ${ov.w} ${ov.h}`"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                >
                  <line
                    :x1="ov.action.x"
                    :y1="ov.action.y"
                    :x2="ov.action.x2"
                    :y2="ov.action.y2"
                    class="pointer-drag-line"
                  />
                  <circle :cx="ov.action.x" :cy="ov.action.y" r="14" class="pointer-drag-start" />
                  <circle :cx="ov.action.x2" :cy="ov.action.y2" r="14" class="pointer-drag-end" />
                </svg>
                <span
                  v-else-if="ov.action.kind === 'vm_scroll' && pctOn(ov, ov.action.x, ov.action.y)"
                  class="shot-mark pointer-scroll"
                  :style="pctOn(ov, ov.action.x, ov.action.y)"
                  :title="ov.action.coordsText"
                  aria-hidden="true"
                />
              </div>
            </figure>
            <p
              v-if="
                !argsText(m) &&
                !resultText(m) &&
                !shotForTool(m) &&
                !targetShotFor(m) &&
                !pointerOverlay(m) &&
                !groundingNotesFor(m).length
              "
              class="tool-empty"
            >{{ t("chat.toolNoDetail") }}</p>
          </div>
        </template>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { formatDurationMs } from "../runTimings";
import { formatMsgTime } from "../timeFormat";

const POINTER_TOOLS = new Set(["vm_click", "vm_drag", "vm_scroll"]);

const props = defineProps({
  entries: { type: Array, required: true },
  /** True once a later chat item (assistant, vault…) follows this group. */
  sealed: { type: Boolean, default: false },
  bot: { type: String, default: "" },
});

const { t, locale } = useI18n();
const stoppingTool = ref(false);

function isRunning(m) {
  return (m?.meta?.status || "running") === "running";
}

function isLlmTurn(m) {
  return m?.role === "system" && m?.meta?.kind === "llm_turn";
}

function isLlmTurnRunning(m) {
  return isLlmTurn(m) && (m?.meta?.status || "") === "running";
}

function isRunText(m) {
  return m?.meta?.kind === "run_text";
}

function runTextBody(m) {
  return String(m?.content || "").trim();
}

function llmTurnLabel(m) {
  const status = String(m?.meta?.status || "done");
  if (status === "running") return t("chat.llmTurnRunning");
  if (status === "error") return t("chat.llmTurnError");
  if (status === "aborted") return t("chat.llmTurnAborted");
  return t("chat.llmTurnDone");
}

function llmTurnDurationMs(m) {
  const meta = m?.meta || {};
  if (Number.isFinite(Number(meta.duration_ms))) return Number(meta.duration_ms);
  const started = Number(meta.started_ms);
  if (Number.isFinite(started) && meta.status === "running") {
    return Math.max(0, nowMs.value - started);
  }
  return null;
}

function llmTurnDurationLabel(m) {
  const ms = llmTurnDurationMs(m);
  return ms == null ? "" : formatDurationMs(ms);
}

function formatTok(n) {
  const value = Number(n);
  if (!Number.isFinite(value)) return "";
  if (value >= 1000) return `${Math.round(value / 1000)}k`;
  return String(value);
}

function llmTurnTokensLabel(m) {
  const tin = Number(m?.meta?.tokens_in);
  const tout = Number(m?.meta?.tokens_out);
  if (!Number.isFinite(tin) && !Number.isFinite(tout)) return "";
  return t("chat.llmTurnTokens", {
    inn: formatTok(Number.isFinite(tin) ? tin : 0),
    out: formatTok(Number.isFinite(tout) ? tout : 0),
  });
}

const llmPayloadCache = reactive({});

function llmPayloadState(id) {
  return llmPayloadCache[id] || null;
}

function prettyJson(data) {
  try {
    if (data && data._legacy_text && data.text != null) {
      return String(data.text);
    }
    return JSON.stringify(data, null, 2);
  } catch {
    return String(data ?? "");
  }
}

async function loadLlmPayloads(m) {
  const id = m?.id;
  if (!id || !props.bot) return;
  const cur = llmPayloadCache[id];
  if (cur?.loading || (cur && !cur.error && (cur.requestText || cur.responseText))) {
    return;
  }
  llmPayloadCache[id] = { loading: true, error: false, requestText: "", responseText: "" };
  const meta = m.meta || {};
  let requestText = "";
  let responseText = "";
  let error = false;
  try {
    if (meta.request_file || meta.request) {
      try {
        const data = await api.llmTurnPayload(props.bot, id, "request");
        requestText = prettyJson(data);
      } catch {
        if (meta.request) requestText = String(meta.request);
      }
    }
    if (meta.response_file) {
      try {
        const data = await api.llmTurnPayload(props.bot, id, "response");
        responseText = prettyJson(data);
      } catch {
        error = !requestText;
      }
    } else if (meta.response && meta.status !== "running") {
      // Hint only until the full file arrives — still show something.
      responseText = String(meta.response);
    }
  } catch {
    error = true;
  }
  llmPayloadCache[id] = {
    loading: false,
    error: error && !requestText && !responseText,
    requestText,
    responseText,
  };
}

function toggleLlmRow(m) {
  const id = m?.id;
  if (!id) return;
  const next = !expanded[id];
  expanded[id] = next;
  if (next) loadLlmPayloads(m);
}

async function stopTool() {
  if (!props.bot || stoppingTool.value) return;
  stoppingTool.value = true;
  try {
    await api.cancelTool(props.bot);
  } catch {
    /* The command may already have finished. */
  } finally {
    stoppingTool.value = false;
  }
}
const expanded = reactive({});
/** Details open only when the user expands — never auto-open on seal. */
const listOpen = ref(false);
const userPinned = ref(false);

function rowTime(m) {
  return formatMsgTime(m?.created_at, locale.value);
}

/** Tick while a tool is running so elapsed duration updates live. */
const nowMs = ref(Date.now());
let tickTimer = null;

function entryTools() {
  return (props.entries || []).filter((m) => m?.meta?.kind === "tool");
}

function anyToolRunning() {
  return entryTools().some((m) => (m.meta?.status || "running") === "running");
}

function anyLlmTurnRunning() {
  return (props.entries || []).some((m) => isLlmTurnRunning(m));
}

function syncTick() {
  if (anyToolRunning() || anyLlmTurnRunning()) {
    nowMs.value = Date.now();
    if (!tickTimer) {
      tickTimer = setInterval(() => {
        nowMs.value = Date.now();
      }, 1000);
    }
  } else if (tickTimer) {
    clearInterval(tickTimer);
    tickTimer = null;
  }
}

onMounted(syncTick);
onBeforeUnmount(() => {
  if (tickTimer) clearInterval(tickTimer);
  tickTimer = null;
});

watch(
  () => props.entries,
  () => syncTick(),
  { deep: true },
);

function isTimedOut(m) {
  const meta = m?.meta || {};
  if (meta.timed_out === true) return true;
  const c = String(m?.content || "");
  if (/\[timeout after\s+\d+s\]/i.test(c)) return true;
  if (/timed out waiting/i.test(c) || /timed out after/i.test(c)) return true;
  return false;
}

function toolDurationMs(m) {
  const meta = m?.meta || {};
  const stored = Number(meta.duration_ms);
  if (Number.isFinite(stored) && stored >= 0) return stored;
  if ((meta.status || "running") === "running" && m?.created_at) {
    const start = Date.parse(m.created_at);
    if (Number.isFinite(start)) return Math.max(0, nowMs.value - start);
  }
  return null;
}

function toolDurationLabel(m) {
  const ms = toolDurationMs(m);
  return ms == null ? "" : formatDurationMs(ms);
}

const groupTimeIso = computed(() => {
  const first = props.entries.find((m) => m?.created_at);
  return first?.created_at || "";
});

const groupTime = computed(() => formatMsgTime(groupTimeIso.value, locale.value));

const groupDurationMs = computed(() => {
  void nowMs.value;
  let total = 0;
  let any = false;
  for (const m of entryTools()) {
    const ms = toolDurationMs(m);
    if (ms == null) continue;
    total += ms;
    any = true;
  }
  for (const m of props.entries || []) {
    if (!isLlmTurn(m)) continue;
    const ms = llmTurnDurationMs(m);
    if (ms == null) continue;
    total += ms;
    any = true;
  }
  return any ? total : null;
});

const groupDurationLabel = computed(() => {
  const ms = groupDurationMs.value;
  return ms == null ? "" : formatDurationMs(ms);
});

const groupTimedOut = computed(() => entryTools().some((m) => isTimedOut(m)));

function isShot(m) {
  return m?.meta?.kind === "screenshot";
}

function isGrounding(m) {
  return m?.meta?.kind === "grounding";
}

/** Latest desk capture meant for the user (not grounding loop frames). */
const foldedShotPreview = computed(() => {
  const shots = (props.entries || []).filter(
    (m) => isShot(m) && m?.meta?.url && !m?.meta?.grounding
  );
  if (!shots.length) return null;
  // Prefer the shot linked to the last vm_screenshot tool in this group.
  for (let i = (props.entries || []).length - 1; i >= 0; i--) {
    const m = props.entries[i];
    if (m?.meta?.kind === "tool" && m?.meta?.tool_name === "vm_screenshot") {
      const linked = shotForTool(m);
      if (linked?.meta?.url) return linked;
      break;
    }
  }
  return shots[shots.length - 1];
});

function isTargetShot(m) {
  if (!isShot(m) || !m?.meta?.grounding) return false;
  const phase = String(m.meta?.phase || "");
  if (m.meta?.target) return true;
  return phase.includes("cross");
}

/** Croix / cibles grounding — uniquement si le menu détail est ouvert. */
const targetShots = computed(() => {
  const crosses = props.entries.filter(isTargetShot);
  if (crosses.length) return crosses;
  const shots = props.entries.filter((m) => isShot(m) && m.meta?.grounding);
  return shots.slice(-1);
});

/**
 * Liste repliable = outils (et orphelins si pas d’outil).
 * Captures / notes grounding / overlays → sous la ligne d’outil dépliée.
 */
const detailEntries = computed(() => {
  const hasTools = props.entries.some((m) => m?.meta?.kind === "tool");
  const targetIdSet = new Set(targetShots.value.map((m) => m.id));
  return props.entries.filter((m) => {
    if (isShot(m)) {
      if (hasTools) return false;
      return !targetIdSet.has(m.id);
    }
    // Loop notes stay in the open list (« Grounding · boucle… »).
    // Captures stay nested under the vm_ground row.
    // LLM turns stay as normal rows in this list.
    return true;
  });
});

/** Capture liée à un outil (id dans le résultat / meta, sinon voisin temporel). */
function shotForTool(m) {
  if (!m || m?.meta?.kind !== "tool") return null;
  const name = m.meta?.tool_name || "";
  if (name !== "vm_screenshot" && name !== "vm_ground") return null;
  const shots = props.entries.filter((s) => isShot(s) && s.meta?.url);
  if (!shots.length) return null;

  const metaId = String(m.meta?.screenshot_id || "").trim();
  const metaUrl = String(m.meta?.screenshot_url || "").trim();
  const blob = `${resultText(m)}\n${JSON.stringify(m.meta?.args || {})}`;
  const fromText =
    metaId ||
    (blob.match(/id:\s*([0-9a-f-]{8,})/i) || [])[1] ||
    (blob.match(/screenshot_id["\s:=]+([0-9a-f-]{8,})/i) || [])[1] ||
    (blob.match(/screenshots\/([0-9a-f-]+)/i) || [])[1] ||
    "";
  if (fromText || metaUrl) {
    // vm_ground: its screenshot_id is the raw capture; the crosshair cards of
    // *that* call carry it as capture_id → show the last cross of this call.
    if (name === "vm_ground" && fromText) {
      const own = shots.filter((s) => String(s.meta?.capture_id || "") === fromText);
      const crosses = own.filter(isTargetShot);
      if (crosses.length) return crosses[crosses.length - 1];
      if (own.length) return own[own.length - 1];
    }
    const hit = shots.find((s) => {
      const sid = String(s.meta?.screenshot_id || "");
      const url = String(s.meta?.url || "");
      if (fromText && (sid === fromText || url.includes(fromText))) return true;
      if (metaUrl && url === metaUrl) return true;
      return false;
    });
    if (hit) return hit;
  }

  const toolTs = Date.parse(m.created_at || "") || 0;
  let best = null;
  let bestDelta = Infinity;
  for (const s of shots) {
    if (name === "vm_screenshot" && s.meta?.grounding) continue;
    if (name === "vm_ground" && !s.meta?.grounding) continue;
    const delta = Math.abs((Date.parse(s.created_at || "") || 0) - toolTs);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = s;
    }
  }
  if (best) return best;
  return name === "vm_screenshot" ? shots[shots.length - 1] : null;
}

/** Croix cible : sous vm_ground déplié uniquement. */
function targetShotFor(m) {
  if (m?.meta?.tool_name !== "vm_ground") return null;
  const linked = shotForTool(m);
  if (linked && isTargetShot(linked)) return linked;
  if (linked) return linked;
  // Legacy records without ids: last cross created before this tool ended,
  // never simply the latest one of the group.
  return shotAtOrBefore(targetShots.value, m) || null;
}

/** Notes de boucle grounding proches de cet appel vm_ground. */
function groundingNotesFor(m) {
  if (m?.meta?.tool_name !== "vm_ground") return [];
  const toolTs = Date.parse(m.created_at || "") || 0;
  const notes = props.entries.filter(isGrounding);
  if (!notes.length) return [];
  // Notes dans une fenêtre ±2 min autour de l’outil (boucle UI-TARS).
  const windowMs = 120_000;
  const near = notes.filter((n) => {
    const ts = Date.parse(n.created_at || "") || 0;
    return Math.abs(ts - toolTs) <= windowMs;
  });
  return near.length ? near : notes.slice(-4);
}

/** Overlay pointeur sous vm_click / vm_drag / vm_scroll déplié. */
function pointerOverlay(m) {
  const action = parsePointer(m);
  if (!action) return null;
  const canvas = overlayCanvas(m);
  if (!canvas) return null;
  return { ...canvas, action };
}

function shotTs(s) {
  return Date.parse(s?.created_at || "") || 0;
}

/** Last shot created at or before tool message `m` (by created_at). */
function shotAtOrBefore(list, m) {
  const ts = shotTs(m);
  let best = null;
  for (const s of list) {
    if (!ts || shotTs(s) <= ts) best = s;
  }
  return best;
}

/**
 * Screenshot the agent saw when it issued pointer tool `m`.
 * New records pin it (meta.base_screenshot_id); legacy ones fall back to the
 * last raw screenshot taken before the call — never the latest of the group.
 */
function overlayCanvas(m) {
  const shots = props.entries.filter((s) => {
    if (!isShot(s) || !s.meta?.url) return false;
    return (Number(s.meta?.width) || 0) > 0 && (Number(s.meta?.height) || 0) > 0;
  });
  const base = String(m?.meta?.base_screenshot_id || "").trim();
  let prefer = null;
  if (base) {
    // Raw capture of that step (not a cross/sheet: those may be stacked images).
    const own = shots.filter(
      (s) =>
        String(s.meta?.screenshot_id || "") === base ||
        String(s.meta?.capture_id || "") === base
    );
    prefer =
      own.find((s) => String(s.meta?.screenshot_id || "") === base) ||
      own.find((s) => s.meta?.phase === "capture") ||
      null;
  }
  if (!prefer) {
    const raw = shots.filter((s) => !isTargetShot(s));
    prefer = shotAtOrBefore(raw, m);
  }
  if (!prefer) return null;
  return {
    url: prefer.meta.url,
    w: Number(prefer.meta.width) || 1920,
    h: Number(prefer.meta.height) || 1200,
  };
}

function pctOn(canvas, x, y) {
  if (!canvas || x == null || y == null) return null;
  return {
    left: `${(x / canvas.w) * 100}%`,
    top: `${(y / canvas.h) * 100}%`,
  };
}

const tools = computed(() => props.entries.filter((m) => m?.meta?.kind === "tool"));

const lastTool = computed(() => {
  const list = tools.value;
  return list.length ? list[list.length - 1] : null;
});

/** Live key: refresh preview when the active tool advances. */
const liveTick = computed(() => {
  const last = lastTool.value;
  if (!last) return "none";
  return `${last.id}:${last.meta?.status || ""}:${String(last.content || "").length}:${toolDurationMs(last) ?? ""}`;
});

/** Compact live line: last tool name + status (details stay in the folded list). */
const livePreview = computed(() => {
  const running = [...entryTools()].reverse().find((m) => isRunning(m));
  const m = running || lastTool.value;
  if (!m) {
    const llm = [...(props.entries || [])].reverse().find(isLlmTurnRunning);
    if (!llm || props.sealed) return null;
    void nowMs.value;
    return {
      name: llmTurnLabel(llm),
      status: "",
      hint: llmTurnTokensLabel(llm),
      duration: llmTurnDurationLabel(llm),
      timedOut: false,
      running: true,
    };
  }
  const active = isRunning(m);
  if (props.sealed && !active) return null;
  void nowMs.value;
  return {
    name: m.meta?.tool_name || t("chat.tool"),
    status: statusLabel(m),
    hint: rowHint(m),
    duration: toolDurationLabel(m),
    timedOut: isTimedOut(m),
    running: active,
  };
});

function clearExpanded() {
  for (const key of Object.keys(expanded)) delete expanded[key];
}

function onToggleList() {
  userPinned.value = true;
  listOpen.value = !listOpen.value;
}

watch(
  () => props.sealed,
  (sealed) => {
    // LLM replied (or other follow-up) → collapse unless the user opened details.
    if (sealed) {
      if (!userPinned.value) {
        listOpen.value = false;
        clearExpanded();
      }
      return;
    }
    if (!userPinned.value) {
      listOpen.value = false;
    }
  },
  { immediate: true }
);

watch(
  liveTick,
  () => {
    if (props.sealed || userPinned.value) return;
    // Pendant le run : aperçu live du dernier outil, menu détail fermé.
    listOpen.value = false;
    clearExpanded();
  },
  { immediate: true }
);

function firstLine(m) {
  const text = String(m?.content || "").trim();
  const nl = text.indexOf("\n");
  return nl >= 0 ? text.slice(0, nl).trim() : text;
}

function extraText(m) {
  const text = String(m?.content || "").trim();
  const nl = text.indexOf("\n");
  if (nl < 0) return "";
  return text.slice(nl + 1).trim();
}

function coordsOf(m) {
  const x = m?.meta?.x;
  const y = m?.meta?.y;
  if (typeof x === "number" && typeof y === "number") return `(${x}, ${y})`;
  const line = firstLine(m);
  const match = line.match(/\((\d+)\s*,\s*(\d+)\)/);
  return match ? `(${match[1]}, ${match[2]})` : "";
}

function markStyle(m) {
  const meta = m?.meta || {};
  let x = meta.x;
  let y = meta.y;
  const w = Number(meta.width) || 0;
  const h = Number(meta.height) || 0;
  if ((typeof x !== "number" || typeof y !== "number") && firstLine(m)) {
    const match = firstLine(m).match(/\((\d+)\s*,\s*(\d+)\)/);
    if (match) {
      x = Number(match[1]);
      y = Number(match[2]);
    }
  }
  if (typeof x !== "number" || typeof y !== "number" || !w || !h) return null;
  return {
    left: `${(x / w) * 100}%`,
    top: `${(y / h) * 100}%`,
  };
}

function asNum(v) {
  if (v == null || typeof v === "boolean") return null;
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n) : null;
}

function resultText(m) {
  const content = m?.content || "";
  const marker = "\n---\n";
  const i = content.indexOf(marker);
  if (i >= 0) return content.slice(i + marker.length).trim();
  return "";
}

function parsePointer(m) {
  const name = m?.meta?.tool_name;
  if (!POINTER_TOOLS.has(name)) return null;
  const meta = m.meta || {};
  const args = meta.args && typeof meta.args === "object" ? meta.args : {};
  const text = resultText(m);
  let x = asNum(meta.x ?? args.x);
  let y = asNum(meta.y ?? args.y);
  let x2 = asNum(meta.x2 ?? args.x2);
  let y2 = asNum(meta.y2 ?? args.y2);
  let dy = asNum(meta.dy ?? args.dy);
  let button = meta.button || args.button || "";

  if (name === "vm_click" && (x == null || y == null)) {
    const match = text.match(/at\s*\((-?\d+)\s*,\s*(-?\d+)\)/i);
    if (match) {
      x = Number(match[1]);
      y = Number(match[2]);
    }
    const btn = text.match(/Clicked\s+(\w+)\s+at/i);
    if (btn && !button) button = btn[1].toLowerCase();
  }
  if (name === "vm_drag" && (x == null || y == null || x2 == null || y2 == null)) {
    const match = text.match(
      /\((-?\d+)\s*,\s*(-?\d+)\)\s*→\s*\((-?\d+)\s*,\s*(-?\d+)\)/
    );
    if (match) {
      x = Number(match[1]);
      y = Number(match[2]);
      x2 = Number(match[3]);
      y2 = Number(match[4]);
    }
  }
  if (name === "vm_scroll" && dy == null) {
    const match = text.match(/dy=(-?\d+)\s+at\s*\((-?\d+)\s*,\s*(-?\d+)\)/i);
    if (match) {
      dy = Number(match[1]);
      x = Number(match[2]);
      y = Number(match[3]);
    }
  }

  if (x == null && y == null && x2 == null && dy == null) return null;

  let label = t("chat.pointerClick");
  let coordsText = x != null && y != null ? `(${x}, ${y})` : "";
  let extra = button && button !== "left" ? button : "";
  if (name === "vm_drag") {
    label = t("chat.pointerDrag");
    coordsText =
      x != null && y != null && x2 != null && y2 != null
        ? `(${x}, ${y}) → (${x2}, ${y2})`
        : coordsText;
  } else if (name === "vm_scroll") {
    label = t("chat.pointerScroll");
    coordsText = dy != null ? `dy=${dy}` + (coordsText ? ` @ ${coordsText}` : "") : coordsText;
  }

  return {
    id: m.id,
    kind: name,
    status: meta.status || "done",
    label,
    coordsText,
    extra,
    x,
    y,
    x2,
    y2,
    dy,
    button,
  };
}

function pointerHint(m) {
  const a = parsePointer(m);
  return a ? a.coordsText : "";
}

function rowHint(m) {
  if (m?.meta?.tool_name === "vm_ground") {
    const instr = String(m?.meta?.args?.instruction || "").trim();
    if (instr) return instr.length > 72 ? `${instr.slice(0, 72)}…` : instr;
  }
  return pointerHint(m);
}

const groundingCount = computed(
  () => tools.value.filter((m) => m?.meta?.tool_name === "vm_ground").length
);

const title = computed(() => {
  if (targetShots.value.length && !tools.value.length) {
    return t("chat.groundingGroup");
  }
  const nTools = tools.value.length;
  const nLlm = (props.entries || []).filter(isLlmTurn).length;
  const bits = [];
  if (nTools === 1) bits.push(t("chat.toolOne"));
  else if (nTools > 1) bits.push(t("chat.toolMany", { count: nTools }));
  if (nLlm === 1) bits.push(t("chat.llmTurnOne"));
  else if (nLlm > 1) bits.push(t("chat.llmTurnMany", { count: nLlm }));
  if (bits.length) return bits.join(", ");
  const last = [...props.entries].reverse().find((m) => isGrounding(m) || isShot(m));
  const line = last ? firstLine(last) : "";
  if (!line) return t("chat.groundingGroup");
  return line.length > 72 ? `${line.slice(0, 72)}…` : line;
});

const groupStatus = computed(() => {
  if ((props.entries || []).some(isLlmTurnRunning)) return "running";
  const statuses = tools.value.map((m) => m.meta?.status || "running");
  if (statuses.some((s) => s === "running")) return "running";
  if (statuses.some((s) => s === "error")) return "error";
  const answers = props.entries.map((m) => m.meta?.answer).filter(Boolean);
  const last = answers[answers.length - 1];
  if (last === "NO" || last === "UNCERTAIN") return "error";
  const failed = props.entries.some((m) => m.meta?.phase === "failed");
  if (failed) return "error";
  return "done";
});

const statusSummary = computed(() => {
  if (tools.value.length) {
    const running = tools.value.filter((m) => (m.meta?.status || "running") === "running").length;
    const errors = tools.value.filter((m) => m.meta?.status === "error").length;
    if (running) return t("chat.toolRunning");
    if (errors) return t("chat.toolErrorCount", { count: errors });
    return t("chat.toolDone");
  }
  const answers = props.entries.map((m) => m.meta?.answer).filter(Boolean);
  return answers[answers.length - 1] || "";
});

function rowClass(m) {
  if (isRunText(m)) return "run-text-row done";
  if (isShot(m)) return "tool-shot-row";
  if (isGrounding(m)) return "grounding-line-row";
  return m.meta?.status || "running";
}

function statusLabel(m) {
  const s = m?.meta?.status;
  if (s === "done") return t("chat.toolDone");
  if (s === "error") return t("chat.toolError");
  return t("chat.toolRunning");
}

function argsText(m) {
  const args = m?.meta?.args;
  if (!args || (typeof args === "object" && !Object.keys(args).length)) return "";
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

function toggle(id) {
  expanded[id] = !expanded[id];
}
</script>
