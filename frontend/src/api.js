const BASE = "/api/v1";

async function request(path, options = {}) {
  const opts = {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  };
  if (opts.body instanceof FormData) {
    // Let the browser set multipart boundary.
    if (opts.headers && opts.headers["Content-Type"]) {
      delete opts.headers["Content-Type"];
    }
  } else if (opts.body && typeof opts.body === "object") {
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(`${BASE}${path}`, opts);
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const err = new Error(formatApiError(data, res.statusText));
    err.status = res.status;
    err.data = data;
    err.code =
      (data &&
        typeof data === "object" &&
        (data.code || data.error_code || data.errors?.code)) ||
      "";
    throw err;
  }
  return data;
}

/** flask-smorest 422 → { errors: { json: { field: ["…"] } } } */
function formatApiError(data, fallback) {
  if (!data || typeof data !== "object") return fallback || "Error";
  if (typeof data.error === "string" && data.error) return data.error;
  if (typeof data.message === "string" && data.message) return data.message;
  const bag = data.errors?.json || data.errors?.query || data.errors;
  if (bag && typeof bag === "object") {
    const parts = [];
    for (const [field, msgs] of Object.entries(bag)) {
      const text = Array.isArray(msgs) ? msgs.join(", ") : String(msgs);
      parts.push(field === "_schema" ? text : `${field}: ${text}`);
    }
    if (parts.length) return parts.join(" · ");
  }
  return fallback || "Error";
}

/** Walk pages until the written user message is included.
 * Tool and grounding events can fill the API window (max 200) and hide the turn.
 */
async function loadThread(name) {
  const pages = [];
  let before = "";
  for (let i = 0; i < 20; i++) {
    const q = new URLSearchParams({ limit: "200" });
    if (before) q.set("before", before);
    const page = await request(`/bots/${name}/messages?${q}`);
    if (!Array.isArray(page) || !page.length) break;
    pages.unshift(page);
    if (page.some((m) => m.role === "user")) break;
    const oldest = page[0]?.created_at;
    if (!oldest || oldest === before) break;
    before = oldest;
  }
  return pages.flat();
}

