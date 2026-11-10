import { reactive } from "vue";
import { i18n } from "./i18n";
import { uid } from "./uid";

export const state = reactive({
  authenticated: false,
  /** Generated install password still in force — UI stays on the change form. */
  mustChangePassword: false,
  bots: [],
  currentBot: null,
  tab: "discussion",
  panel: "details",
  inspectorOpen: false,
  messages: {},
  /** botName → true when assistant activity arrived while not selected */
  unread: {},
  terminal: {},
  jobs: {},
  notifications: [],
  humanControl: false,
  keepControl: false,
  createOpen: false,
  /** Legacy; desk agent requests stay on the chat card (no modal). */
  deskAuthRequest: null,
  /** One-shot: restore scrubbed user text into the composer after secret report. */
  composerRestore: null,
  /** Latest schedule/webhook SSE payload so the Events tab can refresh live. */
  eventsFeed: null,
  /** Latest ~/shared mutation so the Files tab can refresh live. */
  filesFeed: null,
  /** Set when the user saves a timezone in Settings, so Events can reload. */
  userTimezone: null,
  piStatus: null,
  /** GET /setup/status → { ready, gate, checks[] } (null until loaded). */
  setup: null,
  /** Bot slug waiting for the onboarding language answer before prefs script. */
  firstChatPrefsPending: null,
  loading: false,
});

let setupInflight = null;
/** Refresh first-run setup checks (server caches ~10 s unless force). */
export function refreshSetup(force = false) {
  if (setupInflight && !force) return setupInflight;
  setupInflight = (async () => {
    const { api } = await import("./api");
    try {
      state.setup = await api.setupStatus(force);
    } catch {
      /* keep last value */
    } finally {
      setupInflight = null;
    }
    return state.setup;
  })();
  return setupInflight;
}

/** Bot creation allowed? (gate off → always; unknown yet → no). */
export function setupReady() {
  const s = state.setup;
  if (!s) return false;
  return !!s.ready || s.gate === false;
}

export function markBotRead(name) {
  if (!name) return;
  if (state.unread[name]) state.unread[name] = false;
}

export function markBotUnread(name) {
  if (!name) return;
  if (name === state.currentBot) return;
  state.unread[name] = true;
}

/** Local optimistic send ids (ChatPane / setup first-chat). */
export function isOptimisticMessageId(id) {
  return typeof id === "string" && id.startsWith("tmp-");
}

/**
 * Drop optimistic bubbles that match a server message (same role + content).
 * Prevents doubles when SSE / loadMessages arrive before the HTTP replace.
 * Returns ``{ hadQueued, queueOrd }`` from the twin so the file order stays stable
 * when server ``created_at`` would otherwise reshuffle the queue.
 */
export function dropOptimisticDupes(bot, serverMsg) {
  const empty = { hadQueued: false, queueOrd: null };
  if (!bot || !serverMsg?.id || isOptimisticMessageId(serverMsg.id)) return empty;
  const list = state.messages[bot];
  if (!Array.isArray(list) || !list.length) return empty;
  const role = serverMsg.role;
  const content = String(serverMsg.content || "");
  let hadQueued = false;
  let queueOrd = null;
  for (let i = list.length - 1; i >= 0; i--) {
    const m = list[i];
    if (!isOptimisticMessageId(m?.id)) continue;
    if (m.role !== role) continue;
    if (String(m.content || "") !== content) continue;
    if (m.meta?.queued) hadQueued = true;
    const ord = Number(m.meta?.queue_ord);
    if (Number.isFinite(ord)) queueOrd = ord;
    list.splice(i, 1);
  }
  return { hadQueued, queueOrd };
}

/** Keep « En file » + stable ``queue_ord`` from the optimistic twin. */
export function withInheritedQueued(serverMsg, inherit) {
  const hadQueued = !!inherit?.hadQueued;
  const queueOrd = inherit?.queueOrd;
  if (!serverMsg) return serverMsg;
  const meta = { ...(serverMsg.meta || {}) };
  let changed = false;
  if (hadQueued && !meta.queued && !meta.mid_run) {
    meta.queued = true;
    changed = true;
  }
  if (Number.isFinite(queueOrd) && !Number.isFinite(Number(meta.queue_ord))) {
    meta.queue_ord = queueOrd;
    changed = true;
  }
  return changed ? { ...serverMsg, meta } : serverMsg;
}

/** Preserve local ``queue_ord`` across SSE/HTTP merges. */
export function withPreservedQueueOrd(local, remote) {
  if (!remote) return remote;
  const ord = Number(local?.meta?.queue_ord);
  if (!Number.isFinite(ord)) return remote;
  if (Number.isFinite(Number(remote.meta?.queue_ord))) return remote;
  return {
    ...remote,
    meta: { ...(remote.meta || {}), queue_ord: ord },
  };
}

