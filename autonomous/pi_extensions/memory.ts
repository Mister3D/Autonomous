/**
 * Shared household memory tools for Pi.
 * Core facts are also injected into each user prompt by the host.
 * Writes go through memory_propose (the user approves in chat — non-blocking).
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

function formatEntry(e: Json): string {
  return `- ${e.label} (\`${e.key}\`, ${e.tier}): ${e.value}`;
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "memory_list",
    label: "Memory list",
    description:
      "List shared household memory. tier=core|browse|omit for all. " +
      "Core facts are also loaded once into the system prompt at conversation start " +
      "when this bot has memory access.",
    parameters: Type.Object({
      tier: Type.Optional(
        Type.String({ description: "core | browse | omit for all" }),
      ),
    }),
    async execute(_id, params) {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("memory_list unavailable: API env missing.");
      }
      const tier = String(params.tier || "").trim();
      const params_q = new URLSearchParams({ bot: cfg.bot });
      if (tier) params_q.set("tier", tier);
      const res = await api("GET", `/memory/entries?${params_q}`);
      if (!res.ok) {
        return textResult(
          `memory_list failed: ${res.data?.message || res.data?.error || res.status}`,
        );
      }
      const rows = Array.isArray(res.data) ? res.data : [];
      if (!rows.length) return textResult("Shared memory is empty.");
      return textResult(
        `Shared memory (${rows.length}):\n` + rows.map(formatEntry).join("\n"),
        { count: rows.length },
      );
    },
  });

  pi.registerTool({
    name: "memory_get",
    label: "Memory get",
    description: "Read one shared memory entry by key (e.g. preferred_name, address).",
    parameters: Type.Object({
      key: Type.String({ description: "Stable key, e.g. preferred_name" }),
    }),
    async execute(_id, params) {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("memory_get unavailable: API env missing.");
      }
      const key = String(params.key || "").trim();
      const res = await api(
        "GET",
        `/memory/entries/${encodeURIComponent(key)}?bot=${encodeURIComponent(cfg.bot)}`,
      );
      if (!res.ok) {
        return textResult(
          `memory_get failed: ${res.data?.message || res.data?.error || res.status}`,
        );
      }
      return textResult(formatEntry(res.data), { entry: res.data });
    },
  });

  pi.registerTool({
    name: "memory_search",
    label: "Memory search",
    description: "Search shared memory by substring in key/label/value.",
    parameters: Type.Object({
      q: Type.String({ description: "Search query" }),
    }),
    async execute(_id, params) {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("memory_search unavailable: API env missing.");
      }
      const q = String(params.q || "").trim();
      const res = await api(
        "GET",
        `/memory/search?q=${encodeURIComponent(q)}&bot=${encodeURIComponent(cfg.bot)}`,
      );
      if (!res.ok) {
        return textResult(
          `memory_search failed: ${res.data?.message || res.data?.error || res.status}`,
        );
      }
      const rows = Array.isArray(res.data) ? res.data : [];
      if (!rows.length) return textResult(`No memory matches for « ${q} ».`);
      return textResult(
        `Matches (${rows.length}):\n` + rows.map(formatEntry).join("\n"),
        { count: rows.length },
      );
    },
  });

  pi.registerTool({
    name: "memory_propose",
    label: "Memory propose",
    description:
      "Propose saving or deleting a shared memory fact. Creates a chat card for the user. " +
      "NON-BLOCKING: continue your task immediately — do not wait, do not poll. " +
      "Use action=set with key/value/tier. " +
      "core = always-important: name/identity, standing rules for how to act " +
      "(e.g. always ask before a command). " +
      "browse = default for situational details: likes, food, address, hobbies. " +
      "Examples: preferred_name=Alex (core); ask_before_commands=true (core); " +
      "favourite_food=raclette (browse); address=… (browse).",
    parameters: Type.Object({
      action: Type.String({ description: "set | delete" }),
      key: Type.String({
        description: "e.g. preferred_name, ask_before_commands, favourite_food",
      }),
      value: Type.Optional(Type.String({ description: "Required for set" })),
      label: Type.Optional(Type.String({ description: "Label shown to the user" })),
      tier: Type.Optional(
        Type.String({
          description:
            "core = standing rules / identity; browse = likes, food, address (default if unsure)",
        }),
      ),
      reason: Type.Optional(Type.String({ description: "Why store this" })),
    }),
    async execute(_id, params) {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Memory propose unavailable: API env missing.");
      }
      const body = {
        bot: cfg.bot,
        action: String(params.action || "set").trim(),
        key: String(params.key || "").trim(),
        value: String(params.value || ""),
        label: String(params.label || ""),
        tier: String(params.tier || "browse").trim() || "browse",
        reason: String(params.reason || ""),
      };
      const res = await api("POST", "/memory/proposals", body);
      if (!res.ok) {
        return textResult(
          `memory_propose failed: ${res.data?.message || res.data?.error || res.status}`,
        );
      }
      if (res.data?.state === "approved") {
        return textResult(
          `Saved immediately (setup onboarding — no user card). ` +
            `Continue to the next question right away; do not wait.`,
          { proposal_id: res.data.id, state: res.data.state, auto: true },
        );
      }
      return textResult(
        `Proposal ${res.data.id} is pending user approval in chat (non-blocking). ` +
          `Continue your current task; do not wait for approval.`,
        { proposal_id: res.data.id, state: res.data.state },
      );
    },
  });
}
