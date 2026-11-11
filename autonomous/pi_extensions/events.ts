/**
 * Scheduled tasks (host-local cron, stored UTC) + inbound webhooks — Pi tools.
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

function errMsg(res: { data: any; status: number }): string {
  return res.data?.message || res.data?.error || String(res.status);
}

function fireLine(s: any): string {
  const tz = s.timezone || "local";
  const when = s.next_run_local || s.next_run_at || "—";
  const now = s.now_local ? ` Now: ${s.now_local} ${tz}.` : "";
  return (
    `Next fire: ${when} ${tz} (UTC ${s.next_run_at || "—"}).` +
    now +
    ` Tell the user this time. The cron hour is already ${tz}; do not add the UTC offset.`
  );
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "schedule_list",
    label: "List schedules",
    description:
      "List this bot's scheduled tasks. cron and next_run_local are the user timezone; cron_utc and next_run_at are UTC.",
    parameters: Type.Object({}),
    execute: async () => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Events API not configured.");
      const res = await api("GET", `/bots/${encodeURIComponent(cfg.bot)}/schedules`);
      if (!res.ok) return textResult(`schedule_list failed: ${errMsg(res)}`);
      const rows = Array.isArray(res.data) ? res.data : [];
      if (!rows.length) return textResult("No schedules.");
      const lines = rows.map((s: any) => {
        const on = s.enabled ? "on" : "off";
        const once = s.recurring ? "recurring" : "one-shot";
        return (
          `- ${s.id} «${s.name}» cron=\`${s.cron}\` ${s.timezone || "local"} ` +
          `(stored UTC \`${s.cron_utc || s.cron}\`) ${once} [${on}] ` +
          `next=${s.next_run_local || s.next_run_at || "—"} ${s.timezone || ""} ` +
          `(UTC ${s.next_run_at || "—"})`
        );
      });
      return textResult("Schedules (local cron, UTC instants):\n" + lines.join("\n"));
    },
  });

  pi.registerTool({
    name: "schedule_create",
    label: "Create schedule",
    description:
      "Create a schedule in the user's timezone (named in the system prompt, from Settings). "
      + "cron = 5 fields (minute hour day-of-month month day-of-week), "
      + "e.g. 09:00 in that zone = '0 9 * * 1-5'. The server stores the UTC equivalent. "
      + "Before a relative time (« in N minutes »), read the clock with vm_terminal_exec "
      + "as `TZ=<user timezone> date` — it asks for a terminal VM if needed. "
      + "Never pass -u / --utc: `date -u` is UTC and ignores TZ=. "
      + "Never invent the hour, do not add the UTC offset to the cron hour, "
      + "and do not use the VM clock's own zone. "
      + "The tool result's Next fire line is the time you tell the user. "
      + "recurring=false → delete after the fire, unless the next slot is within 15 minutes "
      + "(a short burst, e.g. every 5 min). For one hour of 5-min reminders, pin the day and hour "
      + "('25-55/5 11 1 11 *'), not hour '*'. "
      + "instruction is injected as a user chat message when it fires. "
      + "If you need to relaunch yourself later, call this yourself — do not ask permission, "
      + "and do not merely echo a reminder in the shell.",
    parameters: Type.Object({
      name: Type.String({ description: "Short label" }),
      cron: Type.String({
        description: "5-field cron in the user timezone, e.g. '0 9 * * 1-5'",
      }),
      instruction: Type.Optional(
        Type.String({ description: "What the bot should do when it fires" }),
      ),
      recurring: Type.Optional(
        Type.Boolean({
          description: "true (default) = keep firing; false = delete after the fire, or after a burst of slots ≤15 min apart",
        }),
      ),
      anchor_message_id: Type.Optional(
        Type.String({ description: "Optional chat message id for context" }),
      ),
      enabled: Type.Optional(Type.Boolean()),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Events API not configured.");
      const body: Json = {
        name: String(params.name || ""),
        cron: String(params.cron || ""),
        instruction: String(params.instruction || ""),
        recurring: params.recurring !== false,
        enabled: params.enabled !== false,
      };
      if (params.anchor_message_id) {
        body.anchor_message_id = String(params.anchor_message_id);
      }
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/schedules`,
        body,
      );
      if (!res.ok) return textResult(`schedule_create failed: ${errMsg(res)}`);
      const s = res.data || {};
      return textResult(
        `Schedule created: ${s.id} «${s.name}» local=\`${s.cron}\` ${s.timezone || ""} ` +
          `utc=\`${s.cron_utc || ""}\`. ${fireLine(s)}`,
        { schedule: s },
      );
    },
  });

  pi.registerTool({
    name: "schedule_update",
    label: "Update schedule",
    description:
      "Patch a schedule. cron, when set, is in the user timezone (same as schedule_create).",
    parameters: Type.Object({
      id: Type.String({ description: "Schedule id" }),
      name: Type.Optional(Type.String()),
      cron: Type.Optional(Type.String()),
      instruction: Type.Optional(Type.String()),
      recurring: Type.Optional(Type.Boolean()),
      anchor_message_id: Type.Optional(Type.String()),
      enabled: Type.Optional(Type.Boolean()),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Events API not configured.");
      const sid = String(params.id || "");
      const body: Json = {};
      for (const k of [
        "name",
        "cron",
        "instruction",
        "recurring",
        "anchor_message_id",
        "enabled",
      ] as const) {
        if (params[k] !== undefined) body[k] = params[k];
      }
      const res = await api(
        "PATCH",
        `/bots/${encodeURIComponent(cfg.bot)}/schedules/${encodeURIComponent(sid)}`,
        body,
      );
      if (!res.ok) return textResult(`schedule_update failed: ${errMsg(res)}`);
      const s = res.data || {};
      return textResult(`Schedule updated: ${sid}. ${fireLine(s)}`, { schedule: s });
    },
  });

  pi.registerTool({
    name: "schedule_delete",
    label: "Delete schedule",
    description: "Delete a scheduled task by id.",
    parameters: Type.Object({
      id: Type.String({ description: "Schedule id" }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Events API not configured.");
      const sid = String(params.id || "");
      const res = await api(
        "DELETE",
        `/bots/${encodeURIComponent(cfg.bot)}/schedules/${encodeURIComponent(sid)}`,
      );
      if (!res.ok) return textResult(`schedule_delete failed: ${errMsg(res)}`);
      return textResult(`Schedule deleted: ${sid}`);
    },
  });

  pi.registerTool({
    name: "webhook_list",
    label: "List webhooks",
    description: "List this bot's inbound webhooks (tokenized public URLs).",
    parameters: Type.Object({}),
    execute: async () => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Events API not configured.");
      const res = await api("GET", `/bots/${encodeURIComponent(cfg.bot)}/webhooks`);
      if (!res.ok) return textResult(`webhook_list failed: ${errMsg(res)}`);
      const rows = Array.isArray(res.data) ? res.data : [];
      if (!rows.length) return textResult("No webhooks.");
      const lines = rows.map((w: any) => {
        const on = w.enabled ? "on" : "off";
        const ep = w.url || w.url_path || "/api/v1/hooks";
        return `- ${w.id} «${w.name}» [${on}] POST ${ep} Authorization: Bearer <token>`;
      });
      return textResult("Webhooks:\n" + lines.join("\n"));
    },
  });

  pi.registerTool({
    name: "webhook_create",
    label: "Create webhook",
    description:
      "Create an inbound webhook. Fire with POST `/api/v1/hooks` and "
      + "`Authorization: Bearer <token>` (token not in the URL). "
      + "Injects a chat message for this bot.",
    parameters: Type.Object({
      name: Type.String({ description: "Short label" }),
      instruction: Type.Optional(
        Type.String({ description: "Extra instruction appended on fire" }),
      ),
      anchor_message_id: Type.Optional(Type.String()),
      enabled: Type.Optional(Type.Boolean()),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Events API not configured.");
      const body: Json = {
        name: String(params.name || ""),
        instruction: String(params.instruction || ""),
        enabled: params.enabled !== false,
      };
      if (params.anchor_message_id) {
        body.anchor_message_id = String(params.anchor_message_id);
      }
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/webhooks`,
        body,
      );
      if (!res.ok) return textResult(`webhook_create failed: ${errMsg(res)}`);
      const w = res.data || {};
      const ep = w.url || w.url_path || "/api/v1/hooks";
      return textResult(
        `Webhook created: ${w.id} «${w.name}»\n`
          + `POST ${ep}\nAuthorization: Bearer ${w.token || "<token>"}`,
        { webhook: w },
      );
    },
  });

  pi.registerTool({
    name: "webhook_update",
    label: "Update webhook",
    description: "Patch a webhook (name, instruction, enabled).",
    parameters: Type.Object({
      id: Type.String({ description: "Webhook id" }),
      name: Type.Optional(Type.String()),
      instruction: Type.Optional(Type.String()),
      anchor_message_id: Type.Optional(Type.String()),
      enabled: Type.Optional(Type.Boolean()),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Events API not configured.");
      const wid = String(params.id || "");
      const body: Json = {};
      for (const k of [
        "name",
        "instruction",
        "anchor_message_id",
        "enabled",
      ] as const) {
        if (params[k] !== undefined) body[k] = params[k];
      }
      const res = await api(
        "PATCH",
        `/bots/${encodeURIComponent(cfg.bot)}/webhooks/${encodeURIComponent(wid)}`,
        body,
      );
      if (!res.ok) return textResult(`webhook_update failed: ${errMsg(res)}`);
      return textResult(`Webhook updated: ${wid}`, { webhook: res.data });
    },
  });

  pi.registerTool({
    name: "webhook_delete",
    label: "Delete webhook",
    description: "Delete an inbound webhook by id (URL stops working).",
    parameters: Type.Object({
      id: Type.String({ description: "Webhook id" }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Events API not configured.");
      const wid = String(params.id || "");
      const res = await api(
        "DELETE",
        `/bots/${encodeURIComponent(cfg.bot)}/webhooks/${encodeURIComponent(wid)}`,
      );
      if (!res.ok) return textResult(`webhook_delete failed: ${errMsg(res)}`);
      return textResult(`Webhook deleted: ${wid}`);
    },
  });
}