/**
 * Merge a live streaming bubble with a possibly-stale HTTP/SSE snapshot.
 * Prefer the longer body while either side is still streaming so mid-turn
 * navigation / DB flushes cannot truncate text already shown via deltas.
 * A finished remote message (`streaming: false`) always wins.
 */
export function preferLiveStreamingMessage(local, remote) {
  if (!local) return remote;
  if (!remote) return local;
  const remoteDone = remote.meta && remote.meta.streaming === false;
  if (remoteDone && !local.meta?.streaming) return remote;
  if (remoteDone && String(remote.content || "").length >= String(local.content || "").length) {
    return remote;
  }
  const localStreaming = !!local.meta?.streaming;
  const remoteStreaming = !!remote.meta?.streaming;
  if (!localStreaming && !remoteStreaming) return remote;
  const localLen = String(local.content || "").length;
  const remoteLen = String(remote.content || "").length;
  if (localLen > remoteLen) {
    return {
      ...remote,
      content: local.content,
      meta: {
        ...(remote.meta || {}),
        ...(local.meta || {}),
        streaming: true,
      },
    };
  }
  return {
    ...remote,
    meta: {
      ...(remote.meta || {}),
      streaming: localStreaming || remoteStreaming || !!remote.meta?.streaming,
    },
  };
}

export function pushNotification(text, kind = "info") {
  const id = uid();
  state.notifications.unshift({ id, text, kind, ts: Date.now() });
  if (state.notifications.length > 20) state.notifications.pop();
  setTimeout(() => {
    const i = state.notifications.findIndex((n) => n.id === id);
    if (i >= 0) state.notifications.splice(i, 1);
  }, 6000);
}

