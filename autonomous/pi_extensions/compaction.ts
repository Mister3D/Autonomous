/**
 * Chunked compaction recovery (after Pi's first pass fails).
 *
 * 1. First compact attempt: this extension does nothing → Pi summarizes with the
 *    user's chosen thinking level.
 * 2. If that fails (`session_compact_failed`, non-abort), the next
 *    `session_before_compact` (usually overflow recovery) is handled here:
 *    split the span in half with a short overlap, summarize each half, merge.
 *    The same user thinking level is kept (not forced off).
 */

import { uuidv7 } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { convertToLlm, serializeConversation } from "@earendil-works/pi-coding-agent";

/** Messages from the end of the left half repeated at the start of the right half. */
const OVERLAP_MESSAGES = 4;
const MAX_DEPTH = 8;

const STRUCTURE_HINT = `Use this EXACT format:

## Goal
[What is the user trying to accomplish?]

## Constraints & Preferences
- [Requirements mentioned by the user, or "(none)"]

## Progress
### Done
- [x] [Completed work]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues, if any]

## Key Decisions
- **[Decision]**: [Rationale]

## Next Steps
1. [What should happen next]

## Critical Context
- [Facts, paths, IDs, credentials *labels* (never secret values) needed to continue]
`;

type AgentMessage = unknown;

type Usage = {
  input?: number;
  output?: number;
  totalTokens?: number;
  [key: string]: unknown;
};

type ShotResult = {
  text: string;
  incomplete: boolean;
};

function splitWithOverlap(messages: AgentMessage[]): {
  left: AgentMessage[];
  right: AgentMessage[];
} {
  const mid = Math.floor(messages.length / 2);
  const overlap = Math.min(OVERLAP_MESSAGES, mid, messages.length - mid);
  return {
    left: messages.slice(0, mid),
    right: messages.slice(Math.max(0, mid - overlap)),
  };
}

function extractText(response: {
  content?: Array<{ type: string; text?: string }>;
}): string {
  const parts = response.content || [];
  return parts
    .filter(
      (c): c is { type: "text"; text: string } =>
        c.type === "text" && typeof c.text === "string",
    )
    .map((c) => c.text)
    .join("\n")
    .trim();
}

function buildPrompt(
  conversationText: string,
  previousSummary: string | undefined,
  customInstructions: string | undefined,
): string {
  const focus = customInstructions?.trim()
    ? `\n\nAdditional focus: ${customInstructions.trim()}`
    : "";
  if (previousSummary?.trim()) {
    return (
      `<conversation>\n${conversationText}\n</conversation>\n\n` +
      `<previous-summary>\n${previousSummary.trim()}\n</previous-summary>\n\n` +
      `The messages above are NEW conversation messages to incorporate into the existing summary in <previous-summary>.\n` +
      `Produce an updated structured checkpoint that another LLM can use to continue the work.\n` +
      STRUCTURE_HINT +
      focus
    );
  }
  return (
    `<conversation>\n${conversationText}\n</conversation>\n\n` +
    `The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.\n` +
    STRUCTURE_HINT +
    focus
  );
}

