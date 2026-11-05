<template>
  <div class="terminal-pane">
    <div v-if="bot.capability === 'none'" class="empty">
      <p>{{ t("terminal.needCapability") }}</p>
    </div>
    <div v-else-if="waking || deskSleeping" class="empty desk-wake">
      <p>{{ wakeError || t("desk.waking") }}</p>
      <button
        v-if="wakeError"
        class="btn primary"
        type="button"
        :disabled="waking"
        @click="wake"
      >
        {{ t("desk.wakeRetry") }}
      </button>
    </div>
    <div v-else-if="!deskRunning" class="empty">
      <p>{{ t("terminal.needDesk") }}</p>
    </div>
    <div
      v-else
      ref="hostEl"
      class="term-host"
      @click="focusTerm"
    />
  </div>
</template>

<script setup>
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useI18n } from "vue-i18n";
import { wakeBotDesk } from "../deskWake";

const props = defineProps({
  bot: { type: Object, required: true },
  /** True when the Terminal tab is visible — triggers connect / refocus. */
  active: { type: Boolean, default: false },
});
const { t } = useI18n();

const hostEl = ref(null);
const status = ref("idle");
const waking = ref(false);
const wakeError = ref("");
const deskRunning = computed(() => (props.bot.desk?.state || "") === "running");
const deskSleeping = computed(() => (props.bot.desk?.state || "") === "sleeping");

let term = null;
let fit = null;
let ws = null;
let ro = null;
let disposed = false;

function wsUrl(botName) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/terminal/${encodeURIComponent(botName)}`;
}

function focusTerm() {
  term?.focus();
}

function sendResize() {
  if (!ws || ws.readyState !== WebSocket.OPEN || !term) return;
  ws.send(
    JSON.stringify({
      type: "resize",
      cols: term.cols,
      rows: term.rows,
    }),
  );
}

function disposeSocket() {
  if (ws) {
    try {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.close();
    } catch {
      /* ignore */
    }
    ws = null;
  }
}

function disposeTerm() {
  disposeSocket();
  if (ro) {
    ro.disconnect();
    ro = null;
  }
  if (term) {
    try {
      term.dispose();
    } catch {
      /* ignore */
    }
    term = null;
    fit = null;
  }
}

function connect() {
  if (disposed || !deskRunning.value || !hostEl.value) return;
  disposeSocket();
  status.value = "connecting";

  if (!term) {
    term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: 'ui-monospace, "Cascadia Code", "SF Mono", Menlo, monospace',
      theme: {
        background: "#1c1c1e",
        foreground: "#f2f2f7",
        cursor: "#f08c12",
        selectionBackground: "#f08c1244",
      },
      allowProposedApi: true,
      convertEol: false,
    });
    fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostEl.value);
    term.onData((data) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });
    ro = new ResizeObserver(() => {
      try {
        fit?.fit();
        sendResize();
      } catch {
        /* ignore */
      }
    });
    ro.observe(hostEl.value);
  }

  const socket = new WebSocket(wsUrl(props.bot.name));
  ws = socket;
  socket.binaryType = "arraybuffer";

  socket.onopen = () => {
    if (ws !== socket) return;
    status.value = "open";
    try {
      fit?.fit();
    } catch {
      /* ignore */
    }
    sendResize();
    if (props.active) focusTerm();
  };

  socket.onmessage = (ev) => {
    if (!term) return;
    if (typeof ev.data === "string") {
      term.write(ev.data);
      return;
    }
    term.write(new Uint8Array(ev.data));
  };

  socket.onclose = () => {
    if (ws !== socket) return;
    status.value = "closed";
    ws = null;
  };

  socket.onerror = () => {
    if (ws !== socket) return;
    status.value = "closed";
  };
}

function ensureSession() {
  if (!deskRunning.value || !hostEl.value) return;
  if (status.value === "open" && ws?.readyState === WebSocket.OPEN) {
    try {
      fit?.fit();
    } catch {
      /* ignore */
    }
    sendResize();
    focusTerm();
    return;
  }
  if (term) {
    try {
      term.reset();
    } catch {
      /* ignore */
    }
  }
  connect();
}

async function wake() {
  if (waking.value || props.bot.capability === "none") return;
  if (!deskSleeping.value && deskRunning.value) return;
  if (!deskSleeping.value) return;
  waking.value = true;
  wakeError.value = "";
  try {
    await wakeBotDesk(props.bot.name);
  } catch (e) {
    wakeError.value = e.message || String(e);
  } finally {
    waking.value = false;
  }
}

async function ensureAwakeIfNeeded() {
  if (!props.active) return;
  if (props.bot.capability === "none") return;
  if (deskSleeping.value) await wake();
}

watch(
  () => props.bot.name,
  async () => {
    disposeTerm();
    status.value = "idle";
    wakeError.value = "";
    await nextTick();
    await ensureAwakeIfNeeded();
    if (props.active && deskRunning.value) ensureSession();
  },
);

watch(deskRunning, async (ok) => {
  if (!ok) {
    disposeTerm();
    status.value = "idle";
    return;
  }
  await nextTick();
  if (props.active) ensureSession();
});

watch(deskSleeping, async (asleep) => {
  if (asleep && props.active) await wake();
});

watch(
  () => props.active,
  async (on) => {
    if (!on) return;
    await nextTick();
    await ensureAwakeIfNeeded();
    ensureSession();
  },
);

onMounted(async () => {
  await nextTick();
  await ensureAwakeIfNeeded();
  if (props.active && deskRunning.value) ensureSession();
});

onBeforeUnmount(() => {
  disposed = true;
  disposeTerm();
});

defineExpose({ focusTerm, ensureSession });
</script>
