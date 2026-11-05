/**
 * Search past chat messages across bots (FTS / NL via Autonomous API).
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

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "chat_search",
    label: "Search chat history",
    description:
      "Search past chat messages across bots (or one bot). " +
      "Use for « where did we talk about X » / keywords. " +
      "mode=auto picks lexical vs natural-language. " +
      "Returns bot, message_id, snippet — tell the user the deep-link " +
      "`/b/<bot>/discussion?msg=<message_id>` when relevant. " +
      "Do not invent message ids.",
    parameters: Type.Object({
      query: Type.String({ description: "Keywords or natural-language question" }),
      bot: Type.Optional(
        Type.String({
          description:
            "Limit to one bot slug. Default: search all bots.",
        }),
      ),
      mode: Type.Optional(
        Type.String({
          description: "auto (default) | lexical | nl",
        }),
      ),
      limit: Type.Optional(
        Type.Number({ description: "Max hits (1–50, default 12)" }),
      ),
    }),
    execute: async (_id, params) => {
      const q = String(params.query || "").trim();
      if (!q) {
        return textResult("query is required.", { error: true });
      }
      const mode = String(params.mode || "auto").trim() || "auto";
      const limit = Math.max(1, Math.min(50, Number(params.limit) || 12));
      // Always scope to this bot (bot API token forbids cross-bot / unscoped search).
      const cfg = apiConfig();
      const bot = String(params.bot || cfg?.bot || "").trim();

      if (mode === "nl") {
        const res = await api("POST", "/search/messages/nl", {
          q,
          bot: bot || null,
          limit,
        });
        if (!res.ok) {
          return textResult(
            `chat_search failed: ${res.data?.message || res.data?.error || res.status}`,
            { error: true },
          );
        }
        return formatHits(res.data);
      }

      const qs = new URLSearchParams({
        q,
        mode,
        limit: String(limit),
      });
      if (bot) qs.set("bot", bot);
      const res = await api("GET", `/search/messages?${qs}`);
      if (!res.ok) {
        return textResult(
          `chat_search failed: ${res.data?.message || res.data?.error || res.status}`,
          { error: true },
        );
      }
      return formatHits(res.data);
    },
  });
}

function formatHits(data: any) {
  const hits = Array.isArray(data?.hits) ? data.hits : [];
  if (!hits.length) {
    return textResult(`No messages found for: ${data?.query || ""}`, {
      ok: true,
      count: 0,
      mode: data?.mode || "lexical",
      hits: [],
    });
  }
  const lines = [
    `Search (${data?.mode || "?"}) — ${hits.length} hit(s) for « ${data?.query || ""} »:`,
  ];
  for (const h of hits) {
    const label = h.bot_label || h.bot;
    lines.push(
      `- [${label}] ${h.role} ${h.created_at || ""} id=${h.message_id}\n` +
        `  ${String(h.snippet || "").replace(/\n/g, " ")}\n` +
        `  link: /b/${h.bot}/discussion?msg=${h.message_id}`,
    );
  }
  return textResult(lines.join("\n"), {
    ok: true,
    count: hits.length,
    mode: data?.mode,
    hits,
  });
}
