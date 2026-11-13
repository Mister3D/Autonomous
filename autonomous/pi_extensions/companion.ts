/**
 * MCP tools exposed by the user's paired companion (their own PC).
 *
 * The companion process owns the stdio MCP servers. This extension only
 * lists them and forwards calls through the Autonomous API.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Json = Record<string, unknown>;

function env(name: string): string {
  return (process.env[name] || "").trim();
}

function apiConfig(): { base: string; token: string } | null {
  const base = env("AUTONOMOUS_API_BASE").replace(/\/$/, "");
  const token = env("AUTONOMOUS_TOKEN");
  if (!base || !token) return null;
  return { base, token };
}

async function api(method: string, path: string, body?: Json) {
  const cfg = apiConfig();
  if (!cfg) {
    return { ok: false, status: 0, data: { error: "Autonomous API not configured." } };
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
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  return { ok: res.ok, status: res.status, data };
}

function textResult(text: string, details: Json = {}) {
  return { content: [{ type: "text" as const, text }], details };
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "mcp_list",
    label: "List companion MCP tools",
    description:
      "List MCP tools this bot is allowed to use on a companion PC. " +
      "Call this before mcp_call. An empty list means the user has not allowed " +
      "any companion MCP for this bot (Details), or none are published yet.",
    parameters: Type.Object({}),
    execute: async () => {
      const bot = env("AUTONOMOUS_BOT");
      if (!bot) return textResult("AUTONOMOUS_BOT is not set.", { error: true });
      const res = await api("GET", `/devices/mcp/tools?bot=${encodeURIComponent(bot)}`);
      if (!res.ok) {
        return textResult(res.data?.message || res.data?.error || `HTTP ${res.status}`, {
          error: true,
        });
      }
      const tools = Array.isArray(res.data?.tools) ? res.data.tools : [];
      if (!tools.length) {
        return textResult("No companion MCP tools are available right now.");
      }
      const lines = tools.map((tool: any) => {
        const online = tool.online ? "online" : "offline";
        const where = tool.device_name ? `${tool.device_name} / ` : "";
        return `- ${where}${tool.server} / ${tool.name} (${online}) ${tool.description || ""}`.trim();
      });
      return textResult(lines.join("\n"), { tools });
    },
  });

  pi.registerTool({
    name: "mcp_call",
    label: "Call companion MCP tool",
    description:
      "Call one MCP tool on the user's computer. Use the companion, server and tool names from mcp_list. " +
      "This bot can only call servers allowed in its details. " +
      "arguments_json is a JSON object string. The call runs on the companion PC, not in the VM. " +
      "Pass companion when several computers expose the same server name. " +
      "Screenshots and other images come back as image content and are shown in the chat. " +
      "Do not save them to the desktop, start a local web server, or re-encode them.",
    parameters: Type.Object({
      server: Type.String({ description: "MCP server name as shown by mcp_list." }),
      tool: Type.String({ description: "Tool name inside that server." }),
      companion: Type.Optional(
        Type.String({ description: "Companion name from mcp_list, when more than one matches." }),
      ),
      arguments_json: Type.Optional(
        Type.String({ description: "JSON object of arguments. Omit for {}." }),
      ),
    }),
    execute: async (_id, params) => {
      let args: Json = {};
      const raw = String(params.arguments_json || "").trim();
      if (raw) {
        try {
          args = JSON.parse(raw);
        } catch {
          return textResult("arguments_json must be a JSON object.");
        }
      }
      const bot = env("AUTONOMOUS_BOT");
      if (!bot) return textResult("AUTONOMOUS_BOT is not set.", { error: true });
      const res = await api("POST", "/devices/mcp/call", {
        bot,
        server: String(params.server || ""),
        tool: String(params.tool || ""),
        companion: String(params.companion || ""),
        arguments: args,
      });
      if (!res.ok) {
        return textResult(res.data?.message || res.data?.error || `HTTP ${res.status}`, {
          error: true,
        });
      }
      const images = Array.isArray(res.data?.images) ? res.data.images : [];
      const markdowns: string[] = [];
      const content: Array<
        { type: "text"; text: string } | { type: "image"; data: string; mimeType: string }
      > = [];
      for (const img of images) {
        const data = String(img?.data || "");
        const mime = String(img?.mime || img?.mimeType || "");
        const markdown = String(img?.markdown || "").trim();
        if (data && mime.startsWith("image/")) {
          content.push({ type: "image", data, mimeType: mime });
        }
        if (markdown.startsWith("![")) markdowns.push(markdown);
      }
      let text = String(res.data?.text || "");
      if (!text && markdowns.length) text = "Image captured.";
      if (markdowns.length) {
        text +=
          "\n\nThe image is already shown in the chat. Paste each markdown line exactly if you mention it:\n" +
          markdowns.join("\n");
      }
      content.unshift({ type: "text", text });
      return { content, details: { ok: true, images_md: markdowns } };
    },
  });

  pi.registerTool({
    name: "notify_user",
    label: "Notify the user",
    description:
      "Show a notification on the user's computer (tray icon, on-screen message, sound). " +
      "Call this ONLY when the user asked to be told about a specific event, for example " +
      "\"notify me when this email arrives\" or \"ping me when the job finishes\". " +
      "Do not call it for routine progress, every webhook, or every incoming message. " +
      "If the companion is offline the call fails and the user does not see it. " +
      "Do not restate the notification in your reply: the chat already shows a card.",
    parameters: Type.Object({
      title: Type.String({ description: "Short title, a few words." }),
      message: Type.String({ description: "What the user should know." }),
    }),
    execute: async (_id, params) => {
      const res = await api("POST", "/devices/notify", {
        title: String(params.title || ""),
        body: String(params.message || ""),
        bot: env("AUTONOMOUS_BOT"),
      });
      if (!res.ok) {
        return textResult(res.data?.message || res.data?.error || `HTTP ${res.status}`, {
          error: true,
        });
      }
      return textResult("Notification sent to the user's computer.", { ok: true });
    },
  });
}
