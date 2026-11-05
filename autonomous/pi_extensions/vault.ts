/**
 * Autonomous vault tools for Pi.
 *
 * Secrets never appear in tool results (LLM-visible content). The tools create
 * a pending request that surfaces as a form card in the Autonomous chat UI;
 * they poll until the user approves or denies.
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
          "Autonomous vault API not configured (AUTONOMOUS_API_BASE / TOKEN / BOT).",
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

function redactResult(req: Json): string {
  const state = String(req.state || "");
  const result = (req.result as Json) || {};
  const lines = [
    `Vault request ${req.id} → ${state}.`,
    "Secret values are never returned to the model.",
  ];
  if (result.message) lines.push(String(result.message));
  if (result.entry_id) lines.push(`entry_id: ${result.entry_id}`);
  if (result.label) lines.push(`label: ${result.label}`);
  if (result.origin) lines.push(`origin: ${result.origin}`);
  if (result.username) lines.push(`username: ${result.username}`);
  if (result.human_redirect || result.cancelled) {
    lines.push(
      "User skipped the form with chat guidance — follow that message; this is NOT a hard denial.",
    );
  } else if (result.denied) {
    lines.push("User denied. Do not invent credentials.");
  }
  return lines.join("\n");
}

async function createAndWait(
  kind: "access" | "login" | "secret" | "credential",
  payload: Json,
  signal?: AbortSignal,
): Promise<ReturnType<typeof textResult>> {
  const cfg = apiConfig();
  if (!cfg) {
    return textResult(
      "Vault unavailable: Autonomous API env not set for this Pi session.",
    );
  }
  const created = await api("POST", "/vault/requests", {
    bot: cfg.bot,
    kind,
    ...payload,
  });
  if (!created.ok) {
    const err =
      created.data?.message ||
      created.data?.error ||
      `HTTP ${created.status}`;
    return textResult(`Failed to create vault request: ${err}`);
  }
  let req = created.data as Json;
  if (req.state && req.state !== "pending") {
    return textResult(redactResult(req), { request_id: req.id, state: req.state });
  }

  const started = Date.now();
  // User OTP / credential forms may sit longer than a 5‑minute agent run;
  // the host pauses the runtime clock while status=waiting.
  const timeoutMs = 60 * 60 * 1000;
  while (Date.now() - started < timeoutMs) {
    if (signal?.aborted) {
      return textResult("Vault request aborted before the user responded.", {
        request_id: req.id,
        state: "aborted",
      });
    }
    await new Promise((r) => setTimeout(r, 1500));
    const polled = await api("GET", `/vault/requests/${req.id}`);
    if (!polled.ok) continue;
    req = polled.data as Json;
    if (req.state && req.state !== "pending") {
      return textResult(redactResult(req), {
        request_id: req.id,
        state: req.state,
      });
    }
  }
  return textResult(
    `Vault request ${req.id} still pending after timeout. Ask the user to approve the form in chat, then retry.`,
    { request_id: req.id, state: "pending" },
  );
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "vault_catalog",
    label: "Vault catalog",
    description:
      "List labels of secrets/logins in the global Autonomous vault (metadata only, never secret values). Use before request_vault_access.",
    parameters: Type.Object({}),
    execute: async () => {
      const res = await api("GET", "/vault/catalog");
      if (!res.ok) {
        return textResult(
          `Cannot list vault catalog: ${res.data?.message || res.data?.error || res.status}`,
        );
      }
      const entries = Array.isArray(res.data) ? res.data : [];
      if (!entries.length) {
        return textResult(
          "Vault is empty. Use request_credentials to ask the user for what you need (API key, login, …).",
        );
      }
      const lines = entries.map(
        (e: any) =>
          `- ${e.id} | ${e.kind} | ${e.label}${e.origin ? ` @ ${e.origin}` : ""}${e.username ? ` (user: ${e.username})` : ""}`,
      );
      return textResult(
        "Vault catalog (no secrets):\n" + lines.join("\n"),
      );
    },
  });

  pi.registerTool({
    name: "vault_granted",
    label: "Vault grants",
    description:
      "List vault entries this bot is already allowed to use (metadata only).",
    parameters: Type.Object({}),
    execute: async () => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Vault API not configured.");
      }
      const res = await api(
        "GET",
        `/vault/entries?bot=${encodeURIComponent(cfg.bot)}`,
      );
      if (!res.ok) {
        return textResult(
          `Cannot list grants: ${res.data?.message || res.data?.error || res.status}`,
        );
      }
      const entries = Array.isArray(res.data) ? res.data : [];
      if (!entries.length) {
        return textResult(
          "This bot has no vault grants yet. Use request_credentials or request_vault_access.",
        );
      }
      const lines = entries.map(
        (e: any) =>
          `- ${e.id} | ${e.kind} | ${e.label}${e.origin ? ` @ ${e.origin}` : ""}${e.username ? ` (user: ${e.username})` : ""}`,
      );
      return textResult(
        "Granted entries (secret values withheld; the username shown IS the account " +
          "login — type it with vm_type, never invent another; only the secret/password " +
          "goes through vault_type):\n" +
          lines.join("\n"),
      );
    },
  });

  pi.registerTool({
    name: "request_vault_access",
    label: "Request vault access",
    description:
      "Ask the user (via a chat form) to grant this bot access to an existing vault entry. Secret values are never returned to you.",
    parameters: Type.Object({
      entry_id: Type.String({ description: "Vault entry id from vault_catalog" }),
      reason: Type.Optional(
        Type.String({ description: "Why access is needed" }),
      ),
    }),
    execute: async (_id, params, signal) =>
      createAndWait(
        "access",
        { entry_id: params.entry_id, reason: params.reason || "" },
        signal,
      ),
  });

  pi.registerTool({
    name: "request_credentials",
    label: "Request credentials",
    description:
      "Ask the user for credentials via a secure chat form that YOU define. " +
      "Choose the fields yourself: e.g. only an API key, or username+password, or token+endpoint. " +
      "Secret field values never pass through the model — only a redacted approval result.",
    parameters: Type.Object({
      label: Type.String({
        description: "Short title shown on the form (e.g. 'OpenAI API', 'GitHub login')",
      }),
      reason: Type.Optional(
        Type.String({ description: "Why these credentials are needed" }),
      ),
      origin: Type.Optional(
        Type.String({
          description: "Optional site/service URL, e.g. https://api.openai.com",
        }),
      ),
      fields: Type.Array(
        Type.Object({
          id: Type.String({
            description: "Machine id: lowercase [a-z][a-z0-9_]* e.g. api_key, username, password",
          }),
          label: Type.String({
            description: "Label shown to the user on the form, e.g. 'Clé API'",
          }),
          secret: Type.Boolean({
            description: "true = password-style input, never returned to the model",
          }),
          required: Type.Optional(
            Type.Boolean({ description: "Default true" }),
          ),
        }),
        {
          minItems: 1,
          description:
            "Form fields. Examples: [{id:'api_key',label:'API key',secret:true}] " +
            "or [{id:'username',label:'Email',secret:false},{id:'password',label:'Password',secret:true}]",
        },
      ),
    }),
    execute: async (_id, params, signal) =>
      createAndWait(
        "credential",
        {
          label: params.label || "",
          reason: params.reason || "",
          origin: params.origin || "",
          fields: params.fields || [],
        },
        signal,
      ),
  });

  // Convenience aliases with preset fields
  pi.registerTool({
    name: "request_login",
    label: "Request login",
    description:
      "Shortcut: ask for website username+password. Prefer request_credentials when you need a custom shape (API key only, token, …).",
    parameters: Type.Object({
      origin: Type.String({
        description: "Site origin or URL, e.g. https://example.com",
      }),
      label: Type.Optional(Type.String({ description: "Short label for the vault entry" })),
      reason: Type.Optional(Type.String({ description: "Why login is needed" })),
    }),
    execute: async (_id, params, signal) =>
      createAndWait(
        "credential",
        {
          origin: params.origin || "",
          label: params.label || params.origin || "Login",
          reason: params.reason || "",
          fields: [
            { id: "username", label: "Identifiant / e-mail", secret: false, required: true },
            { id: "password", label: "Mot de passe", secret: true, required: true },
          ],
        },
        signal,
      ),
  });

  pi.registerTool({
    name: "request_secret",
    label: "Request secret",
    description:
      "Shortcut: ask for a single secret/API key. Prefer request_credentials to name the field explicitly.",
    parameters: Type.Object({
      label: Type.String({ description: "Label for the secret" }),
      reason: Type.Optional(Type.String({ description: "Why the secret is needed" })),
    }),
    execute: async (_id, params, signal) =>
      createAndWait(
        "credential",
        {
          label: params.label || "",
          reason: params.reason || "",
          fields: [
            { id: "secret", label: params.label || "Secret / clé API", secret: true, required: true },
          ],
        },
        signal,
      ),
  });

  pi.registerTool({
    name: "report_user_secret",
    label: "Report user secret",
    description:
      "Call SILENTLY (no chat text) as the first action when the user pastes a password, " +
      "API key, token, or similar secret into the chat (not already handled by the vault form). " +
      "Never announce this tool or narrate the call. Do NOT put the secret value in the arguments. " +
      "This scrubs the user message on Autonomous, shows a provider-leak warning, " +
      "and aborts the run. Then wait for the user — do not continue the task with that secret.",
    parameters: Type.Object({
      reason: Type.Optional(
        Type.String({
          description: "Short reason without the secret itself (e.g. user pasted an API key)",
        }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Vault API not configured for this Pi session.");
      }
      const res = await api("POST", "/vault/report-user-secret", {
        bot: cfg.bot,
        reason: String(params.reason || "").trim(),
      });
      if (!res.ok) {
        return textResult(
          `report_user_secret failed: ${res.data?.message || res.data?.error || res.status}`,
          { error: true },
        );
      }
      return textResult(
        (res.data?.message as string) ||
          "Secret report recorded. Stop using any secret from the chat. Wait for the user.",
        {
          ok: true,
          aborted: true,
          scrubbed_message_id: res.data?.scrubbed_message_id,
        },
      );
    },
  });

  pi.registerTool({
    name: "vault_type",
    label: "Vault type / paste",
    description:
      "Type or paste a vault SECRET (the password / API key — NOT the username, which " +
      "you read from vault_catalog / vault_granted and type with vm_type) into the " +
      "focused window of this bot's desktop " +
      "(VNC keystrokes / clipboard). The cleartext NEVER returns to you — only ok + char count. " +
      "Requires a grant (vault_granted) and a running desk. Focus the target (e.g. a terminal) first. " +
      "method=type sends keystrokes; method=paste uses clipboard + Ctrl+Shift+V.",
    parameters: Type.Object({
      entry_id: Type.String({
        description: "Vault entry id from vault_granted / vault_catalog",
      }),
      field: Type.Optional(
        Type.String({
          description:
            "Secret field id to inject (e.g. password, api_key). Default: password/secret/api_key/first.",
        }),
      ),
      method: Type.Optional(
        Type.String({ description: "type (default) or paste" }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Vault API not configured for this Pi session.");
      }
      const method = String(params.method || "type").toLowerCase();
      const body: Json = {
        entry_id: params.entry_id,
        method: method === "paste" ? "paste" : "type",
      };
      if (params.field) body.field = params.field;
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/vault/inject`,
        body,
      );
      if (!res.ok) {
        const err =
          res.data?.message || res.data?.error || `HTTP ${res.status}`;
        return textResult(
          `vault_type failed: ${err}\n` +
            "Secret was not returned. Fix grant/desk/focus, then retry.",
          { error: true },
        );
      }
      const d = res.data || {};
      return textResult(
        [
          "Vault secret injected into the desk (cleartext never returned here).",
          `entry_id: ${d.entry_id}`,
          `field: ${d.field}`,
          `method: ${d.method}`,
          `chars: ${d.chars}`,
        ].join("\n"),
        {
          ok: true,
          entry_id: d.entry_id,
          field: d.field,
          method: d.method,
          chars: d.chars,
          secret_returned: false,
        },
      );
    },
  });
}
