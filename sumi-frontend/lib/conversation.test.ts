import { expect, test } from "vitest";
import { applyEvent, describeToolCall } from "./conversation";
import type { Message } from "./types";

const reply: Message = { id: 2, role: "assistant", blocks: [], status: "streaming" };

test("text is appended to a trailing text block", () => {
  const after = [
    { type: "text", text: "ans" } as const,
    { type: "text", text: "wer" } as const,
  ].reduce(applyEvent, reply);
  expect(after.blocks).toEqual([{ kind: "text", text: "answer" }]);
  expect(after.status).toBe("streaming");
});

test("a tool call gets its own block and later text starts a new one", () => {
  const after = [
    { type: "text", text: "Let me look." } as const,
    { type: "tool_call", name: "search_notes", arguments: { query: "q" } } as const,
    { type: "text", text: "Found it." } as const,
    { type: "done" } as const,
  ].reduce(applyEvent, reply);
  expect(after).toEqual({
    ...reply,
    status: "done",
    blocks: [
      { kind: "text", text: "Let me look." },
      { kind: "tool", name: "search_notes", arguments: { query: "q" } },
      { kind: "text", text: "Found it." },
    ],
  });
});

test("an error event ends the message with its message", () => {
  expect(applyEvent(reply, { type: "error", message: "rate limited" })).toEqual({
    ...reply,
    status: "error",
    error: "rate limited",
  });
});

test.each([
  ["search_notes", { query: "deep work" }, "Searching notes for “deep work”"],
  ["search_notes", {}, "Searching notes"],
  ["grep", { pattern: "vision", path: "." }, "Looking for “vision” in notes"],
  ["read_file", { filename: "Areas/Deep Work.md" }, "Reading Areas/Deep Work.md"],
  ["get_directory_listing", { path: "." }, "Listing the notes folder"],
  ["get_directory_listing", { path: "Areas" }, "Listing Areas"],
  [
    "search_gmail_messages",
    { user_google_email: "me@example.com", query: "from:bank", page_size: 5 },
    "Using search gmail messages: from:bank",
  ],
  ["list_gmail_labels", { count: 3 }, "Using list gmail labels"],
])("describeToolCall(%s, %o)", (name, args, expected) => {
  expect(describeToolCall(name, args)).toBe(expected);
});
