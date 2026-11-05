/**
 * ask_approval — blocking Accept / Refuse card in Autonomous chat.
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

function outcomeText(req: Json): string {
  const state = String(req.state || "");
  const result = (req.result as Json) || {};
  if (state === "approved") {
    return "User ACCEPTED. You may proceed with the action you asked about.";
  }
  if (result.human_redirect || state === "cancelled") {
    return (
      "User skipped the buttons and wrote in chat (not a hard refusal). " +
      `Follow their message: ${result.message || result.guidance || ""}`
    );
  }
  if (state === "denied") {
    return "User REFUSED. Do not perform the action. Acknowledge and stop or propose an alternative.";
  }
  return `Approval still ${state}.`;
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ask_approval",
    label: "Ask approval",
    description:
      "Ask the user to Accept or Refuse via a chat card. BLOCKING: waits until they " +
      "click a button (or write in chat). Use before irreversible / risky actions when " +
      "a standing rule says to ask first (e.g. before a command), or whenever you need " +
      "explicit consent. Provide a clear prompt describing what you want to do.",
    parameters: Type.Object({
      prompt: Type.String({
        description: "What you want approval for (shown on the card)",
      }),
      title: Type.Optional(
        Type.String({ description: "Short card title (default: Approbation)" }),
      ),
    }),
    async execute(_id, params, signal) {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("ask_approval unavailable: API env missing.");
      }
      const created = await api("POST", "/approvals/requests", {
        bot: cfg.bot,
        prompt: String(params.prompt || "").trim(),
        title: String(params.title || "").trim(),
      });
      if (!created.ok) {
        return textResult(
          `ask_approval failed: ${created.data?.message || created.data?.error || created.status}`,
        );
      }
      let req = created.data as Json;
      if (req.state && req.state !== "pending") {
        return textResult(outcomeText(req), {
          request_id: req.id,
          state: req.state,
        });
      }

      const started = Date.now();
      const timeoutMs = 60 * 60 * 1000;
      while (Date.now() - started < timeoutMs) {
        if (signal?.aborted) {
          return textResult("ask_approval aborted before the user responded.", {
            request_id: req.id,
            state: "aborted",
            error: true,
          });
        }
        await new Promise((r) => setTimeout(r, 1500));
        const polled = await api("GET", `/approvals/requests/${req.id}`);
        if (!polled.ok) continue;
        req = polled.data as Json;
        if (req.state && req.state !== "pending") {
          return textResult(outcomeText(req), {
            request_id: req.id,
            state: req.state,
            approved: req.state === "approved",
            denied: req.state === "denied",
          });
        }
      }
      return textResult(
        `Approval ${req.id} still pending after timeout. Ask the user to use the card, then retry.`,
        { request_id: req.id, state: "pending", error: true },
      );
    },
  });
}
