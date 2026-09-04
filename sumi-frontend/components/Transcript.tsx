import { describeToolCall } from "@/lib/conversation";
import type { Message } from "@/lib/types";

export function Transcript({ messages }: { messages: Message[] }) {
  return (
    <ol className="transcript">
      {messages.map((message) =>
        message.role === "user" ? (
          <li key={message.id} className="question">
            {message.blocks[0]?.kind === "text" ? message.blocks[0].text : ""}
          </li>
        ) : (
          <li key={message.id} className="reply" data-status={message.status}>
            <Reply message={message} />
          </li>
        ),
      )}
    </ol>
  );
}

function Reply({ message }: { message: Message }) {
  const lastBlock = message.blocks[message.blocks.length - 1];
  const thinking = message.status === "streaming" && lastBlock?.kind !== "text";
  return (
    <>
      {message.blocks.map((block, index) =>
        block.kind === "tool" ? (
          <p key={index} className="tool">
            {describeToolCall(block.name, block.arguments)}
          </p>
        ) : (
          <p key={index} className="text">
            {block.text}
          </p>
        ),
      )}
      {thinking && <span className="thinking" role="status" aria-label="Thinking" />}
      {message.status === "error" && <p className="error">{message.error}</p>}
    </>
  );
}
