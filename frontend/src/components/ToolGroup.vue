<template>
  <div class="tool-group" :class="[groupStatus, { live: !sealed }]">
    <button class="tool-group-summary" type="button" @click="onToggleList">
      <span class="tool-group-ico" aria-hidden="true">⚙</span>
      <span class="tool-group-title">{{ title }}</span>
      <span v-if="statusSummary" class="tool-group-badge">{{ statusSummary }}</span>
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

    <!-- Pendant le run : résultat du dernier appel d’outil (tous outils, pas seulement grounding). -->
    <div v-if="livePreview" class="tool-group-live">
      <div class="tool-live-head">
        <span class="tool-live-name">{{ livePreview.name }}</span>
        <span class="tool-live-status">{{ livePreview.status }}</span>
        <span v-if="livePreview.hint" class="tool-live-hint">{{ livePreview.hint }}</span>
      </div>
      <div v-if="livePreview.args" class="tool-section">
        <span class="tool-section-label">{{ t("chat.toolArgs") }}</span>
        <pre>{{ livePreview.args }}</pre>
      </div>
      <div v-if="livePreview.result" class="tool-section">
        <span class="tool-section-label">{{ t("chat.toolResult") }}</span>
        <pre>{{ livePreview.result }}</pre>
      </div>
      <p v-else-if="!livePreview.args" class="tool-empty">{{ t("chat.toolNoDetail") }}</p>
    </div>

    <!-- Liste d’outils (repliée) : pas de blocs séparés cible / pointeur. -->
    <ul v-if="listOpen" class="tool-group-list">
      <li
        v-for="m in detailEntries"
        :key="m.id"
        class="tool-row"
        :class="rowClass(m)"
        :data-answer="m.meta?.answer || ''"
      >
        <!-- Orphan capture (API manuelle, sans outil). -->
        <template v-if="isShot(m)">
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
        <template v-else>
          <button class="tool-row-head" type="button" @click="toggle(m.id)">
            <span class="tool-row-name">{{ m.meta?.tool_name || t("chat.tool") }}</span>
            <span class="tool-row-status">{{ statusLabel(m) }}</span>
            <span v-if="pointerHint(m)" class="tool-row-pointer">{{ pointerHint(m) }}</span>
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
            <div v-if="argsText(m)" class="tool-section">
              <span class="tool-section-label">{{ t("chat.toolArgs") }}</span>
              <pre>{{ argsText(m) }}</pre>
            </div>
            <div v-if="resultText(m)" class="tool-section">
              <span class="tool-section-label">{{ t("chat.toolResult") }}</span>
              <pre>{{ resultText(m) }}</pre>
            </div>
            <div
              v-if="groundingNotesFor(m).length"
              class="tool-section tool-grounding-notes"
            >
              <p
                v-for="n in groundingNotesFor(m)"
                :key="n.id"
                class="grounding-line"
              >{{ firstLine(n) }}</p>
            </div>
            <!-- vm_ground : capture + croix sous l’outil déplié -->
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
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { formatMsgTime } from "../timeFormat";

const POINTER_TOOLS = new Set(["vm_click", "vm_drag", "vm_scroll"]);

const props = defineProps({
  entries: { type: Array, required: true },
  /** True once a later chat item (assistant, vault…) follows this group. */
  sealed: { type: Boolean, default: false },
});

const { t, locale } = useI18n();
const expanded = reactive({});
/** Details open only when the user expands — never auto-open on seal. */
const listOpen = ref(false);
const userPinned = ref(false);

function rowTime(m) {
  return formatMsgTime(m?.created_at, locale.value);
}

const groupTimeIso = computed(() => {
  const first = props.entries.find((m) => m?.created_at);
  return first?.created_at || "";
});

const groupTime = computed(() => formatMsgTime(groupTimeIso.value, locale.value));

function isShot(m) {
  return m?.meta?.kind === "screenshot";
}

function isGrounding(m) {
  return m?.meta?.kind === "grounding";
}

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
    // Notes de boucle grounding → sous vm_ground déplié, pas en lignes libres.
    if (isGrounding(m) && hasTools) return false;
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
  return `${last.id}:${last.meta?.status || ""}:${String(last.content || "").length}`;
});

/** Aperçu live : dernier outil, quel qu’il soit (vm_*, browser_*, …). */
const livePreview = computed(() => {
  if (props.sealed) return null;
  const m = lastTool.value;
  if (!m) return null;
  return {
    name: m.meta?.tool_name || t("chat.tool"),
    status: statusLabel(m),
    hint: pointerHint(m),
    args: argsText(m),
    result: resultText(m),
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

const title = computed(() => {
  if (targetShots.value.length && !tools.value.length) {
    return t("chat.groundingGroup");
  }
  const n = tools.value.length;
  if (!n) {
    const last = [...props.entries].reverse().find((m) => isGrounding(m) || isShot(m));
    const line = last ? firstLine(last) : "";
    if (!line) return t("chat.groundingGroup");
    return line.length > 72 ? `${line.slice(0, 72)}…` : line;
  }
  return n <= 1 ? t("chat.toolOne") : t("chat.toolMany", { count: n });
});

const groupStatus = computed(() => {
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
