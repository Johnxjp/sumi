/**
 * Splits decoded server-sent-event text into the `data` payload of every
 * complete event (events end with a blank line), keeping the unfinished tail
 * so it can be joined with the next chunk from the network.
 */
export function parseSse(buffer: string): { payloads: string[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const payloads: string[] = [];
  for (const frame of frames) {
    const data = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice("data:".length).replace(/^ /, ""));
    if (data.length > 0) payloads.push(data.join("\n"));
  }
  return { payloads, rest };
}
