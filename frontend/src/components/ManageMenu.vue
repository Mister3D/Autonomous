<template>
  <div class="action-list">
    <button type="button" @click="clearChat">{{ t("manage.clearChat") }}</button>
    <button type="button" :disabled="exporting" @click="exportPdf">
      {{ exporting ? t("manage.exportingPdf") : t("manage.exportPdf") }}
    </button>
    <button type="button" @click="restart">{{ t("manage.restartDesk") }}</button>
    <button type="button" @click="reset">{{ t("manage.resetDesk") }}</button>
    <button type="button" @click="setCap('none')">{{ t("manage.removeVm") }}</button>

    <template v-if="!confirmingDelete">
      <button class="danger" type="button" @click="confirmingDelete = true">
        {{ t("manage.deleteBot") }}
      </button>
    </template>
    <div v-else class="inline-confirm" role="group">
      <p>{{ t("confirm.deleteBotInline", { name: bot.name }) }}</p>
      <button
        class="danger"
        type="button"
        :disabled="deleting"
        @click="remove"
      >
        {{ deleting ? t("manage.deletingBot") : t("confirm.deleteBotGo") }}
      </button>
      <button type="button" :disabled="deleting" @click="confirmingDelete = false">
        {{ t("files.cancel") }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { api } from "../api";
import { state } from "../store";

const props = defineProps({ bot: { type: Object, required: true } });
const { t } = useI18n();
const router = useRouter();
const confirmingDelete = ref(false);
const deleting = ref(false);
const exporting = ref(false);

watch(
  () => props.bot?.name,
  () => {
    confirmingDelete.value = false;
    deleting.value = false;
    exporting.value = false;
  }
);

function applyBot(bot) {
  if (!bot?.name) return;
  const i = state.bots.findIndex((b) => b.name === bot.name);
  if (i >= 0) state.bots[i] = bot;
}

async function clearChat() {
  await api.clearMessages(props.bot.name);
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

async function restart() {
  try {
    await api.deskRestart(props.bot.name);
  } catch (e) {
    alert(e.message);
  }
}

async function reset() {
  if (!confirm(t("confirm.reset"))) return;
  await api.deskReset(props.bot.name);
}

async function setCap(level) {
  try {
    const bot = await api.setCapability(props.bot.name, level);
    applyBot(bot);
    if (level === "none" && (state.tab === "terminal" || state.tab === "screen")) {
      state.tab = "discussion";
    }
  } catch (e) {
    alert(e.message || String(e));
  }
}

async function remove() {
  if (deleting.value) return;
  const name = props.bot.name;
  deleting.value = true;
  try {
    await api.deleteBot(name);
    // SSE bot.deleted also updates the list; ensure local nav even if event is slow.
    state.bots = state.bots.filter((b) => b.name !== name);
    delete state.messages[name];
    const next = state.bots[0]?.name || null;
    state.currentBot = next;
    confirmingDelete.value = false;
    if (next) {
      state.tab = "discussion";
      router.push(`/b/${encodeURIComponent(next)}/discussion`);
    } else {
      router.push("/");
    }
  } catch (e) {
    alert(e.message || String(e));
  } finally {
    deleting.value = false;
  }
}
</script>
