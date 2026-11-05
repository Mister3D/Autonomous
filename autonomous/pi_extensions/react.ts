/**
 * Emoji reaction on the user message of the current turn.
 * Returns immediately — the assistant reply still happens afterwards.
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
    name: "react",
    label: "React",
    description:
      "Put a single emoji reaction on the user message you are answering " +
      "(example: ❤️ after « thanks »). Returns immediately. This does NOT end " +
      "your turn and does NOT replace a reply: if they need an answer, an " +
      "action, or any follow-up, write that text after this tool. If the " +
      "reaction alone is the whole response (thanks, acknowledgment), stop " +
      "without filler. One emoji only.",
    parameters: Type.Object({
      emoji: Type.String({ description: "One emoji, e.g. ❤️ or 👍" }),
    }),
    async execute(_id, params) {
      const cfg = apiConfig();
      if (!cfg) return textResult("react unavailable: API env missing.");
      const emoji = String(params.emoji || "").trim();
      if (!emoji) return textResult("react needs one emoji.");
      const res = await api("POST", `/bots/${encodeURIComponent(cfg.bot)}/reactions`, {
        emoji,
      });
      if (!res.ok) {
        const err = res.data?.message || res.data?.error || res.status;
        return textResult(`react failed: ${err}`);
      }
      return textResult(
        `Reaction ${emoji} is on the user's message. Your turn is still open: ` +
          "write the reply if one is needed. If the reaction is enough, stop " +
          "with no extra text.",
        { emoji },
      );
    },
  });
}
