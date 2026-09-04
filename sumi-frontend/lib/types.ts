/** One event from the backend's server-sent-event stream. */
export type ServerEvent =
  | { type: "text"; text: string }
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "done" }
  | { type: "error"; message: string };

/** A message is rendered as blocks in the order the agent produced them. */
export type Block =
  | { kind: "text"; text: string }
  | { kind: "tool"; name: string; arguments: Record<string, unknown> };

export type Message = {
  id: number;
  role: "user" | "assistant";
  blocks: Block[];
  status: "streaming" | "done" | "error";
  error?: string;
};
