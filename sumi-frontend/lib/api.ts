import { parseSse } from "./sse";
import type { ServerEvent } from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8766";

/** Sends one message and calls `onEvent` for each event the backend streams back. */
export async function streamReply(
  message: string,
  onEvent: (event: ServerEvent) => void,
): Promise<void> {
  const response = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok || response.body === null) {
    throw new Error(`The backend answered with status ${response.status}.`);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const { payloads, rest } = parseSse(buffer);
    buffer = rest;
    for (const payload of payloads) onEvent(JSON.parse(payload) as ServerEvent);
  }
}

export async function resetConversation(): Promise<void> {
  const response = await fetch(`${API_URL}/api/reset`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`The backend answered with status ${response.status}.`);
  }
}
