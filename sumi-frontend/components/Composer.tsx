"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

export function Composer({
  onSend,
  canSend,
}: {
  onSend: (text: string) => void;
  canSend: boolean;
}) {
  const [text, setText] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);
  const ready = canSend && text.trim().length > 0;

  useEffect(() => {
    textarea.current?.focus();
  }, []);

  useLayoutEffect(() => {
    const element = textarea.current;
    if (element) {
      element.style.height = "auto";
      element.style.height = `${element.scrollHeight}px`;
    }
  }, [text]);

  function submit() {
    if (!ready) return;
    onSend(text.trim());
    setText("");
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer" onSubmit={onSubmit}>
      <textarea
        ref={textarea}
        rows={1}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask your notes"
        aria-label="Your question"
      />
      <button type="submit" className="seal" disabled={!ready} aria-label="Send">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path
            d="M7 12V2M7 2L2.5 6.5M7 2l4.5 4.5"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </form>
  );
}