export default function (pi: ExtensionAPI) {
  /** Set when Pi's default summarizer failed; cleared on success or our own failure. */
  let recoverWithChunks = false;

  pi.on("session_compact_failed", (event) => {
    if (event.aborted) return;
    if (event.fromExtension) {
      // Our recovery failed — do not loop forever.
      recoverWithChunks = false;
      return;
    }
    recoverWithChunks = true;
  });

  pi.on("session_compact", () => {
    recoverWithChunks = false;
  });

  pi.on("session_before_compact", async (event, ctx) => {
    // First pass: leave Pi alone (user thinking level, default one-shot summary).
    if (!recoverWithChunks) {
      return;
    }

    const { preparation, customInstructions, signal } = event;
    const model = ctx.model;
    if (!model) {
      return;
    }

    const {
      messagesToSummarize,
      turnPrefixMessages,
      tokensBefore,
      firstKeptEntryId,
      previousSummary,
    } = preparation;

    const allMessages: AgentMessage[] = [
      ...(messagesToSummarize || []),
      ...(turnPrefixMessages || []),
    ];
    if (allMessages.length === 0) {
      return;
    }

    const maxTokens = Math.max(
      1024,
      Math.min(Number(model.maxTokens) || 8192, 16384),
    );
    // Keep the user's reflection level (same as Pi's first pass).
    const thinkingLevel = ctx.thinkingLevel;
    const useReasoning =
      Boolean(model.reasoning) &&
      !!thinkingLevel &&
      thinkingLevel !== "off";

    let passes = 0;
    let usageAcc: Usage = {};

    const oneShot = async (
      messages: AgentMessage[],
      prev: string | undefined,
    ): Promise<ShotResult> => {
      passes += 1;
      const conversationText = serializeConversation(
        convertToLlm(messages as any),
      );
      const promptText = buildPrompt(
        conversationText,
        prev,
        customInstructions,
      );
      const options: Record<string, unknown> = {
        maxTokens,
        signal,
        cacheRetention: "none",
        sessionId: uuidv7(),
      };
      if (useReasoning) {
        options.reasoning = thinkingLevel;
      }
      const response = await ctx.modelRegistry.complete(
        model,
        {
          messages: [
            {
              role: "user",
              content: [{ type: "text", text: promptText }],
              timestamp: Date.now(),
            },
          ],
        },
        options as any,
      );
      const text = extractText(response);
      const incomplete =
        (response as { stopReason?: string }).stopReason === "length";
      const usage = (response as { usage?: Usage }).usage;
      if (usage && typeof usage === "object") {
        usageAcc = {
          ...usageAcc,
          input: (Number(usageAcc.input) || 0) + (Number(usage.input) || 0),
          output: (Number(usageAcc.output) || 0) + (Number(usage.output) || 0),
          totalTokens:
            (Number(usageAcc.totalTokens) || 0) +
            (Number(usage.totalTokens) || 0),
        };
      }
      return { text, incomplete };
    };

    const summarizeChunked = async (
      messages: AgentMessage[],
      prev: string | undefined,
      depth: number,
    ): Promise<string> => {
      if (signal.aborted) {
        throw new Error("Compaction aborted");
      }

      // Recovery path: always split once when possible, then recurse if a half still fails.
      if (messages.length > 6 && depth < MAX_DEPTH) {
        const { left, right } = splitWithOverlap(messages);
        if (
          left.length > 0 &&
          right.length > 0 &&
          left.length < messages.length
        ) {
          const leftSummary = await summarizeChunked(left, prev, depth + 1);
          return summarizeChunked(right, leftSummary, depth + 1);
        }
      }

      const shot = await oneShot(messages, prev);
      if (shot.text && !shot.incomplete) {
        return shot.text;
      }

      if (messages.length > 6 && depth < MAX_DEPTH) {
        const { left, right } = splitWithOverlap(messages);
        if (
          left.length > 0 &&
          right.length > 0 &&
          left.length < messages.length
        ) {
          const leftSummary = await summarizeChunked(left, prev, depth + 1);
          return summarizeChunked(right, leftSummary, depth + 1);
        }
      }

      if (shot.text) {
        return shot.text;
      }
      throw new Error("Chunked summarization produced an empty summary");
    };

    try {
      const summary = await summarizeChunked(allMessages, previousSummary, 0);
      if (!summary.trim()) {
        throw new Error("empty summary");
      }
      return {
        compaction: {
          summary,
          firstKeptEntryId,
          tokensBefore,
          usage: usageAcc,
          details: {
            autonomous: true,
            chunked: true,
            recovery: true,
            passes,
            overlap: OVERLAP_MESSAGES,
            thinking: thinkingLevel || "off",
          },
        },
      };
    } catch (err) {
      // Surface a distinct error so the chat card can suggest lowering Thinking.
      const detail = err instanceof Error ? err.message : String(err);
      throw new Error(
        `Chunked compaction recovery failed (${detail}). ` +
          "Try lowering the thinking level (Réflexion) in bot details, then Relancer.",
      );
    }
  });
}
