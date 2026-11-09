/**
 * Live sync via EventSource ``/api/v1/events``.
 *
 * Every open tab connects its own stream — do **not** rebroadcast SSE on
 * BroadcastChannel. That used to apply ``message.delta`` twice (same tab echo
 * + peer tabs that also have EventSource) and duplicated streamed tokens until
 * a hard refresh reloaded the clean DB text.
 */
import { api } from "./api";
import { state, pushNotification, applyEvent } from "./store";

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