export const api = {
  health: () => request("/health"),
  authStatus: () => request("/auth/status"),
  login: (password) => request("/auth/login", { method: "POST", body: { password } }),
  logout: () => request("/auth/logout", { method: "POST", body: {} }),
  listBots: () => request("/bots"),
  createBot: (body) => request("/bots", { method: "POST", body }),
  getBot: (name) => request(`/bots/${name}`),
  patchBot: (name, body) => request(`/bots/${name}`, { method: "PATCH", body }),
  deleteBot: (name) => request(`/bots/${name}`, { method: "DELETE" }),
  setCapability: (name, level) =>
    request(`/bots/${name}/capability`, { method: "POST", body: { level } }),
  listMessages: (name) => loadThread(name),
  sendMessage: (name, content, attachments = [], opts = {}) =>
    request(`/bots/${name}/messages`, {
      method: "POST",
      body: {
        content,
        attachments,
        ...(opts.prompt ? { prompt: opts.prompt } : {}),
      },
    }),
  /** Chat drop/picker → ~/shared/upload/<uuid>/<filename> */
  uploadChatFile: (name, file) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return request(`/bots/${name}/chat/files`, {
      method: "POST",
      body: fd,
      headers: {},
    });
  },
  clearMessages: (name) => request(`/bots/${name}/messages`, { method: "DELETE" }),
  /** Download discussion PDF (tools named without args/results). */
  async exportDiscussionPdf(name) {
    const res = await fetch(`${BASE}/bots/${encodeURIComponent(name)}/messages/export.pdf`, {
      credentials: "include",
    });
    if (!res.ok) {
      const ct = res.headers.get("content-type") || "";
      const data = ct.includes("application/json") ? await res.json() : await res.text();
      const err = new Error(formatApiError(data, res.statusText));
      err.status = res.status;
      throw err;
    }
    const blob = await res.blob();
    const cd = res.headers.get("content-disposition") || "";
    const m = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(cd);
    const filename = m
      ? decodeURIComponent(m[1].replace(/"/g, "").trim())
      : `discussion-${name}.pdf`;
    return { blob, filename };
  },
  deskStatus: (name) => request(`/bots/${name}/desk`),
  deskRequest: (name, body = { mode: "screen", reason: "" }) =>
    request(`/bots/${name}/desk/request`, { method: "POST", body }),
  deskRequestResolve: (name, action = "deny") =>
    request(`/bots/${name}/desk/request/resolve`, { method: "POST", body: { action } }),
  deskCreate: (name, body = { mode: "screen", internet: true }) =>
    request(`/bots/${name}/desk/create`, { method: "POST", body }),
  deskWake: (name) => request(`/bots/${name}/desk/wake`, { method: "POST", body: {} }),
  deskDestroy: (name) => request(`/bots/${name}/desk/destroy`, { method: "POST", body: {} }),
  deskRestart: (name) => request(`/bots/${name}/desk/restart`, { method: "POST", body: {} }),
  deskReset: (name) =>
    request(`/bots/${name}/desk/reset`, { method: "POST", body: { confirm: true } }),
  novnc: (name) => request(`/bots/${name}/desk/novnc`),
  getJob: (id) => request(`/jobs/${id}`),
  terminalLog: (name) => request(`/bots/${name}/terminal`),
  terminalExec: (name, command, timeout = 30) =>
    request(`/bots/${name}/terminal/exec`, { method: "POST", body: { command, timeout } }),
  listFiles: (name, path = ".") =>
    request(`/bots/${name}/files?path=${encodeURIComponent(path)}`),
  deleteFile: (name, path) =>
    request(`/bots/${name}/files?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
  downloadUrl: (name, path) =>
    `${BASE}/bots/${name}/files/download?path=${encodeURIComponent(path)}`,
  mkdir: (name, path, dirname) =>
    request(`/bots/${name}/files/mkdir`, {
      method: "POST",
      body: { path: path || ".", name: dirname },
    }),
  uploadFile: (name, path, file) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return request(`/bots/${name}/files/upload?path=${encodeURIComponent(path || ".")}`, {
      method: "POST",
      body: fd,
      headers: {},
    });
  },
  settings: () => request("/settings"),
  putSettings: (body) => request("/settings", { method: "PUT", body }),
  piStatus: () => request("/pi/status"),
  piModels: () => request("/pi/models"),
  stopBot: (name) => request(`/bots/${name}/stop`, { method: "POST", body: {} }),
  resumeBot: (name) => request(`/bots/${name}/resume`, { method: "POST", body: {} }),
  vaultEntries: () => request("/vault/entries"),
  createVaultEntry: (body) => request("/vault/entries", { method: "POST", body }),
  deleteVaultEntry: (id) => request(`/vault/entries/${id}`, { method: "DELETE" }),
  vaultGrants: (bot) =>
    request(bot ? `/vault/grants?bot=${encodeURIComponent(bot)}` : "/vault/grants"),
  grantVault: (bot, entry_id) =>
    request("/vault/grants", { method: "POST", body: { bot, entry_id } }),
  revokeVault: (bot, entry_id) =>
    request(`/vault/grants/${encodeURIComponent(bot)}/${entry_id}`, { method: "DELETE" }),
  resolveVaultRequest: (id, body) =>
    request(`/vault/requests/${id}/resolve`, { method: "POST", body }),
  memoryEntries: () => request("/memory/entries"),
  createMemoryEntry: (body) => request("/memory/entries", { method: "POST", body }),
  deleteMemoryEntry: (key) =>
    request(`/memory/entries/${encodeURIComponent(key)}`, { method: "DELETE" }),
  resolveMemoryProposal: (id, body) =>
    request(`/memory/proposals/${id}/resolve`, { method: "POST", body }),
  resolveApproval: (id, body) =>
    request(`/approvals/requests/${id}/resolve`, { method: "POST", body }),
  resolveClarify: (id, body) =>
    request(`/clarifies/requests/${id}/resolve`, { method: "POST", body }),
  clock: () => request("/clock"),
  searchMessages: (q, { bot, limit = 20, mode = "auto" } = {}) => {
    const qs = new URLSearchParams({ q, limit: String(limit), mode });
    if (bot) qs.set("bot", bot);
    return request(`/search/messages?${qs}`);
  },
  searchMessagesNl: (q, { bot, limit = 20 } = {}) =>
    request("/search/messages/nl", {
      method: "POST",
      body: { q, bot: bot || null, limit },
    }),
  takeScreenshot: (name, show_in_chat = true) =>
    request(`/bots/${name}/screen/screenshot`, {
      method: "POST",
      body: { show_in_chat },
    }),
  listSchedules: (name) => request(`/bots/${name}/schedules`),
  createSchedule: (name, body) =>
    request(`/bots/${name}/schedules`, { method: "POST", body }),
  patchSchedule: (name, id, body) =>
    request(`/bots/${name}/schedules/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body,
    }),
  deleteSchedule: (name, id) =>
    request(`/bots/${name}/schedules/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  listWebhooks: (name) => request(`/bots/${name}/webhooks`),
  patchWebhook: (name, id, body) =>
    request(`/bots/${name}/webhooks/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body,
    }),
  deleteWebhook: (name, id) =>
    request(`/bots/${name}/webhooks/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  listBotMcp: (name) => request(`/bots/${encodeURIComponent(name)}/mcp`),
  grantBotMcp: (name, body) =>
    request(`/bots/${encodeURIComponent(name)}/mcp`, { method: "POST", body }),
  revokeBotMcp: (name, grantId) =>
    request(`/bots/${encodeURIComponent(name)}/mcp/${encodeURIComponent(grantId)}`, {
      method: "DELETE",
    }),
  listDevices: () => request("/devices/"),
  companionBuild: () => request("/companion/build"),
  rebuildCompanion: () => request("/companion/build", { method: "POST" }),
  approveDevice: (pairId) =>
    request(`/devices/pair/${encodeURIComponent(pairId)}/approve`, { method: "POST" }),
  denyDevice: (pairId) =>
    request(`/devices/pair/${encodeURIComponent(pairId)}/deny`, { method: "POST" }),
  revokeDevice: (deviceId) =>
    request(`/devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" }),
  patchDevice: (deviceId, body) =>
    request(`/devices/${encodeURIComponent(deviceId)}`, { method: "PATCH", body }),
  notifyDevices: (body) => request("/devices/notify", { method: "POST", body }),
  setupStatus: (force = false) => request(`/setup/status${force ? "?force=1" : ""}`),
  startSetupJob: (kind) => request(`/setup/jobs/${encodeURIComponent(kind)}`, { method: "POST", body: {} }),
  setupLlm: () => request("/setup/llm"),
  saveSetupLlm: (body) => request("/setup/llm", { method: "PUT", body }),
  testSetupLlm: (body) => request("/setup/llm/test", { method: "POST", body }),
  setupLlmModels: (body) => request("/setup/llm/models", { method: "POST", body }),
  setupGroundingModels: (body) => request("/setup/grounding/models", { method: "POST", body }),
  setupGrounding: () => request("/setup/grounding"),
  saveSetupGrounding: (body) => request("/setup/grounding", { method: "PUT", body }),
  testSetupGrounding: (body) => request("/setup/grounding/test", { method: "POST", body }),
  updateStatus: (force = false) =>
    request(`/setup/update${force ? "?force=1" : ""}`),
  setUpdateChannel: (body) => request("/setup/update", { method: "PUT", body }),
  checkUpdate: () => request("/setup/update/check", { method: "POST", body: {} }),
  applyUpdate: () => request("/setup/update/apply", { method: "POST", body: {} }),
};
