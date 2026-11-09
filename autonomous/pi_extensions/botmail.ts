/**
 * Inter-bot messaging tools for Pi (Dit / Demande à @bot).
 * Managers: bot_list + bot_delegate (async, peer must relaunch),
 * plus household bot_create / bot_delete / bot_models.
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
      data: {
        error:
          "Autonomous API not configured (AUTONOMOUS_API_BASE / TOKEN / BOT).",
      },
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

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error("aborted"));
      return;
    }
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(new Error("aborted"));
      },
      { once: true },
    );
  });
}

async function isManager(cfg: { bot: string }): Promise<boolean> {
  const me = await api("GET", `/bots/${encodeURIComponent(cfg.bot)}`);
  return Boolean(me.ok && me.data?.is_manager);
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "bot_list",
    label: "List bots",
    description:
      "MANAGER ONLY: list other Autonomous bots (name, status, capability) "
      + "so you can orchestrate work across them. Non-managers cannot call this.",
    parameters: Type.Object({}),
    execute: async () => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Bot mail API not configured.");
      }
      const res = await api(
        "GET",
        `/bots/${encodeURIComponent(cfg.bot)}/mail/peers`,
      );
      if (!res.ok) {
        const msg =
          res.data?.message || res.data?.error || `HTTP ${res.status}`;
        return textResult(
          `Cannot list peers: ${msg}. `
            + (res.status === 403
              ? "Only a Manager bot can list other bots."
              : ""),
        );
      }
      const peers = Array.isArray(res.data) ? res.data : [];
      if (!peers.length) {
        return textResult("No other bots available.");
      }
      const lines = peers.map((b: any) => {
        const label =
          b.label && b.label !== b.name ? ` (${b.label})` : "";
        const mgr = b.is_manager ? " [manager]" : "";
        return (
          `- @${b.name}${label}${mgr} [${b.status || "idle"}] `
          + `cap=${b.capability || "none"}`
        );
      });
      return textResult(
        "Peers (use bot_delegate to assign work without waiting):\n"
          + lines.join("\n"),
      );
    },
  });

  pi.registerTool({
    name: "bot_delegate",
    label: "Delegate to bot",
    description:
      "MANAGER ONLY: assign a task to another bot WITHOUT waiting. "
      + "The message tells them to relaunch you with « Tell @you … » when done. "
      + "Continue other work; when their Dit arrives, you are relaunched.",
    parameters: Type.Object({
      to: Type.String({ description: "Worker bot name (with or without @)" }),
      task: Type.String({ description: "What the worker must do" }),
      expect_reply: Type.Optional(
        Type.String({
          description:
            "What they should put in the Dit-à callback (default: short success/failure summary)",
        }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Bot mail API not configured.");
      }
      const to = String(params.to || "").replace(/^@/, "");
      const body: Json = {
        to,
        task: String(params.task || ""),
      };
      if (params.expect_reply != null && String(params.expect_reply).trim()) {
        body.expect_reply = String(params.expect_reply).trim();
      }
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/mail/delegate`,
        body,
      );
      if (!res.ok) {
        const msg =
          res.data?.message || res.data?.error || `HTTP ${res.status}`;
        return textResult(
          `bot_delegate failed: ${msg}`
            + (res.status === 403
              ? " (Manager flag required — enable is_manager on this bot.)"
              : ""),
        );
      }
      return textResult(
        `Task delegated to @${to} (async). `
          + `You are NOT waiting — keep going. `
          + `They will relaunch you with « Tell @${cfg.bot} … » when finished.`,
        { inbox_id: res.data?.message },
      );
    },
  });

  pi.registerTool({
    name: "bot_models",
    label: "List models",
    description:
      "MANAGER ONLY: list available Pi models (provider/id refs) and the Settings "
      + "default used when bot_create omits model=. Call this before inventing a ref.",
    parameters: Type.Object({}),
    execute: async () => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Bot mail API not configured.");
      }
      const res = await api(
        "GET",
        `/bots/${encodeURIComponent(cfg.bot)}/household/models`,
      );
      if (!res.ok) {
        const msg =
          res.data?.message || res.data?.error || `HTTP ${res.status}`;
        return textResult(
          `Cannot list models: ${msg}`
            + (res.status === 403 ? " (Manager flag required.)" : ""),
        );
      }
      const def = String(res.data?.default_model || "").trim();
      const models = Array.isArray(res.data?.models) ? res.data.models : [];
      if (!models.length) {
        return textResult(
          (def ? `Default model: ${def}\n` : "No default model set in Settings → LLM.\n")
            + "No models listed by Pi right now.",
        );
      }
      const lines = models.slice(0, 80).map((m: any) => {
        const ref = m.ref || `${m.provider}/${m.id}`;
        const label = m.label && m.label !== m.id ? ` — ${m.label}` : "";
        return `- ${ref}${label}`;
      });
      const more =
        models.length > 80 ? `\n…and ${models.length - 80} more.` : "";
      return textResult(
        (def ? `Default model: ${def}\n` : "No default model set in Settings → LLM.\n")
          + "Available models (use ref with bot_create model=):\n"
          + lines.join("\n")
          + more,
      );
    },
  });

  pi.registerTool({
    name: "bot_create",
    label: "Create bots",
    description:
      "MANAGER ONLY: create one or more Autonomous bots. "
      + "Pass bots:[{name, model?}]. Omit model to use Settings → LLM default; "
      + "when the user names a model (e.g. gpt-4o / openai), set model on each bot "
      + "or call bot_models first. Does not create another Manager.",
    parameters: Type.Object({
      bots: Type.Array(
        Type.Object({
          name: Type.String({ description: "Display name (spaces OK)" }),
          model: Type.Optional(
            Type.String({
              description:
                "Pi model ref (provider/id) or clear hint; default = Settings LLM",
            }),
          ),
        }),
        { minItems: 1 },
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Bot mail API not configured.");
      }
      const bots = Array.isArray(params.bots) ? params.bots : [];
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/household/bots`,
        { bots },
      );
      if (!res.ok) {
        const msg =
          res.data?.message || res.data?.error || `HTTP ${res.status}`;
        return textResult(
          `bot_create failed: ${msg}`
            + (res.status === 403
              ? " (Manager flag required.)"
              : ""),
        );
      }
      const created = Array.isArray(res.data?.created) ? res.data.created : [];
      if (!created.length) {
        return textResult("bot_create: nothing created.");
      }
      const lines = created.map(
        (b: any) =>
          `- @${b.name}`
          + (b.label && b.label !== b.name ? ` (${b.label})` : "")
          + (b.model ? ` · ${b.model}` : ""),
      );
      return textResult(
        `Created ${created.length} bot(s):\n` + lines.join("\n"),
        { created },
      );
    },
  });

  pi.registerTool({
    name: "bot_delete",
    label: "Delete bots",
    description:
      "MANAGER ONLY: propose deleting bots via a chat card with a checklist "
      + "(all checked by default). BLOCKS until the user confirms or cancels. "
      + "Pass the bot names to offer; the user may uncheck some before confirming. "
      + "You cannot delete yourself.",
    parameters: Type.Object({
      bots: Type.Array(Type.String({ description: "Bot slug or @name" }), {
        minItems: 1,
      }),
      prompt: Type.Optional(
        Type.String({ description: "Why these bots should be deleted" }),
      ),
      title: Type.Optional(Type.String({ description: "Card title" })),
    }),
    execute: async (_id, params, signal) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Bot mail API not configured.");
      }
      const bots = Array.isArray(params.bots)
        ? params.bots.map((b: any) => String(b || "").replace(/^@/, ""))
        : [];
      const body: Json = { bots };
      if (params.prompt != null && String(params.prompt).trim()) {
        body.prompt = String(params.prompt).trim();
      }
      if (params.title != null && String(params.title).trim()) {
        body.title = String(params.title).trim();
      }
      const created = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/household/delete-requests`,
        body,
      );
      if (!created.ok) {
        const msg =
          created.data?.message
          || created.data?.error
          || `HTTP ${created.status}`;
        return textResult(
          `bot_delete failed: ${msg}`
            + (created.status === 403 ? " (Manager flag required.)" : ""),
        );
      }
      let req = created.data as Json;
      if (req.state && req.state !== "pending") {
        const deleted = Array.isArray((req.result as Json)?.deleted)
          ? ((req.result as Json).deleted as string[])
          : [];
        return textResult(
          req.state === "confirmed"
            ? `User confirmed. Deleted: ${deleted.join(", ") || "(none)"}.`
            : `Delete request ${req.state}.`,
          { request_id: req.id, state: req.state, deleted },
        );
      }

      const started = Date.now();
      const timeoutMs = 60 * 60 * 1000;
      while (Date.now() - started < timeoutMs) {
        if (signal?.aborted) {
          return textResult("bot_delete aborted before the user responded.", {
            request_id: req.id,
            state: "aborted",
            error: true,
          });
        }
        try {
          await sleep(1500, signal);
        } catch {
          return textResult("bot_delete aborted before the user responded.", {
            request_id: req.id,
            state: "aborted",
            error: true,
          });
        }
        const polled = await api(
          "GET",
          `/bots/${encodeURIComponent(cfg.bot)}/household/delete-requests/${req.id}`,
        );
        if (!polled.ok) continue;
        req = polled.data as Json;
        if (req.state && req.state !== "pending") {
          const result = (req.result as Json) || {};
          const deleted = Array.isArray(result.deleted)
            ? (result.deleted as string[])
            : [];
          if (result.human_redirect || req.state === "cancelled") {
            return textResult(
              "User skipped the buttons and wrote in chat (not a hard refusal). "
                + `Follow their message: ${result.message || result.guidance || ""}`,
              { request_id: req.id, state: req.state, deleted },
            );
          }
          if (req.state === "denied") {
            return textResult(
              "User cancelled the delete card. No bots were deleted.",
              { request_id: req.id, state: req.state, deleted: [] },
            );
          }
          const errs = Array.isArray(result.errors) ? result.errors : [];
          return textResult(
            `User confirmed. Deleted: ${deleted.join(", ") || "(none)"}.`
              + (errs.length ? ` Errors: ${errs.join("; ")}` : ""),
            { request_id: req.id, state: req.state, deleted, errors: errs },
          );
        }
      }
      return textResult(
        `Delete request ${req.id} still pending after timeout.`,
        { request_id: req.id, state: "pending", error: true },
      );
    },
  });

  pi.registerTool({
    name: "bot_tell",
    label: "Tell bot",
    description:
      "Send a one-way async message to another bot (like « Tell @name … »). Does not wait. "
      + "Mentioning @name in chat text is NOT enough — call this tool only when the user "
      + "(or a standing instruction) explicitly asks you to contact them. "
      + "Confirming delivery is not the end of the task. "
      + "content = a self-contained brief for the peer (they lack this chat): objective, "
      + "relevant facts, constraints, expected result — not the user's raw last sentence. "
      + "Address them as tu/you. Write content in the conversation language only "
      + "(do not mix French and English). "
      + "Managers assigning work should prefer bot_delegate (adds relaunch instructions).",
    parameters: Type.Object({
      to: Type.String({ description: "Target bot name (without or with @)" }),
      content: Type.String({
        description:
          "Self-contained brief for the peer, in the conversation language only. Not a raw user fragment.",
      }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Bot mail API not configured.");
      }
      const res = await api("POST", `/bots/${encodeURIComponent(cfg.bot)}/mail/tell`, {
        to: String(params.to || "").replace(/^@/, ""),
        content: String(params.content || ""),
      });
      if (!res.ok) {
        return textResult(
          `bot_tell failed: ${res.data?.message || res.data?.error || res.status}`,
        );
      }
      return textResult(
        `Message queued/delivered to @${String(params.to).replace(/^@/, "")}.`,
        { inbox_id: res.data?.message },
      );
    },
  });

  pi.registerTool({
    name: "bot_ask",
    label: "Ask bot",
    description:
      "Ask another bot and WAIT for its answer (blocks this run). Use when the user "
      + "wants the peer’s reply brought back here (« rapporte-moi sa réponse »). "
      + "Managers MUST NOT use this for orchestration — use bot_delegate instead "
      + "(async + peer relaunches you with Tell @). "
      + "Mentioning @name is NOT enough; need an explicit ask. "
      + "content = self-contained brief/question the peer can act on without this chat, "
      + "in the conversation language only (do not mix French and English). "
      + "Structure example, not a language: « si elle fait du poney » → « Est-ce que tu fais du poney ? ».",
    parameters: Type.Object({
      to: Type.String({ description: "Target bot name" }),
      content: Type.String({
        description:
          "Self-contained brief/question for the peer, in the conversation language only. Not a raw user fragment.",
      }),
      timeout_sec: Type.Optional(
        Type.Number({
          description: "Max wait seconds (default 600)",
        }),
      ),
    }),
    execute: async (_id, params, signal) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Bot mail API not configured.");
      }
      if (await isManager(cfg)) {
        return textResult(
          "You are a Manager: do NOT use bot_ask (blocking). "
            + "Call bot_delegate(to, task) so the peer relaunches you with Tell @ when done.",
        );
      }
      const to = String(params.to || "").replace(/^@/, "");
      const created = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/mail/ask`,
        { to, content: String(params.content || "") },
      );
      if (!created.ok) {
        return textResult(
          `bot_ask failed: ${created.data?.message || created.data?.error || created.status}`,
        );
      }
      const askId = created.data?.id;
      if (!askId) {
        return textResult("bot_ask: missing ask id in response.");
      }
      const timeoutSec = Math.max(
        30,
        Math.min(3600, Number(params.timeout_sec) || 600),
      );
      const deadline = Date.now() + timeoutSec * 1000;
      while (Date.now() < deadline) {
        if (signal?.aborted) {
          return textResult("bot_ask aborted.");
        }
        const poll = await api(
          "GET",
          `/bots/${encodeURIComponent(cfg.bot)}/mail/asks/${encodeURIComponent(askId)}`,
        );
        if (poll.ok && poll.data?.state === "answered") {
          const answer = String(poll.data.answer || "").trim() || "(empty)";
          return textResult(
            `Reply from @${poll.data.to_bot}:\n${answer}`,
            { ask_id: askId, answer },
          );
        }
        try {
          await sleep(2000, signal);
        } catch {
          return textResult("bot_ask aborted.");
        }
      }
      return textResult(
        `bot_ask timed out after ${timeoutSec}s waiting for @${to}.`,
        { ask_id: askId },
      );
    },
  });
}
