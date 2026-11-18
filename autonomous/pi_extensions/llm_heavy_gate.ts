/**
 * Cap concurrent LLM calls **per model** (provider/id).
 *
 * Honours ``autonomous.parallelGate`` (any size) and/or ``autonomous.heavyGate``
 * (estimated tokens ≥ threshold). Waits on Autonomous for a lease before the
 * provider HTTP call.
 */

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

/** Rough chars/4 — mirrors autonomous.services.llm_heavy_gate.estimate_tokens. */
function estimateTokens(payload: unknown): number {
  const walk = (node: unknown): number => {
    if (node == null) return 0;
    if (typeof node === "string") return node.length;
    if (typeof node === "number" || typeof node === "boolean") return 8;
    if (Array.isArray(node)) return node.reduce((n, x) => n + walk(x), 0);
    if (typeof node === "object") {
      const obj = node as Record<string, unknown>;
      const t = obj.type;
      if (t === "image_url" || t === "image" || t === "input_image") return 1200;
      let total = 0;
      for (const [key, value] of Object.entries(obj)) {
        if (
          (key === "image_url" || key === "image" || key === "source") &&
          value &&
          typeof value === "object"
        ) {
          const url =
            (value as { url?: unknown; data?: unknown }).url ??
            (value as { data?: unknown }).data ??
            "";
          if (typeof url === "string" && url.startsWith("data:")) {
            total += 1200;
            continue;
          }
        }
        total += walk(value);
      }
      return total;
    }
    return 0;
  };
  return Math.max(0, Math.floor((walk(payload) + 3) / 4));
}

function payloadModel(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return undefined;
  const m = (payload as { model?: unknown }).model;
  return typeof m === "string" && m.trim() ? m.trim() : undefined;
}

type LeaseState = { leaseId: string | null };

async function acquireLease(
  tokens: number,
  model: string | undefined,
  state: LeaseState,
): Promise<void> {
  const cfg = apiConfig();
  if (!cfg) return;
  try {
    const body: Record<string, unknown> = { tokens };
    if (model) body.model = model;
    const res = await fetch(
      `${cfg.base}/bots/${encodeURIComponent(cfg.bot)}/llm-heavy-gate/acquire`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${cfg.token}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(body),
      },
    );
    if (!res.ok) {
      // Fail open after the host refused — do not block the household forever.
      return;
    }
    const data = (await res.json()) as { lease_id?: string | null; heavy?: boolean };
    if (data?.lease_id) state.leaseId = String(data.lease_id);
  } catch {
    // Network blip: fail open.
  }
}

async function releaseLease(state: LeaseState): Promise<void> {
  const lid = state.leaseId;
  if (!lid) return;
  state.leaseId = null;
  const cfg = apiConfig();
  if (!cfg) return;
  try {
    await fetch(
      `${cfg.base}/bots/${encodeURIComponent(cfg.bot)}/llm-heavy-gate/release`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${cfg.token}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ lease_id: lid }),
      },
    );
  } catch {
    // Lease TTL on the host will reclaim.
  }
}

export default function (pi: ExtensionAPI) {
  // One in-flight provider call per Pi process is the normal case.
  const state: LeaseState = { leaseId: null };

  pi.on("before_provider_request", async (event) => {
    const tokens = estimateTokens(event.payload);
    await acquireLease(tokens, payloadModel(event.payload), state);
  });

  pi.on("after_provider_response", async () => {
    await releaseLease(state);
  });

  pi.on("session_shutdown", async () => {
    await releaseLease(state);
  });
}
