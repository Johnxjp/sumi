"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL, resetConversation, streamReply } from "@/lib/api";
import { applyEvent } from "@/lib/conversation";
import type { Message } from "@/lib/types";
import { Composer } from "./Composer";
import { Transcript } from "./Transcript";

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const followBottom = useRef(true);

  useEffect(() => {
    const root = document.documentElement;
    const onScroll = () => {
      followBottom.current =
        window.innerHeight + window.scrollY >= root.scrollHeight - 80;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (followBottom.current) {
      window.scrollTo({ top: document.documentElement.scrollHeight });
    }
  }, [messages]);

  function updateReply(update: (reply: Message) => Message) {
    setMessages((previous) => [
      ...previous.slice(0, -1),
      update(previous[previous.length - 1]),
    ]);
  }

  async function send(text: string) {
    const question: Message = {
      id: nextId.current++,
      role: "user",
      blocks: [{ kind: "text", text }],
      status: "done",
    };
    const reply: Message = {
      id: nextId.current++,
      role: "assistant",
      blocks: [],
      status: "streaming",
    };
    followBottom.current = true;
    setMessages((previous) => [...previous, question, reply]);
    setBusy(true);
    try {
      await streamReply(text, (event) =>
        updateReply((current) => applyEvent(current, event)),
      );
      updateReply((current) =>
        current.status === "streaming"
          ? {
              ...current,
              status: "error",
              error: "The connection closed before the reply finished.",
            }
          : current,
      );
    } catch (error) {
      updateReply((current) => ({
        ...current,
        status: "error",
        error: describeFailure(error),
      }));
    } finally {
      setBusy(false);
    }
  }

  async function startNewChat() {
    setMessages([]);
    try {
      await resetConversation();
    } catch {
      // The backend is unreachable; the next message will report it.
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="topbar-inner">
          <span className="wordmark">sumi</span>
          <button
            type="button"
            className="newchat"
            onClick={startNewChat}
            disabled={busy || messages.length === 0}
          >
            New chat
          </button>
        </div>
      </header>
      <main className="transcript-area">
        {messages.length === 0 ? (
          <p className="empty">Ask a question about your notes.</p>
        ) : (
          <Transcript messages={messages} />
        )}
      </main>
      <footer className="dock">
        <Composer onSend={send} canSend={!busy} />
      </footer>
    </div>
  );
}

function describeFailure(error: unknown): string {
  if (error instanceof TypeError) {
    return `Couldn't reach the backend at ${API_URL}. Start it and try again.`;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}
