<template>
  <div class="token-usage">
    <header class="token-usage-head">
      <h2>{{ t("settings.tokensTitle") }}</h2>
      <p class="hint">{{ narrow ? t("settings.tokensHintMobile") : t("settings.tokensHint") }}</p>
    </header>

    <div v-if="loading" class="token-usage-empty">…</div>
    <div v-else-if="error" class="token-usage-empty vault-error">{{ error }}</div>
    <template v-else-if="narrow">
      <div v-if="selectedDay" class="token-usage-daynav">
        <button
          type="button"
          :disabled="!canPrevDay"
          :aria-label="t('settings.tokensPrevDay')"
          @click="shiftDay(-1)"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M14.5 6.5 9 12l5.5 5.5" />
          </svg>
        </button>
        <span class="token-usage-daynav-date">{{ formatNavDate(selectedDay) }}</span>
        <button
          type="button"
          :disabled="!canNextDay"
          :aria-label="t('settings.tokensNextDay')"
          @click="shiftDay(1)"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M9.5 6.5 15 12l-5.5 5.5" />
          </svg>
        </button>
      </div>
      <div class="token-usage-table-wrap">
        <p v-if="!dayBots.length" class="token-usage-empty">{{ t("settings.tokensDayEmpty") }}</p>
        <table v-else class="token-usage-table">
          <thead>
            <tr>
              <th scope="col">{{ t("settings.tokensColBot") }}</th>
              <th scope="col">{{ t("settings.tokensColTotal") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in dayBots" :key="s.bot">
              <th scope="row">
                <span class="token-usage-bot">
                  <BotAvatar class="token-usage-legend-av" :bot="legendBot(s)" size="sm" />
                  <span class="token-usage-bot-name">{{ s.label }}</span>
                </span>
              </th>
              <td>{{ formatExact(s.amount) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <template v-else>
      <ul
        v-if="series.length"
        class="token-usage-legend"
        :aria-label="t('settings.tokensLegend')"
      >
        <li v-for="s in series" :key="s.bot" class="token-usage-legend-item">
          <BotAvatar class="token-usage-legend-av" :bot="legendBot(s)" size="sm" />
          <span class="token-usage-legend-name" :style="{ color: lineColor(s) }">
            {{ s.label }}
          </span>
        </li>
      </ul>

      <div
        ref="scrollEl"
        class="token-usage-scroll"
        @scroll="onScroll"
      >
        <div
          class="token-usage-canvas"
          :style="{ width: canvasWidth + 'px' }"
          @mousemove="onMove"
          @mouseleave="hover = null"
        >
          <svg
            class="token-usage-svg"
            :viewBox="`0 0 ${canvasWidth} ${chartH}`"
            preserveAspectRatio="none"
            :width="canvasWidth"
            :height="chartH"
          >
            <line
              v-for="(gy, i) in gridYs"
              :key="'g' + i"
              class="token-usage-grid"
              :x1="pad.l"
              :x2="canvasWidth - pad.r"
              :y1="gy"
              :y2="gy"
            />
            <path
              v-for="s in series"
              :key="s.bot"
              class="token-usage-line"
              :d="pathFor(s)"
              fill="none"
              :stroke="lineColor(s)"
              stroke-width="2.4"
              stroke-linecap="round"
              stroke-linejoin="round"
              vector-effect="non-scaling-stroke"
            />
            <circle
              v-for="s in series"
              :key="'end' + s.bot"
              :cx="xAt(nDays - 1)"
              :cy="yAt(s.cumulative[nDays - 1] || 0)"
              r="4.5"
              :fill="lineColor(s)"
            />
            <g v-if="hover && maxCumulative">
              <line
                class="token-usage-guide"
                :x1="xAt(hover.index)"
                :x2="xAt(hover.index)"
                :y1="pad.t"
                :y2="chartH - pad.b"
              />
              <circle
                v-for="s in series"
                :key="'d' + s.bot"
                :cx="xAt(hover.index)"
                :cy="yAt(s.cumulative[hover.index] || 0)"
                r="4"
                :fill="lineColor(s)"
              />
            </g>
          </svg>
          <div
            v-if="hover && maxCumulative"
            class="token-usage-tip"
            :style="tipStyle"
          >
            <strong>{{ hover.day }}</strong>
            <ul>
              <li v-for="s in series" :key="'t' + s.bot">
                <span :style="{ color: lineColor(s) }">{{ s.label }}</span>
                <em>{{ formatTokens(s.cumulative[hover.index] || 0) }}</em>
              </li>
            </ul>
          </div>
          <div class="token-usage-yaxis">
            <span>{{ maxCumulative ? formatTokens(yMax) : "0" }}</span>
            <span>0</span>
          </div>
          <p v-if="!maxCumulative" class="token-usage-empty-overlay">
            {{ t("settings.tokensEmpty") }}
          </p>
        </div>
      </div>
      <p class="token-usage-range hint">{{ rangeLabel }}</p>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { SWATCHES, swatchCssAt } from "@companion-avatar";
import { api } from "../api";
import { avatarColor } from "../avatarColor";
import BotAvatar from "./BotAvatar.vue";

const WINDOW_DAYS = 30;
const PX_PER_DAY = 28;
const pad = { t: 16, r: 12, b: 28, l: 8 };

const { t, locale } = useI18n();
const NARROW_MQ = "(max-width: 760px)";
const narrow = ref(typeof window !== "undefined" && window.matchMedia(NARROW_MQ).matches);
const dayIndex = ref(-1);
const loading = ref(true);
const error = ref("");
const days = ref([]);
const series = ref([]);
const maxCumulative = ref(0);
const scrollEl = ref(null);
const chartH = ref(420);
const hover = ref(null);
let ro = null;
let narrowMq = null;

function syncNarrow() {
  narrow.value = !!(narrowMq && narrowMq.matches);
}

watch(days, (list) => {
  if (!list.length) {
    dayIndex.value = -1;
    return;
  }
  if (dayIndex.value < 0 || dayIndex.value >= list.length) dayIndex.value = list.length - 1;
});

const selectedDay = computed(() => days.value[dayIndex.value] || "");
const canPrevDay = computed(() => dayIndex.value > 0);
const canNextDay = computed(() => dayIndex.value >= 0 && dayIndex.value < days.value.length - 1);
const dayBots = computed(() => {
  const i = dayIndex.value;
  if (i < 0) return [];
  return series.value
    .map((s) => ({ ...s, amount: Number((s.daily || [])[i]) || 0 }))
    .filter((s) => s.amount > 0)
    .sort((a, b) => b.amount - a.amount || String(a.label).localeCompare(String(b.label)));
});

function shiftDay(delta) {
  const next = dayIndex.value + delta;
  if (next < 0 || next >= days.value.length) return;
  dayIndex.value = next;
}

const yMax = computed(() => Math.max(1, Number(maxCumulative.value) || 0));
const nDays = computed(() => days.value.length || 1);
const canvasWidth = computed(() =>
  Math.max(nDays.value * PX_PER_DAY, WINDOW_DAYS * PX_PER_DAY) + pad.l + pad.r,
);

const gridYs = computed(() => {
  const steps = 4;
  const out = [];
  for (let i = 0; i <= steps; i++) {
    const v = (yMax.value * i) / steps;
    out.push(yAt(v));
  }
  return out;
});

const rangeLabel = computed(() => {
  if (!days.value.length) return "";
  const first = days.value[0];
  const last = days.value[days.value.length - 1];
  return t("settings.tokensRange", { from: first, to: last });
});

const tipStyle = computed(() => {
  if (!hover.value || !scrollEl.value) return {};
  const x = xAt(hover.value.index) - (scrollEl.value.scrollLeft || 0);
  const left = Math.min(Math.max(x + 12, 8), (scrollEl.value.clientWidth || 200) - 180);
  return { left: `${left}px`, top: `${pad.t + 8}px` };
});

function legendBot(s) {
  return {
    name: s.bot,
    label: s.label,
    avatar: s.avatar,
    avatar_color: s.avatar_color,
    status: "idle",
  };
}

function lineColor(s) {
  const i = Math.max(0, Math.min(SWATCHES.length - 1, Number(s.avatar_color) || 0));
  const css = swatchCssAt(i);
  // Original swatch has no solid hue — fall back to the stable name palette.
  return css || avatarColor(s.bot || s.label);
}

function xAt(i) {
  const span = Math.max(1, nDays.value - 1);
  const inner = canvasWidth.value - pad.l - pad.r;
  return pad.l + (i / span) * inner;
}

function yAt(v) {
  const inner = chartH.value - pad.t - pad.b;
  const ratio = Math.min(1, Math.max(0, Number(v) / yMax.value));
  return pad.t + inner * (1 - ratio);
}

function pathFor(s) {
  const vals = s.cumulative || [];
  if (!vals.length) return "";
  return vals
    .map((v, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(2)} ${yAt(v).toFixed(2)}`)
    .join(" ");
}

function formatNavDate(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const yyyy = String(d.getUTCFullYear());
  if (String(locale.value || "").toLowerCase().startsWith("en")) return `${mm}/${dd}/${yyyy}`;
  return `${dd}/${mm}/${yyyy}`;
}

function formatExact(n) {
  const v = Math.round(Number(n) || 0);
  try {
    return v.toLocaleString(locale.value || undefined);
  } catch {
    return String(v);
  }
}

function formatTokens(n) {
  const v = Math.round(Number(n) || 0);
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 10_000) return `${Math.round(v / 1000)}k`;
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return String(v);
}

function onMove(ev) {
  const el = scrollEl.value;
  if (!el || !days.value.length) return;
  const rect = el.getBoundingClientRect();
  const x = ev.clientX - rect.left + el.scrollLeft;
  const span = Math.max(1, nDays.value - 1);
  const inner = canvasWidth.value - pad.l - pad.r;
  const ratio = Math.min(1, Math.max(0, (x - pad.l) / inner));
  const index = Math.round(ratio * span);
  hover.value = { index, day: days.value[index] };
}

function onScroll() {
  /* tip position depends on scrollLeft via tipStyle */
}

function measureHeight() {
  const el = scrollEl.value;
  if (!el) return;
  const h = el.clientHeight;
  if (h > 80) chartH.value = h;
}

function scrollToEnd() {
  const el = scrollEl.value;
  if (!el) return;
  el.scrollLeft = Math.max(0, el.scrollWidth - el.clientWidth);
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await api.tokenUsageHistory();
    days.value = Array.isArray(data.days) ? data.days : [];
    series.value = Array.isArray(data.series) ? data.series : [];
    maxCumulative.value = Number(data.max_cumulative) || 0;
  } catch (e) {
    error.value = e.message || String(e);
  } finally {
    loading.value = false;
    await nextTick();
    measureHeight();
    scrollToEnd();
  }
}

onMounted(async () => {
  if (typeof window !== "undefined" && window.matchMedia) {
    narrowMq = window.matchMedia(NARROW_MQ);
    syncNarrow();
    narrowMq.addEventListener("change", syncNarrow);
  }
  await load();
  await nextTick();
  measureHeight();
  scrollToEnd();
  if (typeof ResizeObserver !== "undefined" && scrollEl.value) {
    ro = new ResizeObserver(() => {
      measureHeight();
    });
    ro.observe(scrollEl.value);
  }
});

watch(narrow, async (isNarrow) => {
  if (isNarrow) return;
  await nextTick();
  measureHeight();
  scrollToEnd();
  if (ro) ro.disconnect();
  if (typeof ResizeObserver !== "undefined" && scrollEl.value) {
    ro = new ResizeObserver(() => measureHeight());
    ro.observe(scrollEl.value);
  }
});

onUnmounted(() => {
  if (ro) ro.disconnect();
  if (narrowMq) narrowMq.removeEventListener("change", syncNarrow);
});
</script>

<style scoped>
.token-usage {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0 1.5rem 0.85rem 0;
  box-sizing: border-box;
}

@media (max-width: 760px) {
  .token-usage {
    padding-left: 0;
    padding-right: 0;
  }

  .token-usage-head {
    padding-left: 0.75rem;
    padding-right: 0.75rem;
  }
}

.token-usage-head h2 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.token-usage-head .hint,
.token-usage-range {
  margin: 0.2rem 0 0;
}

.token-usage-daynav {
  display: grid;
  grid-template-columns: 2.5rem minmax(0, 1fr) 2.5rem;
  align-items: center;
  margin: 0 0.75rem;
  min-height: 2.5rem;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--bg-elev);
  color: var(--text);
  box-shadow: var(--shadow-xs);
}

.token-usage-daynav button {
  appearance: none;
  border: 0;
  background: transparent;
  color: var(--accent-ink);
  width: 2.5rem;
  height: 2.5rem;
  display: grid;
  place-items: center;
  cursor: pointer;
  border-radius: var(--radius-sm);
}

.token-usage-daynav button:hover:not(:disabled) {
  background: var(--accent-softer);
  color: var(--accent);
}

.token-usage-daynav button:disabled {
  color: var(--muted);
  opacity: 0.45;
  cursor: default;
}

.token-usage-daynav-date {
  text-align: center;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
  color: var(--text);
}

.token-usage-table-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.token-usage-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 0.92rem;
}

.token-usage-table th:nth-child(2),
.token-usage-table td:nth-child(2),
.token-usage-table th:nth-child(3),
.token-usage-table td:nth-child(3) {
  width: 5.4rem;
}

.token-usage-table th,
.token-usage-table td {
  padding: 0.55rem 0.75rem;
  text-align: left;
  font-weight: 550;
}

.token-usage-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--bg-sidebar);
  color: #6b6b70;
  font-size: 0.72rem;
  font-weight: 650;
  letter-spacing: 0.02em;
}

.token-usage-table tbody th,
.token-usage-table tbody td {
  border-top: 1px solid var(--line);
  font-weight: 500;
}

.token-usage-table th:nth-child(n + 2),
.token-usage-table td {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.token-usage-bot {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
  text-align: left;
  font-weight: 600;
}

.token-usage-bot-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}


.token-usage-empty {
  flex: 1;
  display: grid;
  place-items: center;
  color: #6b6b70;
  font-size: 0.92rem;
}

.token-usage-empty-overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  margin: 0;
  padding: 1.5rem;
  text-align: center;
  color: #6b6b70;
  font-size: 0.92rem;
  pointer-events: none;
  background: linear-gradient(
    180deg,
    color-mix(in srgb, #fff 35%, transparent),
    color-mix(in srgb, #fff 55%, transparent)
  );
}

.token-usage-legend {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem 1rem;
  align-items: center;
}

.token-usage-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.token-usage-legend-av {
  width: 22px !important;
  height: 22px !important;
  flex: none;
}

.token-usage-legend-av :deep(svg.avatar-svg) {
  width: 22px !important;
  height: 22px !important;
}

.token-usage-legend-name {
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 9rem;
}

.token-usage-scroll {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow-x: auto;
  overflow-y: hidden;
  border-radius: 14px;
  background: color-mix(in srgb, #fff 70%, var(--bg-sidebar));
  border: 1px solid var(--line);
}

.token-usage-canvas {
  position: relative;
  height: 100%;
  min-height: 280px;
}

.token-usage-svg {
  display: block;
  height: 100%;
}

.token-usage-grid {
  stroke: color-mix(in srgb, var(--line) 80%, transparent);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.token-usage-guide {
  stroke: color-mix(in srgb, #1c1c1e 35%, transparent);
  stroke-width: 1;
  stroke-dasharray: 3 4;
  vector-effect: non-scaling-stroke;
}

.token-usage-yaxis {
  position: absolute;
  left: 0.4rem;
  top: 0.35rem;
  bottom: 0.55rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  pointer-events: none;
  font-size: 0.68rem;
  color: #8a8a90;
  font-variant-numeric: tabular-nums;
}

.token-usage-tip {
  position: absolute;
  z-index: 2;
  min-width: 9.5rem;
  max-width: 14rem;
  padding: 0.45rem 0.55rem;
  border-radius: 10px;
  background: #1c1c1e;
  color: #fff;
  font-size: 0.72rem;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.18);
  pointer-events: none;
}

.token-usage-tip strong {
  display: block;
  margin-bottom: 0.25rem;
  font-weight: 600;
  opacity: 0.85;
}

.token-usage-tip ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.15rem;
}

.token-usage-tip li {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
}

.token-usage-tip em {
  font-style: normal;
  font-variant-numeric: tabular-nums;
  opacity: 0.92;
}
</style>
