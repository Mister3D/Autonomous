/**
 * Marker so one assistant response can run its tools one after another.
 *
 * Pi's default is parallel: every tool call in the same response starts together,
 * then the model is called once with all the results. A tool whose
 * executionMode is "sequential" forces that whole response to run one call
 * after another (still one model call after the batch). Including
 * batch_sequential is how the model chooses that order. Omitting it keeps
 * the parallel default.
 *
 * The marker is hidden in the chat (see agent._HIDDEN_TOOL_CARDS).
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
  pi.on("before_provider_request", (event) => {
    const payload = event.payload;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return;
    const body = payload as Record<string, unknown>;
    // OpenAI chat-completions shape (vLLM included). Anthropic uses a top-level
    // system field and rejects parallel_tool_calls.
    if (!Array.isArray(body.messages) || !Array.isArray(body.tools)) return;
    if (body.tools.length === 0) return;
    if ("system" in body || "anthropic_version" in body) return;
    if (body.parallel_tool_calls === true) return;
    return { ...body, parallel_tool_calls: true };
  });

  pi.registerTool({
    name: "batch_sequential",
    label: "Sequential batch",
    description:
      "Marker only. Include this once in the same response as other tool calls " +
      "when those calls must run one after another (they must not overlap) and " +
      "you already know every argument. They still finish before the next model " +
      "call; this does not let a later call read an earlier result. Omit this " +
      "tool when the calls are independent: they then start at the same time. " +
      "Never call this alone. Never use it for a step that needs a result you " +
      "do not have yet — send that one tool and wait.",
    executionMode: "sequential",
    parameters: Type.Object({
      note: Type.Optional(
        Type.String({
          description:
            "Optional one-line reason these calls must not overlap. Not shown to the user.",
        }),
      ),
    }),
    async execute() {
      return {
        content: [
          {
            type: "text" as const,
            text:
              "Sequential batch. The other tools in this response run one after another. " +
              "Their results arrive together on the next model call.",
          },
        ],
        details: { mode: "sequential" },
      };
    },
  });
}
