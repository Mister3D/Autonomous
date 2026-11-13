import assert from "node:assert/strict";
import test from "node:test";

import { capVisionMessages } from "../autonomous/pi_extensions/vision_budget.ts";

function image(id: string) {
  return { type: "image", data: id, mimeType: "image/png" };
}

test("keeps the newest images and leaves a short note on the older ones", () => {
  const messages = [
    { role: "user", content: [{ type: "text", text: "look" }, image("a"), image("b")] },
    {
      role: "toolResult",
      content: [image("c"), { type: "text", text: "shot" }, image("d")],
    },
    { role: "assistant", content: [{ type: "text", text: "ok" }] },
  ];
  const next = capVisionMessages(messages, 2);
  assert.notEqual(next, messages);
  assert.deepEqual(next[0].content, [
    { type: "text", text: "look" },
    {
      type: "text",
      text: "(earlier image omitted: this model accepts only a few images per request; the picture is still in the chat)",
    },
  ]);
  assert.equal(next[1].content[0].type, "image");
  assert.equal(next[1].content[0].data, "c");
  assert.equal(next[1].content[2].data, "d");
  assert.equal(next[2], messages[2]);
});

test("does not copy the transcript when it already fits", () => {
  const messages = [{ role: "toolResult", content: [image("only")] }];
  assert.equal(capVisionMessages(messages, 2), messages);
});
