/**
 * Bot ~/shared (workspace) file tools — no desk required.
 * Same volume as the Files inspector and VM ~/workspace.
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
    body: body === undefined ? undefined : JSON.stringify(body),
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

function q(path: string): string {
  return encodeURIComponent(path || ".");
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "files_list",
    label: "List bot files",
    description:
      "List files/folders in this bot's shared workspace (~/shared = ~/workspace). " +
      "No running desk required. Prefer this over vm_terminal_exec when you only need to browse bot files.",
    parameters: Type.Object({
      path: Type.Optional(
        Type.String({
          description: "Relative path under ~/shared (default: root '.')",
        }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Autonomous API not configured.");
      const path = String(params.path || ".").trim() || ".";
      const res = await api(
        "GET",
        `/bots/${encodeURIComponent(cfg.bot)}/files?path=${q(path)}`,
      );
      if (!res.ok) {
        return textResult(errMessage(res.data, res.status), { error: true });
      }
      const entries = Array.isArray(res.data) ? res.data : [];
      if (!entries.length) {
        return textResult(`(empty) ${path}`, { path, entries: [] });
      }
      const lines = entries.map((e: any) => {
        const kind = e.is_dir ? "dir " : "file";
        const size = e.is_dir ? "" : ` ${e.size ?? 0}B`;
        return `${kind}\t${e.path}${size}`;
      });
      return textResult(lines.join("\n"), { path, entries });
    },
  });

  pi.registerTool({
    name: "files_read",
    label: "Read bot file",
    description:
      "Read a UTF-8 text file from this bot's ~/shared workspace. " +
      "Binary files are rejected — use Files panel download instead.",
    parameters: Type.Object({
      path: Type.String({ description: "Relative path, e.g. 'notes.txt' or 'upload/.../x.md'" }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Autonomous API not configured.");
      const path = String(params.path || "").trim();
      if (!path) return textResult("path required", { error: true });
      const res = await api(
        "GET",
        `/bots/${encodeURIComponent(cfg.bot)}/files/content?path=${q(path)}`,
      );
      if (!res.ok) {
        return textResult(errMessage(res.data, res.status), { error: true });
      }
      const content = String(res.data?.content ?? "");
      const header = `path=${res.data?.path || path} size=${res.data?.size ?? content.length}`;
      return textResult(`${header}\n\n${content}`, {
        path: res.data?.path || path,
        size: res.data?.size,
      });
    },
  });

  pi.registerTool({
    name: "files_write",
    label: "Write bot file",
    description:
      "Create or overwrite a UTF-8 text file in this bot's ~/shared workspace. " +
      "Parents are created as needed. Visible in the Files inspector " +
      "and inside the VM at ~/workspace.",
    parameters: Type.Object({
      path: Type.String({ description: "Relative file path under ~/shared" }),
      content: Type.String({ description: "Full file contents (UTF-8)" }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Autonomous API not configured.");
      const path = String(params.path || "").trim();
      if (!path) return textResult("path required", { error: true });
      const content =
        params.content === undefined || params.content === null
          ? ""
          : String(params.content);
      const res = await api(
        "PUT",
        `/bots/${encodeURIComponent(cfg.bot)}/files/content`,
        { path, content },
      );
      if (!res.ok) {
        return textResult(errMessage(res.data, res.status), { error: true });
      }
      return textResult(
        `Wrote ${res.data?.path || path} (${res.data?.size ?? content.length} bytes)`,
        { entry: res.data },
      );
    },
  });

  pi.registerTool({
    name: "files_mkdir",
    label: "Mkdir bot folder",
    description:
      "Create a directory under this bot's ~/shared workspace. ",
    parameters: Type.Object({
      path: Type.Optional(
        Type.String({ description: "Parent directory (default '.')" }),
      ),
      name: Type.String({ description: "New folder name" }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Autonomous API not configured.");
      const name = String(params.name || "").trim();
      if (!name) return textResult("name required", { error: true });
      const parent = String(params.path || ".").trim() || ".";
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/files/mkdir`,
        { path: parent, name },
      );
      if (!res.ok) {
        return textResult(errMessage(res.data, res.status), { error: true });
      }
      return textResult(`Created directory ${res.data?.path || name}`, {
        entry: res.data,
      });
    },
  });

  pi.registerTool({
    name: "files_delete",
    label: "Delete bot file",
    description:
      "Delete a file or directory under this bot's ~/shared workspace. ",
    parameters: Type.Object({
      path: Type.String({ description: "Relative path to delete (not the shared root)" }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Autonomous API not configured.");
      const path = String(params.path || "").trim();
      if (!path || path === ".") {
        return textResult("Refuse to delete shared root — give a relative path.", {
          error: true,
        });
      }
      const res = await api(
        "DELETE",
        `/bots/${encodeURIComponent(cfg.bot)}/files?path=${q(path)}`,
      );
      if (!res.ok) {
        return textResult(errMessage(res.data, res.status), { error: true });
      }
      return textResult(`Deleted ${path}`, { path, ok: true });
    },
  });

  pi.registerTool({
    name: "files_share_image",
    label: "Share image in chat",
    description:
      "Prepare a workspace IMAGE (~/shared) to show INSIDE your reply text. " +
      "Returns a markdown image line — you MUST paste that exact markdown into your " +
      "assistant text (rendered inline). png/jpg/webp/gif/svg/bmp. " +
      "For PDF/zip/other non-preview files use files_attach instead. " +
      "No desk required, no vm_screenshot.",
    parameters: Type.Object({
      path: Type.String({
        description: "Relative image path under ~/shared, e.g. 'crabe.png'",
      }),
      caption: Type.Optional(
        Type.String({ description: "Alt text / caption for the markdown image" }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Autonomous API not configured.");
      const path = String(params.path || "").trim();
      if (!path) return textResult("path required", { error: true });
      const body: Json = { path };
      const caption = String(params.caption || "").trim();
      if (caption) body.caption = caption;
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/files/share`,
        body,
      );
      if (!res.ok) {
        return textResult(errMessage(res.data, res.status), { error: true });
      }
      const md = String(res.data?.markdown || "").trim();
      return textResult(
        md
          ? `Paste this exact markdown into your reply (inline image):\n\n${md}`
          : `Image ready: ${res.data?.url || path}`,
        { ...res.data, ok: true },
      );
    },
  });

  pi.registerTool({
    name: "files_attach",
    label: "Attach file in chat",
    description:
      "Attach a non-image workspace file (PDF, zip, doc, …) to your assistant reply " +
      "as a download card. Do NOT use for images — use files_share_image + markdown instead. " +
      "",
    parameters: Type.Object({
      path: Type.String({
        description: "Relative path under ~/shared, e.g. 'report.pdf'",
      }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Autonomous API not configured.");
      const path = String(params.path || "").trim();
      if (!path) return textResult("path required", { error: true });
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/files/attach`,
        { path },
      );
      if (!res.ok) {
        return textResult(errMessage(res.data, res.status), { error: true });
      }
      return textResult(
        `Attached ${res.data?.name || path} to your reply bubble (download card).`,
        { ...res.data, ok: true },
      );
    },
  });

  pi.registerTool({
    name: "files_claim_mail",
    label: "Place mail attachment",
    description:
      "Move a file received via inter-bot mail from staging "
      + "(.autonomous/mail-inbox/<id>/…) to a destination under YOUR ~/shared. "
      + "Use after bot_tell/bot_ask delivered attachments — you choose the final path. "
      + "Does not leave a copy in staging.",
    parameters: Type.Object({
      path: Type.String({
        description:
          "Staging path, e.g. '.autonomous/mail-inbox/<inbox_id>/spec.md'",
      }),
      dest: Type.String({
        description:
          "Destination relative path under ~/shared, e.g. 'projects/chat/spec.md'",
      }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) return textResult("Autonomous API not configured.");
      const path = String(params.path || "").trim();
      const dest = String(params.dest || "").trim();
      if (!path || !dest) {
        return textResult("path and dest required", { error: true });
      }
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/files/claim-mail`,
        { path, dest },
      );
      if (!res.ok) {
        return textResult(errMessage(res.data, res.status), { error: true });
      }
      return textResult(
        `Moved mail attachment to ${res.data?.path || dest}.`,
        { ...res.data, ok: true },
      );
    },
  });
}
