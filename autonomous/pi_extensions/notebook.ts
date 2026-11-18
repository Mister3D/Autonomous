/**
 * Per-bot notebook. The host appends standing orders, open lines, and note
 * titles to each prompt. These tools save immediately (no confirm card).
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Json = Record<string, unknown>;

function env(name: string): string {
  return (process.env[name] || "").trim();
}

function apiConfig(): { base: string; token: string; bot: string } | null {
  const base = env("AUTONOMOUS_API_BASE").replace(/\/$/, "");
  const token = env("AUTONOMOUS_TOKEN");
  const bot = env("AUTONOMOUS_BOT");
  if (!base || !token || !bot) return null;
  return { base, token, bot };
}

async function api(
  method: string,
  path: string,
  body?: Json,
): Promise<{ ok: boolean; status: number; data: any }> {
  const cfg = apiConfig();
  if (!cfg) {
    return {
      ok: false,
      status: 0,
      data: { error: "Autonomous API not configured for this Pi session." },
    };
  }
  const res = await fetch(`${cfg.base}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${cfg.token}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data: any = null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  } else {
    data = { message: await res.text() };
  }
  return { ok: res.ok, status: res.status, data };
}

function textResult(text: string, details: Json = {}) {
  return {
    content: [{ type: "text" as const, text }],
    details,
  };
}

function fail(res: { data: any; status: number }, name: string) {
  const msg =
    res.data?.message || res.data?.error || res.data?.error_code || res.status;
  return textResult(`${name} failed: ${msg}`);
}

function line(e: Json): string {
  const kind = String(e.kind || "");
  if (kind === "note") return `- ${e.id} (${kind}) ${e.title}`;
  return `- ${e.id} (${kind}) ${e.body}`;
}

export default function (pi: ExtensionAPI) {
  const botPath = () => {
    const cfg = apiConfig();
    return cfg ? `/bots/${encodeURIComponent(cfg.bot)}/notebook` : "";
  };

  pi.registerTool({
    name: "notebook_list",
    label: "Notebook list",
    description:
      "List this bot's notebook: standing orders, unfinished lines, and note titles. " +
      "Ids are used by notebook_get and notebook_close.",
    parameters: Type.Object({}),
    async execute() {
      const path = botPath();
      if (!path) return textResult("notebook_list unavailable: API env missing.");
      const res = await api("GET", path);
      if (!res.ok) return fail(res, "notebook_list");
      const rows = Array.isArray(res.data) ? res.data : [];
      if (!rows.length) return textResult("Notebook is empty.");
      return textResult(rows.map(line).join("\n"), { count: rows.length });
    },
  });

  pi.registerTool({
    name: "notebook_get",
    label: "Notebook get",
    description:
      "Read one notebook entry by id, including the full note body. " +
      "Use this when a note title matches the subject.",
    parameters: Type.Object({
      id: Type.String({ description: "Entry id from the prompt trailer or notebook_list" }),
    }),
    async execute(_id, params) {
      const path = botPath();
      if (!path) return textResult("notebook_get unavailable: API env missing.");
      const id = String(params.id || "").trim();
      const res = await api("GET", `${path}/${encodeURIComponent(id)}`);
      if (!res.ok) return fail(res, "notebook_get");
      const e = res.data || {};
      const text =
        e.kind === "note"
          ? `${e.id} (${e.kind}) ${e.title}\n${e.body}`
          : `${e.id} (${e.kind}) ${e.body}`;
      return textResult(text, { entry: e });
    },
  });

  pi.registerTool({
    name: "notebook_remember",
    label: "Notebook remember",
    description:
      "Save into THIS bot's notebook immediately. No confirm card. " +
      "kind=order: a lasting rule the user stated, one short sentence, stable title. " +
      "kind=open: one short line of work still unfinished. Write it before leaving the subject. " +
      "kind=note: a decision or setup to keep (title + body). " +
      "Reuse the same title to update. Pass id to update that row. Do not store secrets.",
    parameters: Type.Object({
      kind: Type.String({ description: "order | open | note" }),
      body: Type.String({ description: "The rule, the unfinished line, or the note body" }),
      title: Type.Optional(
        Type.String({ description: "Stable short title. Required in spirit for notes." }),
      ),
      id: Type.Optional(Type.String({ description: "Update this entry instead of creating one" })),
    }),
    async execute(_id, params) {
      const path = botPath();
      if (!path) return textResult("notebook_remember unavailable: API env missing.");
      const body = {
        kind: String(params.kind || "").trim(),
        title: String(params.title || "").trim(),
        body: String(params.body || ""),
        id: String(params.id || "").trim(),
      };
      const res = await api("POST", path, body);
      if (!res.ok) return fail(res, "notebook_remember");
      const e = res.data || {};
      return textResult(
        `Saved ${e.id} (${e.kind}) ${e.title}. Continue; the next message already includes it.`,
        { entry: e },
      );
    },
  });

  pi.registerTool({
    name: "notebook_close",
    label: "Notebook close",
    description:
      "Remove one notebook entry by id. Use it when an open line is done, " +
      "or when the user drops a standing order.",
    parameters: Type.Object({
      id: Type.String({ description: "Entry id to remove" }),
    }),
    async execute(_id, params) {
      const path = botPath();
      if (!path) return textResult("notebook_close unavailable: API env missing.");
      const id = String(params.id || "").trim();
      const res = await api("DELETE", `${path}/${encodeURIComponent(id)}`);
      if (!res.ok) return fail(res, "notebook_close");
      return textResult(`Removed ${id}.`, { id });
    },
  });
}