export function applyEvent(envelope, { fromBroadcast = false } = {}) {
  if (!envelope || !envelope.type) return;
  const { type, data } = envelope;
  const t = i18n.global.t;

  if (type === "bot.created" && data.bot) {
    const exists = state.bots.some((b) => b.name === data.bot.name);
    if (!exists) state.bots.push(data.bot);
    else {
      const i = state.bots.findIndex((b) => b.name === data.bot.name);
      state.bots[i] = data.bot;
    }
    if (!fromBroadcast) {
      pushNotification(
        t("notify.botCreated", { name: data.bot.label || data.bot.name })
      );
    }
  }
  if (type === "bot.updated" && data.bot) {
    const i = state.bots.findIndex((b) => b.name === data.bot.name);
    if (i >= 0) state.bots[i] = data.bot;
    if (state.currentBot === data.bot.name) {
      /* keep selection */
    }
  }
  if (type === "bot.deleted" && data.name) {
    state.bots = state.bots.filter((b) => b.name !== data.name);
    delete state.unread[data.name];
    if (state.currentBot === data.name) state.currentBot = state.bots[0]?.name || null;
    if (!fromBroadcast) pushNotification(t("notify.botDeleted", { name: data.name }));
  }
  if (type === "message.created" && data.message) {
    const bot = data.message.bot;
    if (!state.messages[bot]) state.messages[bot] = [];
    const inherit = dropOptimisticDupes(bot, data.message);
    const incoming = withInheritedQueued(data.message, inherit);
    data.message = incoming;
    if (!state.messages[bot].some((m) => m.id === incoming.id)) {
      state.messages[bot].push(incoming);
    }
    // Queued drafts stay out of "last activity" until they actually fire.
    if (!incoming.meta?.queued) {
      const i = state.bots.findIndex((b) => b.name === bot);
      if (i >= 0 && data.message.created_at) {
        const prev = state.bots[i].last_message_at || "";
        if (data.message.created_at > prev) {
          state.bots[i] = { ...state.bots[i], last_message_at: data.message.created_at };
        }
      }
    }
    // Assistant turn started while viewing another bot → notify pastille.
    if (
      data.message.role === "assistant" &&
      !data.message.meta?.queued &&
      bot !== state.currentBot
    ) {
      markBotUnread(bot);
    }
  }
  if (type === "message.delta" && data.id && data.bot) {
    if (!state.messages[data.bot]) state.messages[data.bot] = [];
    const list = state.messages[data.bot];
    const i = list.findIndex((m) => m.id === data.id);
    if (i >= 0) {
      const prev = list[i];
      list[i] = {
        ...prev,
        content: (prev.content || "") + (data.delta || ""),
        meta: { ...(prev.meta || {}), streaming: true },
      };
    } else {
      // Entering a bot mid-stream can miss message.created — don't drop deltas.
      list.push({
        id: data.id,
        bot: data.bot,
        role: "assistant",
        content: data.delta || "",
        created_at: new Date().toISOString(),
        meta: { streaming: true },
      });
    }
  }
  if (type === "message.updated" && data.message) {
    const bot = data.message.bot;
    if (!state.messages[bot]) state.messages[bot] = [];
    const list = state.messages[bot];
    const inherit = dropOptimisticDupes(bot, data.message);
    let incoming = withInheritedQueued(data.message, inherit);
    data.message = incoming;
    const i = list.findIndex((m) => m.id === incoming.id);
    const released =
      i >= 0 &&
      list[i].meta?.queued &&
      !incoming.meta?.queued;
    if (i >= 0) {
      incoming = withPreservedQueueOrd(list[i], incoming);
      data.message = incoming;
      if (released) {
        // Leave the early "draft" slot and append as a real turn.
        list.splice(i, 1);
        list.push(incoming);
      } else {
        // Mid-stream DB flush can lag behind SSE deltas already applied.
        list[i] = preferLiveStreamingMessage(list[i], incoming);
      }
    } else {
      list.push(incoming);
    }
    if (released || !data.message.meta?.queued) {
      const bi = state.bots.findIndex((b) => b.name === bot);
      if (bi >= 0 && data.message.created_at) {
        const prev = state.bots[bi].last_message_at || "";
        if (data.message.created_at > prev) {
          state.bots[bi] = {
            ...state.bots[bi],
            last_message_at: data.message.created_at,
          };
        }
      }
    }
    if (
      data.message.role === "assistant" &&
      !data.message.meta?.queued &&
      !data.message.meta?.streaming &&
      bot !== state.currentBot
    ) {
      markBotUnread(bot);
    }
  }
  if (type === "message.deleted" && data.bot && data.id) {
    const list = state.messages[data.bot];
    if (list) {
      state.messages[data.bot] = list.filter((m) => m.id !== data.id);
    }
  }
  if (type === "message.cleared" && data.bot) {
    state.messages[data.bot] = [];
    const i = state.bots.findIndex((b) => b.name === data.bot);
    if (i >= 0) {
      state.bots[i] = { ...state.bots[i], last_message_at: null };
    }
  }
  if (type === "vault.user_secret_report" && data.bot) {
    // Original user text for the composer only — never re-persist in history.
    state.composerRestore = {
      bot: data.bot,
      text: String(data.restore_text || ""),
      ts: Date.now(),
    };
  }
  if (type === "desk.updated" && data.bot) {
    const i = state.bots.findIndex((b) => b.name === data.bot);
    if (i >= 0) {
      const desk = data.desk;
      state.bots[i] = {
        ...state.bots[i],
        desk,
        status: desk?.state === "creating" ? "waiting" : state.bots[i].status,
      };
    }
  }
  if (type === "job.updated" && data.job) {
    state.jobs[data.job.id] = data.job;
  }
  if (type === "terminal.created" && data.entry) {
    const bot = data.entry.bot;
    if (!state.terminal[bot]) state.terminal[bot] = [];
    if (!state.terminal[bot].some((e) => e.id === data.entry.id)) {
      state.terminal[bot].push(data.entry);
    }
  }
  if (
    type === "schedule.updated" ||
    type === "schedule.deleted" ||
    type === "webhook.updated" ||
    type === "webhook.deleted"
  ) {
    state.eventsFeed = { type, ...data, at: Date.now() };
  }
  if (type === "files.changed" && data.bot) {
    state.filesFeed = { type, ...data, at: Date.now() };
  }
  if (type === "notification" && data.kind) {
    if (data.kind === "desk.running" && !fromBroadcast) {
      pushNotification(t("notify.deskRunning", { bot: data.bot }));
      if (state.deskAuthRequest?.bot === data.bot) state.deskAuthRequest = null;
    }
    if (data.kind === "desk.creating" && !fromBroadcast) {
      pushNotification(t("notify.deskCreating", { bot: data.bot }));
    }
    if (data.kind === "desk.request" && data.bot && !fromBroadcast) {
      // Carte chat seulement — pas d’ouverture auto de CreateDeskModal.
      pushNotification(t("notify.deskRequest", { bot: data.bot }));
    }
    if (data.kind === "device.pairing" && !fromBroadcast) {
      pushNotification(t("notify.devicePairing", { name: data.name, code: data.code }));
    }
    if (
      (data.kind === "bot.busy" || data.kind === "bot.waiting") &&
      data.bot
    ) {
      const name = data.bot.name || data.bot;
      const i = state.bots.findIndex((b) => b.name === name);
      if (i >= 0 && data.bot.name) state.bots[i] = data.bot;
    }
  }
}

export function currentBotObj() {
  return state.bots.find((b) => b.name === state.currentBot) || null;
}
