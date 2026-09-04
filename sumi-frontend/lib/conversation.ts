import type { Block, Message, ServerEvent } from "./types";

/** Folds one backend event into the assistant message being streamed. */
export function applyEvent(message: Message, event: ServerEvent): Message {
  switch (event.type) {
    case "text":
      return { ...message, blocks: appendText(message.blocks, event.text) };
    case "tool_call":
      return {
        ...message,
        blocks: [
          ...message.blocks,
          { kind: "tool", name: event.name, arguments: event.arguments },
        ],
      };
    case "done":
      return { ...message, status: "done" };
    case "error":
      return { ...message, status: "error", error: event.message };
  }
}

function appendText(blocks: Block[], text: string): Block[] {
  const last = blocks[blocks.length - 1];
  if (last?.kind === "text") {
    return [...blocks.slice(0, -1), { kind: "text", text: last.text + text }];
  }
  return [...blocks, { kind: "text", text }];
}

const DETAIL_KEYS = ["query", "pattern", "filename", "path"];

/** A plain one-line account of a tool call, for the transcript. */
export function describeToolCall(
  name: string,
  args: Record<string, unknown>,
): string {
  const detail = pickDetail(args);
  switch (name) {
    case "search_notes":
      return detail ? `Searching notes for “${detail}”` : "Searching notes";
    case "grep":
      return detail ? `Looking for “${detail}” in notes` : "Looking through notes";
    case "read_file":
      return detail ? `Reading ${detail}` : "Reading a note";
    case "get_directory_listing":
      return detail && detail !== "."
        ? `Listing ${detail}`
        : "Listing the notes folder";
    default: {
      const verb = `Using ${name.replace(/_/g, " ")}`;
      return detail ? `${verb}: ${detail}` : verb;
    }
  }
}

function pickDetail(args: Record<string, unknown>): string | undefined {
  const isText = (value: unknown): value is string =>
    typeof value === "string" && value.length > 0;
  for (const key of DETAIL_KEYS) {
    if (isText(args[key])) return args[key];
  }
  return Object.values(args).find(isText);
}
