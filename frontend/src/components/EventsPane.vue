<template>
  <div class="events-pane">
    <p class="events-tz">{{ tzLabel }}</p>

    <section class="events-section">
      <h3>{{ t("events.schedules") }}</h3>
      <p v-if="!schedules.length && !loading" class="hint">{{ t("events.schedulesEmpty") }}</p>
      <ul v-else class="events-list">
        <li v-for="s in schedules" :key="s.id" class="events-item">
          <div class="events-item-main">
            <label class="events-toggle">
              <input
                type="checkbox"
                role="switch"
                :checked="!!s.enabled"
                :aria-label="s.enabled ? t('events.on') : t('events.off')"
                @change="toggleSchedule(s, $event)"
              />
            </label>
            <button
              type="button"
              class="events-name"
              :title="t('events.showInstruction')"
              @click="openInstruction(s.name, s.instruction, 'schedule')"
            >
              {{ s.name }}
            </button>
            <code class="events-cron" :title="s.cron_utc ? `UTC ${s.cron_utc}` : ''">{{ s.cron }}</code>
            <span class="events-badge">{{ s.timezone || t("events.local") }}</span>
            <span v-if="!s.recurring" class="events-badge once">{{ t("events.oneShot") }}</span>
          </div>
          <div class="events-meta-row">
            <div class="events-meta">
              <span>{{ t("events.nextRun") }}: {{ formatWhen(s.next_run_at, s.timezone) }}</span>
            </div>
            <button
              type="button"
              class="events-icon-btn danger"
              :aria-label="t('events.delete')"
              :title="t('events.delete')"
              @click="removeSchedule(s)"
            >
              <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
                <path d="M5 7h14M9 7V5h6v2M8 7l1 12h6l1-12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>
        </li>
      </ul>
    </section>

    <section class="events-section">
      <h3>{{ t("events.webhooks") }}</h3>
      <p v-if="!webhooks.length && !loading" class="hint">{{ t("events.webhooksEmpty") }}</p>
      <ul v-else class="events-list">
        <li v-for="w in webhooks" :key="w.id" class="events-item">
          <div class="events-item-main">
            <label class="events-toggle">
              <input
                type="checkbox"
                role="switch"
                :checked="!!w.enabled"
                :aria-label="w.enabled ? t('events.on') : t('events.off')"
                @change="toggleWebhook(w, $event)"
              />
            </label>
            <button
              type="button"
              class="events-name"
              :title="t('events.showInstruction')"
              @click="openInstruction(w.name, w.instruction, 'webhook')"
            >
              {{ w.name }}
            </button>
            <div class="events-item-actions">
              <button
                type="button"
                class="events-icon-btn"
                :aria-label="copiedId === w.id ? t('events.copied') : t('events.copyUrl')"
                :title="copiedId === w.id ? t('events.copied') : t('events.copyUrl')"
                @click="copyUrl(w)"
              >
                <svg v-if="copiedId === w.id" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12.5 10 17.5 19 7.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                <svg v-else viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="8" y="8" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.7" />
                  <path d="M6 16V6a2 2 0 0 1 2-2h10" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
                </svg>
              </button>
              <button
                type="button"
                class="events-icon-btn danger"
                :aria-label="t('events.delete')"
                :title="t('events.delete')"
                :aria-expanded="confirmWebhookId === w.id"
                @click="confirmWebhookId = confirmWebhookId === w.id ? '' : w.id"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 7h14M9 7V5h6v2M8 7l1 12h6l1-12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
            </div>
          </div>
          <div v-if="confirmWebhookId === w.id" class="inline-confirm" role="group">
            <p>{{ t("events.confirmDelete", { name: w.name }) }}</p>
            <button
              class="danger"
              type="button"
              :disabled="deletingWebhookId === w.id"
              @click="removeWebhook(w)"
            >
              {{ t("confirm.deleteBotGo") }}
            </button>
            <button type="button" :disabled="deletingWebhookId === w.id" @click="confirmWebhookId = ''">
              {{ t("files.cancel") }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <EventInstructionModal
      :open="!!instructionModal"
      :name="instructionModal?.name || ''"
      :instruction="instructionModal?.instruction || ''"
      :kind="instructionModal?.kind || 'webhook'"
      @close="closeInstruction"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { api } from "../api";
import { state } from "../store";
import EventInstructionModal from "./EventInstructionModal.vue";

const props = defineProps({ bot: { type: Object, required: true } });
const { t, locale } = useI18n();

const schedules = ref([]);
const webhooks = ref([]);
const loading = ref(false);
const copiedId = ref("");
const confirmWebhookId = ref("");
const deletingWebhookId = ref("");
const instructionModal = ref(null);
const clock = ref({ timezone: "", utc_offset: "" });

function openInstruction(name, instruction, kind) {
  instructionModal.value = {
    name: String(name || "").trim() || "—",
    instruction: String(instruction || ""),
    kind,
  };
}

function closeInstruction() {
  instructionModal.value = null;
}

const tzLabel = computed(() =>
  t("events.timezone", {
    tz: clock.value.timezone || "…",
    offset: clock.value.utc_offset || "",
  })
);

async function reload() {
  if (!props.bot?.name) return;
  loading.value = true;
  try {
    const [s, w, clk] = await Promise.all([
      api.listSchedules(props.bot.name),
      api.listWebhooks(props.bot.name),
      api.clock().catch(() => null),
    ]);
    schedules.value = Array.isArray(s) ? s : [];
    webhooks.value = Array.isArray(w) ? w : [];
    if (clk?.timezone) clock.value = clk;
    else if (schedules.value[0]?.timezone) {
      clock.value = {
        timezone: schedules.value[0].timezone,
        utc_offset: schedules.value[0].utc_offset || "",
      };
    }
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function formatWhen(iso, tz) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const opts = {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    };
    if (tz && tz !== "local") opts.timeZone = tz;
    return d.toLocaleString(locale.value, opts);
  } catch {
    try {
      return new Date(iso).toLocaleString(locale.value, { hour12: false });
    } catch {
      return iso;
    }
  }
}

async function toggleSchedule(s, ev) {
  const next = !!ev.target.checked;
  const prev = s.enabled;
  s.enabled = next;
  try {
    const updated = await api.patchSchedule(props.bot.name, s.id, { enabled: next });
    Object.assign(s, updated);
  } catch (e) {
    s.enabled = prev;
    ev.target.checked = prev;
    alert(e.message);
  }
}

async function removeSchedule(s) {
  if (!confirm(t("events.confirmDelete", { name: s.name }))) return;
  try {
    await api.deleteSchedule(props.bot.name, s.id);
    schedules.value = schedules.value.filter((x) => x.id !== s.id);
  } catch (e) {
    alert(e.message);
  }
}

async function toggleWebhook(w, ev) {
  const next = !!ev.target.checked;
  const prev = w.enabled;
  w.enabled = next;
  try {
    const updated = await api.patchWebhook(props.bot.name, w.id, { enabled: next });
    Object.assign(w, updated);
  } catch (e) {
    w.enabled = prev;
    ev.target.checked = prev;
    alert(e.message);
  }
}

async function removeWebhook(w) {
  deletingWebhookId.value = w.id;
  try {
    await api.deleteWebhook(props.bot.name, w.id);
    webhooks.value = webhooks.value.filter((x) => x.id !== w.id);
    if (confirmWebhookId.value === w.id) confirmWebhookId.value = "";
  } catch (e) {
    alert(e.message);
  } finally {
    if (deletingWebhookId.value === w.id) deletingWebhookId.value = "";
  }
}

async function copyUrl(w) {
  // Always use the browser origin (same host/scheme as the UI). Server-built
  // ``w.url`` often is ``http://127.0.0.1:…`` and yields a 301 (e.g. to HTTPS)
  // that strips the Bearer / turns POST into GET — fire then looks like it "worked"
  // for the agent while the caller only saw a redirect.
  const path = (w.url_path || "/api/v1/hooks").replace(/\/+$/, "") || "/api/v1/hooks";
  const origin = String(location.origin || "").replace(/\/+$/, "");
  const endpoint = `${origin}${path.startsWith("/") ? path : `/${path}`}`;
  const token = w.token || "";
  const text = token
    ? `curl -sS -X POST '${endpoint}' -H 'Authorization: Bearer ${token}' -H 'Content-Type: application/json' -d '{}'`
    : endpoint;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
  copiedId.value = w.id;
  setTimeout(() => {
    if (copiedId.value === w.id) copiedId.value = "";
  }, 1500);
}

function upsertSchedule(row) {
  if (!row?.id) return;
  const i = schedules.value.findIndex((s) => s.id === row.id);
  if (i >= 0) schedules.value[i] = row;
  else schedules.value = [...schedules.value, row];
  if (row.timezone) {
    clock.value = {
      timezone: row.timezone,
      utc_offset: row.utc_offset || clock.value.utc_offset,
    };
  }
}

function upsertWebhook(row) {
  if (!row?.id) return;
  const i = webhooks.value.findIndex((w) => w.id === row.id);
  if (i >= 0) webhooks.value[i] = row;
  else webhooks.value = [...webhooks.value, row];
}

onMounted(reload);
watch(() => props.bot?.name, reload);
watch(
  () => state.userTimezone,
  (tz, prev) => {
    if (!tz || tz === prev) return;
    reload();
  },
);
watch(
  () => state.eventsFeed,
  (ev) => {
    if (!ev) return;
    const name = props.bot?.name;
    const owner = ev.schedule?.bot || ev.webhook?.bot || ev.bot;
    if (!name || owner !== name) return;
    if (ev.type === "schedule.updated" && ev.schedule) upsertSchedule(ev.schedule);
    else if (ev.type === "schedule.deleted" && ev.id) {
      schedules.value = schedules.value.filter((s) => s.id !== ev.id);
    } else if (ev.type === "webhook.updated" && ev.webhook) upsertWebhook(ev.webhook);
    else if (ev.type === "webhook.deleted" && ev.id) {
      webhooks.value = webhooks.value.filter((w) => w.id !== ev.id);
    }
  },
);

defineExpose({ reload });
</script>
