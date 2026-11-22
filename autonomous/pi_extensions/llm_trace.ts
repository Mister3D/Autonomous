/**
 * Capture the exact provider request JSON before each LLM HTTP call.
 *
 * Writes the payload under the bot Pi cwd (`llm_turns/`) then opens a chat
 * card pointing at that file. The Python agent writes the response JSON on
 * message_end. Base64 image bytes stay in the file (full payload).
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

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

function writeRequestPayload(payload: unknown): string | null {
  try {
    const dir = join(process.cwd(), "llm_turns");
    mkdirSync(dir, { recursive: true });
    const name = `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.json`;
    const rel = `llm_turns/${name}`;
    writeFileSync(join(process.cwd(), rel), JSON.stringify(payload), "utf8");
    return rel;
  } catch {
    return null;
  }
}

async function postOpen(requestFile: string): Promise<void> {
  const cfg = apiConfig();
  if (!cfg) return;
  try {
    await fetch(`${cfg.base}/bots/${encodeURIComponent(cfg.bot)}/llm-turns`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${cfg.token}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        request_file: requestFile,
        request_kind: "provider",
      }),
    });
  } catch {
    // Never block the provider call on a trace failure.
  }
}

export default function (pi: ExtensionAPI) {
  pi.on("before_provider_request", (event) => {
    const rel = writeRequestPayload(event.payload);
    if (rel) void postOpen(rel);
    // Do not modify the payload.
  });
}
