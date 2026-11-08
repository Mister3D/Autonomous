<template>
  <div class="action-list">
    <div v-for="item in rows" :key="item.id" class="action-row">
      <button
        type="button"
        :class="{ danger: item.danger }"
        :disabled="item.disabled"
        @click="onRow(item)"
      >
        {{ item.label }}
      </button>
      <span
        v-if="item.confirm && armed === item.id"
        class="action-confirm-wrap"
        @pointerenter="tip = item.id"
        @pointerleave="tip = ''"
        @focusin="tip = item.id"
        @focusout="tip = ''"
      >
        <button
          class="action-confirm"
          type="button"
          :disabled="busy"
          :aria-label="t('confirm.confirmAction')"
          @click="run(item.id)"
        >
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path
              d="M3.2 8.2 6.4 11.4 12.8 4.6"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
        <span v-if="tip === item.id" class="action-confirm-tip" role="tooltip">{{
          t("confirm.confirmAction")
        }}</span>
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { api } from "../api";
import { state } from "../store";

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();
const router = useRouter();
const armed = ref("");
const tip = ref("");
const busy = ref(false);
const exporting = ref(false);

/** A desktop exists (running, asleep, starting, or failed). Absent means no VM. */
const deskOn = computed(() => {
  const st = props.bot.desk?.state;
  return st === "creating" || st === "running" || st === "sleeping" || st === "error";
});

const rows = computed(() => {
  const list = [
    {
      id: "clear",
      label: t("manage.clearChat"),
      confirm: t("confirm.clearChat"),
    },
    {
      id: "export",
      label: exporting.value ? t("manage.exportingPdf") : t("manage.exportPdf"),
      disabled: exporting.value,
    },
  ];
  if (deskOn.value) {
    list.push(
      {
        id: "restart",
        label: t("manage.restartDesk"),
        confirm: t("confirm.restartDesk"),
      },
      {
        id: "reset",
        label: t("manage.resetDesk"),
        confirm: t("confirm.reset"),
      },
      {
        id: "vm",
        label: t("manage.removeVm"),
        confirm: t("confirm.removeVm"),
      },
    );
  }
  list.push({
    id: "delete",
    label: busy.value && armed.value === "delete" ? t("manage.deletingBot") : t("manage.deleteBot"),
    confirm: t("confirm.deleteBotInline", { name: props.bot.label || props.bot.name }),
    danger: true,
    disabled: busy.value,
  });
  return list;
});

watch(
  () => props.bot?.name,
  () => {
    armed.value = "";
    tip.value = "";
    busy.value = false;
    exporting.value = false;
  },
);

watch(deskOn, (on) => {
  if (!on && (armed.value === "restart" || armed.value === "reset" || armed.value === "vm")) {
    armed.value = "";
  }
});

function applyBot(bot) {
  if (!bot?.name) return;
  const i = state.bots.findIndex((b) => b.name === bot.name);
  if (i >= 0) state.bots[i] = bot;
}

function onRow(item) {
  if (item.disabled) return;
  if (!item.confirm) {
    if (item.id === "export") exportPdf();
    return;
  }
  armed.value = armed.value === item.id ? "" : item.id;
  tip.value = "";
}

async function clearChat() {
  const name = props.bot.name;
  await api.clearMessages(name);
  // Server wipe does not emit SSE; drop the thread so the pane and the rail update.
  state.messages[name] = [];
}

async function exportPdf() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const { blob, filename } = await api.exportDiscussionPdf(props.bot.name);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    exporting.value = false;
  }
}

async function run(id) {
  if (busy.value || armed.value !== id) return;
  busy.value = true;
  try {
    if (id === "clear") await clearChat();
    else if (id === "restart") await api.deskRestart(props.bot.name);
    else if (id === "reset") await api.deskReset(props.bot.name);
    else if (id === "vm") await setCap("none");
    else if (id === "delete") await remove();
    armed.value = "";
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    busy.value = false;
  }
}

async function setCap(level) {
  const bot = await api.setCapability(props.bot.name, level);
  applyBot(bot);
  if (level === "none" && (state.tab === "terminal" || state.tab === "screen")) {
    state.tab = "discussion";
  }
}

async function remove() {
  const name = props.bot.name;
  await api.deleteBot(name);
  state.bots = state.bots.filter((b) => b.name !== name);
  delete state.messages[name];
  const next = state.bots[0]?.name || null;
  state.currentBot = next;
  if (next) {
    state.tab = "discussion";
    router.push(`/b/${encodeURIComponent(next)}/discussion`);
  } else {
    router.push("/");
  }
}
</script>
