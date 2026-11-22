/**
 * Keep each provider request inside the model's image budget.
 *
 * Tool screenshots (MCP and others) stay in the Pi session, so the next turn
 * used to resend every one of them and the provider answered
 * "At most N image(s)". This hook runs before each LLM call and leaves only
 * the newest N image blocks in the request. The session file is unchanged.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Block = { type?: string; text?: string };
type Msg = { role?: string; content?: string | Block[] };

const PLACEHOLDER =
  "(earlier image omitted: this model accepts only a few images per request; the picture is still in the chat)";

export function visionCap(): number {
  let cap = parseCap(process.env.AUTONOMOUS_MAX_IMAGES, 2);
  const home = (process.env.AUTONOMOUS_HOME || "").trim();
  const bot = (process.env.AUTONOMOUS_BOT || "").trim();
  if (!home || !bot) return cap;
  try {
    const text = readFileSync(join(home, "bots", bot, "pi", "vision_image_cap"), "utf8");
    const tighter = parseCap(text, 0);
    if (tighter >= 1) cap = Math.min(cap, tighter);
  } catch {
    // No learned cap yet.
  }
  return cap;
}

function parseCap(raw: string | undefined, fallback: number): number {
  const n = Number.parseInt(String(raw ?? "").trim(), 10);
  if (!Number.isFinite(n) || n < 1) return fallback;
  return Math.min(32, n);
}

export function capVisionMessages<T extends Msg>(messages: T[], cap: number): T[] {
  const limit = Math.max(1, Math.min(32, cap));
  const slots: { mi: number; bi: number }[] = [];
  messages.forEach((msg, mi) => {
    if (msg.role !== "user" && msg.role !== "toolResult") return;
    if (!Array.isArray(msg.content)) return;
    msg.content.forEach((block, bi) => {
      if (block?.type === "image") slots.push({ mi, bi });
    });
  });
  if (slots.length <= limit) return messages;
  const drop = new Set(
    slots.slice(0, slots.length - limit).map((slot) => `${slot.mi}:${slot.bi}`),
  );
  return messages.map((msg, mi) => {
    if (!Array.isArray(msg.content)) return msg;
    if (!msg.content.some((_, bi) => drop.has(`${mi}:${bi}`))) return msg;
    const content: Block[] = [];
    let noted = false;
    msg.content.forEach((block, bi) => {
      if (drop.has(`${mi}:${bi}`)) {
        if (!noted) {
          content.push({ type: "text", text: PLACEHOLDER });
          noted = true;
        }
        return;
      }
      content.push(block);
      noted = false;
    });
    return { ...msg, content };
  });
}

export default function (pi: ExtensionAPI) {
  pi.on("context", (event) => {
    const next = capVisionMessages(event.messages, visionCap());
    if (next === event.messages) return;
    return { messages: next };
  });
}
