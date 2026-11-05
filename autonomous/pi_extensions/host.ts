/**
 * Host shell permission tools (Pi bash on the Autonomous host — not the VM).
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
      data: { error: "Autonomous API not configured." },
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

function errMessage(data: any, status: number): string {
  return data?.message || data?.error || `HTTP ${status}`;
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "host_request_shell",
    label: "Request host shell",
    description:
      "Ask the user (chat card) to allow the built-in Pi bash tool on the HOST machine " +
      "(not the bot VM). Wait until approved or denied. After approval the Pi session restarts " +
      "with bash enabled. Do NOT use this for bot ~/shared files — use files_list/read/write instead. " +
      "Do NOT use this for date, curl, ping, or other utilities — call vm_terminal_exec " +
      "(it asks the user for a terminal VM if there is none). " +
      "Prefer vm_terminal_exec for work inside the bot desktop. " +
      "The user can also toggle Shell hôte in Details and revoke anytime.",
    parameters: Type.Object({
      reason: Type.Optional(
        Type.String({ description: "Why host bash is needed (shown on the card)" }),
      ),
    }),
    execute: async (_id, params, signal) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const reason = String(params.reason || "").trim();
      const posted = await api("POST", `/bots/${encodeURIComponent(cfg.bot)}/shell/request`, {
        reason,
      });
      if (!posted.ok) {
        return textResult(errMessage(posted.data, posted.status), { error: true });
      }
      if (posted.data?.already_allowed || posted.data?.allow_host_shell) {
        return textResult(
          "Host bash already allowed. If bash is still missing, ask the user to send another message (session restart).",
          { allow_host_shell: true, state: "approved" },
        );
      }
      const messageId = posted.data?.message_id || null;
      const started = Date.now();
      const maxMs = 30 * 60 * 1000;
      while (!signal?.aborted && Date.now() - started < maxMs) {
        await new Promise((r) => setTimeout(r, 2000));
        if (signal?.aborted) break;
        const st = await api("GET", `/bots/${encodeURIComponent(cfg.bot)}/shell`);
        if (st.ok && st.data?.allow_host_shell) {
          return textResult(
            "User approved host bash. The Pi session will restart on the next turn — then you can use bash. " +
              "For VM work prefer vm_terminal_exec (no host permission needed).",
            {
              allow_host_shell: true,
              state: "approved",
              message_id: messageId,
            },
          );
        }
        if (st.ok && !st.data?.pending_request_id && !st.data?.allow_host_shell) {
          return textResult("User denied or revoked host bash.", {
            allow_host_shell: false,
            state: "denied",
            message_id: messageId,
            error: true,
          });
        }
      }
      if (signal?.aborted) {
        return textResult("Aborted while waiting for host shell authorization.", {
          error: true,
          state: "aborted",
        });
      }
      return textResult("Timed out waiting for host shell authorization.", {
        error: true,
        state: "timeout",
      });
    },
  });
}
