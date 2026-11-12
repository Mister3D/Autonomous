/**
 * Autonomous VM tools for Pi (server-side).
 *
 * Commands run via the Autonomous API → docker exec in the bot container.
 * No browser / UI required — safe for future automations.
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

function errMessage(data: any, status: number): string {
  return data?.message || data?.error || `HTTP ${status}`;
}

/**
 * Post a desk_request card (if needed) and BLOCK until the VM is running,
 * the user denies, abort, or timeout — same pattern as vault requests.
 * Do not return early: the LLM would keep calling other tools for nothing.
 */
async function requestAndWaitDesk(
  cfg: { base: string; token: string; bot: string },
  opts: {
    reason?: string;
    signal?: AbortSignal;
  } = {},
): Promise<ReturnType<typeof textResult>> {
  const reason =
    String(opts.reason || "").trim() ||
    "Le bot a besoin de sa VM (terminal et écran) pour continuer.";

  const desk0 = await api("GET", `/bots/${encodeURIComponent(cfg.bot)}/desk`);
  const desk0State = desk0.ok ? String(desk0.data?.state || "") : "";

  if (desk0State === "running") {
    return textResult("Desk already running — no authorization needed.", {
      ok: true,
      state: "running",
    });
  }

  if (desk0State === "sleeping") {
    const woke = await api("POST", `/bots/${encodeURIComponent(cfg.bot)}/desk/wake`);
    if (woke.ok && String(woke.data?.state || "") === "running") {
      return textResult("Desk was sleeping — woken automatically. Continue with VM tools.", {
        ok: true,
        state: "running",
        woken: true,
      });
    }
  }

  const posted = await api("POST", `/bots/${encodeURIComponent(cfg.bot)}/desk/request`, {
    reason,
  });
  if (!posted.ok) {
    return textResult(errMessage(posted.data, posted.status), { error: true });
  }

  const started = Date.now();
  const maxMs = 60 * 60 * 1000;
  while (!opts.signal?.aborted && Date.now() - started < maxMs) {
    await new Promise((r) => setTimeout(r, 2000));
    if (opts.signal?.aborted) break;
    const st = await api("GET", `/bots/${encodeURIComponent(cfg.bot)}/desk`);
    if (!st.ok) continue;
    const desk = st.data || {};
    if (desk.state === "running") {
      return textResult(
        "User authorized the desk — now running. Continue with VM tools.",
        {
          ok: true,
          state: "running",
          message_id: posted.data?.message_id || null,
        },
      );
    }
    if (desk.pending_state === "denied") {
      return textResult("User denied desk authorization. Do not invent a workaround.", {
        ok: false,
        error: true,
        state: "denied",
      });
    }
    // pending | creating | starting | sleeping → keep waiting
  }
  if (opts.signal?.aborted) {
    return textResult("Aborted while waiting for desk authorization.", {
      error: true,
      state: "aborted",
    });
  }
  return textResult("Timed out waiting for desk authorization.", {
    error: true,
    state: "timeout",
  });
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "vm_desk_status",
    label: "VM desk status",
    description:
      "Check whether this bot's VM is running (one container: shell and desktop). " +
      "If the desk is missing, call vm_request_desk (it waits for the user) — do not keep calling other tools.",
    parameters: Type.Object({}),
    execute: async () => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const botRes = await api("GET", `/bots/${encodeURIComponent(cfg.bot)}`);
      if (!botRes.ok) {
        return textResult(`Cannot load bot: ${errMessage(botRes.data, botRes.status)}`);
      }
      const bot = botRes.data || {};
      const desk = bot.desk || null;
      const lines = [
        `bot: ${cfg.bot}`,
        `capability: ${bot.capability || "none"}`,
        `desk.state: ${desk?.state || "none"}`,
        desk?.container_id ? `container: ${desk.container_id}` : "container: —",
        desk?.last_error ? `last_error: ${desk.last_error}` : null,
        bot.internet === false ? "internet: off" : "internet: on",
      ].filter(Boolean);
      const cap = bot.capability || "none";
      const deskState = desk?.state || "none";
      if (deskState === "sleeping") {
        lines.push(
          "Desk is sleeping. VM tools (vm_terminal_exec, screenshot, browser…) wake it " +
            "automatically — do NOT call vm_request_desk just to wake.",
        );
      } else if (cap === "none" || !desk || deskState !== "running") {
        lines.push(
          "Desk not ready. Call vm_request_desk — " +
            "that tool BLOCKS until the user authorizes. Do NOT call other tools meanwhile.",
        );
      }
      return textResult(lines.join("\n"), {
        capability: bot.capability,
        desk_state: desk?.state || null,
      });
    },
  });

  pi.registerTool({
    name: "vm_request_desk",
    label: "Request desk authorization",
    description:
      "Ask the user to authorize creating this bot's VM (shell and desktop together). " +
      "Posts a chat card and WAITS until the desk is running or denied (like vault). " +
      "Do NOT call other tools after this — the tool only returns when authorization is resolved.",
    parameters: Type.Object({
      reason: Type.Optional(
        Type.String({ description: "Short reason shown on the authorization card." }),
      ),
    }),
    execute: async (_id, params, signal) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      return requestAndWaitDesk(cfg, {
        reason: String(params.reason || "").trim(),
        signal,
      });
    },
  });

  pi.registerTool({
    name: "vm_screenshot",
    label: "VM screenshot",
    description:
      "Take a screenshot of this bot's desktop (server-side X11 capture). " +
      "Returns the image for tool-chaining / vision, and can post it in the chat. " +
      "Works without the user having the UI open. Requires a running desk.",
    parameters: Type.Object({
      show_in_chat: Type.Optional(
        Type.Boolean({
          description:
            "If true (default), also show the screenshot in the conversation for the user. Set false for silent tool-chain use.",
        }),
      ),
    }),
    execute: async (_id, params, signal) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const showInChat = params.show_in_chat !== false;
      // Never attach PNG to the LLM tool result — some providers
      // cap images/prompt; pixel vision goes through vm_ground (UI-TARS).
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/screen/screenshot`,
        { show_in_chat: showInChat },
      );
      if (!res.ok) {
        const code = res.data?.code || "";
        let hint = errMessage(res.data, res.status);
        if (code === "no_capability" || code === "desk_not_running") {
          // Block until the user authorizes — don't return early so the LLM keeps going.
          const wait = await requestAndWaitDesk(cfg, {
            reason: "Screenshot impossible sans VM.",
            signal,
          });
          if (wait.details && (wait.details as Json).state === "running") {
            const retry = await api(
              "POST",
              `/bots/${encodeURIComponent(cfg.bot)}/screen/screenshot`,
              { show_in_chat: showInChat },
            );
            if (retry.ok) {
              const shot = retry.data || {};
              return textResult(
                `Screenshot captured ${shot.width || "?"}×${shot.height || "?"}.\n` +
                  `id: ${shot.id || ""}\n` +
                  `url: ${shot.url || ""}\n` +
                  "(Desk was authorized during this call.)",
                {
                  screenshot_id: String(shot.id || ""),
                  url: String(shot.url || ""),
                  width: shot.width,
                  height: shot.height,
                },
              );
            }
            hint = errMessage(retry.data, retry.status);
          } else {
            return wait;
          }
        }
        return textResult(hint, { error: true, code });
      }
      const shot = res.data || {};
      const shotId = String(shot.id || "");
      const url = String(shot.url || "");
      const w = shot.width || "?";
      const h = shot.height || "?";
      const text =
        `Screenshot captured ${w}×${h}.\n` +
        `id: ${shotId}\n` +
        `url: ${url}\n` +
        (showInChat
          ? "Also posted in the chat for the user."
          : "Not posted in chat (show_in_chat=false).") +
        "\n(PNG never attached to the model — use vm_ground for pixel localization.)";
      return textResult(text, {
        screenshot_id: shotId,
        url,
        width: shot.width,
        height: shot.height,
      });
    },
  });

  pi.registerTool({
    name: "vm_look",
    label: "VM look (read the screen)",
    description:
      "Your EYES (expensive). Fresh desktop screenshot → multimodal model → plain-text " +
      "description: page/site, exact visible text (errors, banners, dialogs), blockers " +
      "(consent layer, modal, verification widget, access-denied page, login wall), form " +
      "state (empty / filled / validation errors) and key data shown. " +
      "Not the first step when browser_snapshot already lists the control. Use it " +
      "when that read was empty or inconclusive, after a gesture you cannot " +
      "verify, and before you tell the user what went wrong. Do not call it " +
      "twice in a row with no gesture between them. Optional `question` is " +
      "answered first. NEVER click coordinates it states — they are guesses. " +
      "Click screen= from browser_snapshot, or vm_ground when the control is not " +
      "in the DOM.",
    parameters: Type.Object({
      question: Type.Optional(
        Type.String({
          description: "Specific thing to check, e.g. 'Is there an error under the password field?'",
        }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = { show_in_chat: false };
      if (params.question) body.question = String(params.question);
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/screen/describe`,
        body,
      );
      if (!res.ok) {
        return textResult(`vm_look failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      if (res.data?.ok === false) {
        const why = String(res.data?.text || errMessage(res.data, res.status) || "").trim();
        return textResult(
          why
            ? `vm_look refused: ${why}`
            : "vm_look refused.",
          { error: true, code: res.data?.code || "dom_observe_required" },
        );
      }
      return textResult(String(res.data?.text || "(no description)"), {
        ok: true,
        screenshot_id: res.data?.screenshot_id,
      });
    },
  });

  pi.registerTool({
    name: "vm_ground",
    label: "GUI ground",
    description:
      "Locate a UI element on a FRESH desk screenshot via UI-TARS + optional judge. " +
      "Returns geometry only — does NOT act. Use it when browser_snapshot / " +
      "browser_frames_snapshot does NOT list the control (canvas, image, native " +
      "dialog, drawn widget). If the control has screen=x,y, vm_click that " +
      "instead — this call is slow. " +
      "Pass that choice as action_hint. Instruction in English. If ok=false, " +
      "do not invent coordinates. Then: action=click → vm_click; action=drag → " +
      "vm_drag(x,y,x2,y2) press-drag-release (never click a slider).",
    parameters: Type.Object({
      instruction: Type.String({
        description:
          "What to find, in English (name the visible control, e.g. handle / button).",
      }),
      action_hint: Type.Optional(
        Type.String({
          description:
            "Gesture already decided: click | left_click | right_click | double | drag | scroll.",
        }),
      ),
      verify: Type.Optional(
        Type.Boolean({
          description: "Run multimodal hollow-cross verification (default true)",
        }),
      ),
      show_in_chat: Type.Optional(
        Type.Boolean({
          description:
            "Post capture, crosshair sheets and verify steps for every loop in chat (default true)",
        }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {
        instruction: params.instruction,
        verify: params.verify !== false,
        check_exists: true,
        show_in_chat: params.show_in_chat !== false,
      };
      if (params.action_hint) body.action_hint = params.action_hint;
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/screen/ground`,
        body,
      );
      if (!res.ok) {
        return textResult(
          `vm_ground failed: ${errMessage(res.data, res.status)}`,
          { error: true },
        );
      }
      const d = res.data || {};
      if (!d.ok) {
        return textResult(
          [
            `Grounding failed (ok=false). Do NOT click or invent coordinates.`,
            `status: ${d.status || "?"}`,
            d.error ? `error: ${d.error}` : "",
            d.grounder_raw ? `grounder: ${d.grounder_raw}` : "",
          ]
            .filter(Boolean)
            .join("\n"),
          { ok: false, status: d.status, error: d.error },
        );
      }
      const action = String(d.action || "click");
      const lines = [
        "Grounding ok — no gesture performed yet.",
        `action: ${action}`,
        `x: ${d.x}`,
        `y: ${d.y}`,
      ];
      if (d.x2 != null) lines.push(`x2: ${d.x2}`, `y2: ${d.y2}`);
      if (d.direction) lines.push(`direction: ${d.direction}`);
      if (d.verifier?.answer) lines.push(`verifier: ${d.verifier.answer}`);
      if (action === "drag") {
        lines.push(
          "NEXT REQUIRED: call vm_drag with these x,y,x2,y2 (press–drag–release). Do NOT vm_click.",
        );
      } else if (action === "click" || action === "left_double" || action === "right_single") {
        lines.push("NEXT: call vm_click with these x,y (unless you need another ground).");
      }
      return textResult(lines.join("\n"), {
        ok: true,
        action,
        x: d.x,
        y: d.y,
        x2: d.x2,
        y2: d.y2,
        screenshot_id: d.screenshot_id,
      });
    },
  });

  pi.registerTool({
    name: "vm_click",
    label: "VM click",
    description:
      "Click at desktop pixel coordinates with a real pointer (VNC): the mouse " +
      "glides there. This is the only click. Coordinates come from " +
      "browser_snapshot / browser_frames_snapshot (screen=x,y) or from vm_ground " +
      "(ok=true). Never from vm_look, never a point vm_ground rejected, never " +
      "browser_click_selector. Do NOT use it on sliders — use vm_drag. " +
      "button: left (default), right, middle, double, or move = HOVER only " +
      "(menus that open on mouse-over; then snapshot again).",
    parameters: Type.Object({
      x: Type.Number({ description: "X pixel on the original screenshot / desk" }),
      y: Type.Number({ description: "Y pixel on the original screenshot / desk" }),
      button: Type.Optional(
        Type.String({ description: "left|right|middle|double|move (default left)" }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {
        x: Math.round(Number(params.x)),
        y: Math.round(Number(params.y)),
        button: String(params.button || "left").toLowerCase(),
      };
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/screen/click`,
        body,
      );
      if (!res.ok) {
        return textResult(`vm_click failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const d = res.data || {};
      return textResult(
        d.button === "move"
          ? `Moved the pointer to (${d.x},${d.y}) (hover).`
          : `Clicked ${d.button || "left"} at (${d.x},${d.y}).`,
        { ok: true, x: d.x, y: d.y, button: d.button },
      );
    },
  });

  pi.registerTool({
    name: "vm_type",
    label: "VM type",
    description:
      "Type or paste text into the currently focused desk window via VNC keystrokes. " +
      "Click the field first (vm_click) — never use it for secrets (use vault_type). " +
      "The address bar is only for a Google search: click it, type the query, " +
      "Enter. Never type a site URL there. method=type (default) or paste.",
    parameters: Type.Object({
      text: Type.String({ description: "Text to type into the focused control" }),
      method: Type.Optional(
        Type.String({ description: "type (keystrokes) or paste (clipboard + Ctrl+Shift+V)" }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const method = String(params.method || "type").toLowerCase();
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/screen/type`,
        {
          text: String(params.text ?? ""),
          method: method === "paste" ? "paste" : "type",
        },
      );
      if (!res.ok) {
        return textResult(`vm_type failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const d = res.data || {};
      return textResult(
        `Typed ${d.chars} char(s) via ${d.method}.`,
        { ok: true, chars: d.chars, method: d.method },
      );
    },
  });

  pi.registerTool({
    name: "vm_scroll",
    label: "VM scroll",
    description:
      "Real mouse-wheel scroll on the desk via VNC. dy>0 scrolls content down " +
      "(read further); dy<0 up. Optional x,y = pointer position (defaults center-ish). " +
      "Prefer this over browser_scroll when browsing visually.",
    parameters: Type.Object({
      dy: Type.Number({
        description: "Vertical scroll delta in pixels (e.g. 400). Sign: >0 = down.",
      }),
      x: Type.Optional(Type.Number({ description: "Pointer X (optional)" })),
      y: Type.Optional(Type.Number({ description: "Pointer Y (optional)" })),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = { dy: Math.round(Number(params.dy)) };
      if (params.x != null) body.x = Math.round(Number(params.x));
      if (params.y != null) body.y = Math.round(Number(params.y));
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/screen/scroll`,
        body,
      );
      if (!res.ok) {
        return textResult(`vm_scroll failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const d = res.data || {};
      return textResult(`Scrolled dy=${d.dy} at (${d.x || 0},${d.y || 0}).`, {
        ok: true,
        dy: d.dy,
      });
    },
  });

  pi.registerTool({
    name: "vm_key",
    label: "VM key",
    description:
      "Press a named key via VNC: Return, Tab, Escape, BackSpace, Delete, " +
      "Left/Up/Right/Down, Page_Up, Page_Down, Home, End, space. Optional repeats.",
    parameters: Type.Object({
      key: Type.String({ description: "Key name, e.g. Return or Page_Down" }),
      repeats: Type.Optional(
        Type.Number({ description: "How many times (default 1, max 50)" }),
      ),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/screen/key`,
        {
          key: String(params.key || ""),
          repeats: Math.max(1, Math.min(Number(params.repeats) || 1, 50)),
        },
      );
      if (!res.ok) {
        return textResult(`vm_key failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const d = res.data || {};
      return textResult(`Key ${d.key} ×${d.repeats}.`, {
        ok: true,
        key: d.key,
        repeats: d.repeats,
      });
    },
  });

  pi.registerTool({
    name: "vm_drag",
    label: "VM drag",
    description:
      "Drag with the left mouse button from (x,y) to (x2,y2) via VNC. " +
      "Coordinates from browser_frames_snapshot (handle center → end of track) or vm_ground " +
      "(action=drag). For slide-to-verify widgets: ONE drag. Do not invent coordinates.",
    parameters: Type.Object({
      x: Type.Number({ description: "Start X" }),
      y: Type.Number({ description: "Start Y" }),
      x2: Type.Number({ description: "End X" }),
      y2: Type.Number({ description: "End Y" }),
    }),
    execute: async (_id, params) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const body: Json = {
        x: Math.round(Number(params.x)),
        y: Math.round(Number(params.y)),
        x2: Math.round(Number(params.x2)),
        y2: Math.round(Number(params.y2)),
      };
      const res = await api(
        "POST",
        `/bots/${encodeURIComponent(cfg.bot)}/screen/drag`,
        body,
      );
      if (!res.ok) {
        return textResult(`vm_drag failed: ${errMessage(res.data, res.status)}`, {
          error: true,
        });
      }
      const d = res.data || {};
      return textResult(
        `Dragged (${d.x},${d.y}) → (${d.x2},${d.y2}).`,
        { ok: true, x: d.x, y: d.y, x2: d.x2, y2: d.y2 },
      );
    },
  });

  pi.registerTool({
    name: "vm_terminal_exec",
    label: "VM terminal",
    description:
      "Run a non-interactive shell command inside this bot's desktop VM (server-side docker exec). " +
      "This is the shell for date, curl, ping, and any other command. " +
      "If there is no desk, this call asks the user for the VM and waits — do not invent the output. " +
      "There is no host bash on the Autonomous server. Works even when no user has the web UI open. " +
      "cwd is /home/autonomous/workspace. For reading/writing bot files prefer files_list/read/write (no desk needed). " +
      "Prefer short commands; raise timeout for long ones. " +
      "Do NOT use for interactive TUIs (nano/vim/top) — those need the Terminal tab PTY.",
    parameters: Type.Object({
      command: Type.String({
        description: "Shell command, e.g. 'uname -a' or 'ls -la'",
      }),
      timeout: Type.Optional(
        Type.Number({
          description: "Seconds (default 30, max 600)",
          minimum: 1,
          maximum: 600,
        }),
      ),
    }),
    execute: async (_id, params, signal) => {
      const cfg = apiConfig();
      if (!cfg) {
        return textResult("Autonomous API not configured for this Pi session.");
      }
      const command = String(params.command || "").trim();
      if (!command) {
        return textResult("command is required");
      }
      const timeout = Math.max(1, Math.min(Number(params.timeout) || 30, 600));
      const res = await api("POST", `/bots/${encodeURIComponent(cfg.bot)}/terminal/exec`, {
        command,
        timeout,
      });
      if (!res.ok) {
        const code = String(res.data?.error_code || res.data?.code || "");
        let hint = errMessage(res.data, res.status);
        if (code === "no_capability" || code === "desk_not_running") {
          const wait = await requestAndWaitDesk(cfg, {
            reason: "Commande VM impossible sans bureau.",
            signal,
          });
          if (wait.details && (wait.details as Json).state === "running") {
            const retry = await api(
              "POST",
              `/bots/${encodeURIComponent(cfg.bot)}/terminal/exec`,
              { command, timeout },
            );
            if (retry.ok) {
              const entry = retry.data || {};
              const output = String(entry.output ?? "");
              return textResult(
                `$ ${command}\nexit_code=${entry.exit_code}` +
                  (output.length ? `\n${output}` : "\n(no output)") +
                  "\n(Desk was authorized during this call.)",
                { exit_code: entry.exit_code, log_id: entry.id },
              );
            }
            hint = errMessage(retry.data, retry.status);
          } else {
            return wait;
          }
        }
        return textResult(hint, { error: true, code });
      }
      const entry = res.data || {};
      const exitCode = entry.exit_code;
      const output = String(entry.output ?? "");
      const header = `$ ${command}\nexit_code=${exitCode}`;
      const body = output.length ? `\n${output}` : "\n(no output)";
      return textResult(header + body, {
        exit_code: exitCode,
        log_id: entry.id,
      });
    },
  });
}
