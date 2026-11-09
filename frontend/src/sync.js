/**
 * Cross-tab sync: one EventSource to /api/v1/events + BroadcastChannel
 * so all open tabs (up to many) see bot create / run / notifications.
 */
import { api } from "./api";
import { state, pushNotification, applyEvent } from "./store";

const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("autonomous") : null;

let es = null;

function onEvent(ev) {
  let data = {};
  try {
    data = JSON.parse(ev.data || "{}");
  } catch {
    data = {};
  }
  const envelope = { type: ev.type || "message", data };
  if (envelope.type === "ui.focus" && data.path) {
    window.dispatchEvent(new CustomEvent("autonomous-focus", { detail: data }));
  }
  applyEvent(envelope);
  if (channel) {
    channel.postMessage(envelope);
  }
}

export function startGlobalSync() {
  if (channel) {
    channel.onmessage = (msg) => {
      // Ignore echoes from this tab if we already applied; still apply for other tabs' local actions
      applyEvent(msg.data, { fromBroadcast: true });
    };
  }
}

export function connectEvents() {
  // Navigation calls this on every route. Tearing the stream down each time
  // aborts the in-flight GET and the console fills with ERR_EMPTY_RESPONSE.
  if (es && es.readyState !== EventSource.CLOSED) return;
  es = new EventSource("/api/v1/events", { withCredentials: true });
  const types = [
    "ping",
    "bot.created",
    "bot.updated",
    "bot.deleted",
    "message.created",
    "message.delta",
    "message.updated",
    "message.deleted",
    "message.cleared",
    "pi.status",
    "desk.updated",
    "job.updated",
    "terminal.created",
    "notification",
    "schedule.updated",
    "schedule.deleted",
    "webhook.updated",
    "webhook.deleted",
    "vault.user_secret_report",
    "files.changed",
    "ui.focus",
  ];
  for (const t of types) {
    es.addEventListener(t, onEvent);
  }
  es.onerror = () => {
    // Browser reconnects automatically for EventSource
  };
}

export function disconnectEvents() {
  if (es) {
    es.close();
    es = null;
  }
}

export async function refreshBots() {
  state.bots = await api.listBots();
}

export { pushNotification };
