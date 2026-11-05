/**
 * ask_clarify — blocking structured question (choices and/or short text).
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
  if (state === "answered") {
    const answer = String(result.answer || "");
    const via = String(result.via || "text");
    return `User answered (${via}): ${answer}. Use this and continue.`;
  }
  if (result.human_redirect || state === "cancelled") {
    return (
      "User skipped the card and wrote in chat. " +
      `Follow their message: ${result.message || result.guidance || ""}`
    );
  }
  return `Clarify still ${state}.`;
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ask_clarify",
    label: "Ask clarify",
    description:
      "Ask the user a structured question via a chat card. BLOCKING until they " +
      "answer or write in chat. Use for a missing fact (format, name, which option). " +
      "choices: 2–8 short labels they can click. Omit choices for a short text field. " +
      "allow_text=true with choices accepts either a click or a typed answer. " +
      "Do NOT use this for yes/no consent on a risky action — use ask_approval.",
    parameters: Type.Object({
      prompt: Type.String({
        description: "The question, shown on the card",
      }),
      title: Type.Optional(
        Type.String({ description: "Short card title (default: Précision)" }),
      ),
      choices: Type.Optional(
        Type.Array(Type.String(), {
          minItems: 2,
          maxItems: 8,
          description: "Clickable answers, e.g. ['PDF', 'Markdown']",
        }),
      ),
      allow_text: Type.Optional(
        Type.Boolean({
          description:
            "Allow a short typed answer. Default: true when choices are omitted, false when choices are set.",
        }),
      ),
    }),
    async execute(_id, params, signal) {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("ask_clarify unavailable: API env missing.");
      }
      const body: Json = {
        bot: cfg.bot,
        prompt: String(params.prompt || "").trim(),
        title: String(params.title || "").trim(),
      };
      const choices = Array.isArray(params.choices)
        ? params.choices.map((c) => String(c || "").trim()).filter(Boolean)
        : [];
      if (choices.length) body.choices = choices;
      if (params.allow_text !== undefined) body.allow_text = Boolean(params.allow_text);

      const created = await api("POST", "/clarifies/requests", body);
      if (!created.ok) {
        return textResult(
          `ask_clarify failed: ${created.data?.message || created.data?.error || created.status}`,
        );
      }
      let req = created.data as Json;
      if (req.state && req.state !== "pending") {
        return textResult(outcomeText(req), {
          request_id: req.id,
          state: req.state,
          answer: (req.result as Json)?.answer,
        });
      }

      const started = Date.now();
      const timeoutMs = 60 * 60 * 1000;
      while (Date.now() - started < timeoutMs) {
        if (signal?.aborted) {
          return textResult("ask_clarify aborted before the user responded.", {
            request_id: req.id,
            state: "aborted",
            error: true,
          });
        }
        await new Promise((r) => setTimeout(r, 1500));
        const polled = await api("GET", `/clarifies/requests/${req.id}`);
        if (!polled.ok) continue;
        req = polled.data as Json;
        if (req.state && req.state !== "pending") {
          const result = (req.result as Json) || {};
          return textResult(outcomeText(req), {
            request_id: req.id,
            state: req.state,
            answer: result.answer,
            via: result.via,
          });
        }
      }
      return textResult(
        `Clarify ${req.id} still pending after timeout. Ask the user to use the card, then retry.`,
        { request_id: req.id, state: "pending", error: true },
      );
    },
  });
}
