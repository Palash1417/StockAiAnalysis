"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, Message } from "@/lib/api";
import { Disclaimer } from "./Disclaimer";
import { EmptyState } from "./EmptyState";
import { Header } from "./Header";
import { InputBar } from "./InputBar";
import { MessageBubble } from "./MessageBubble";
import { TypingIndicator } from "./TypingIndicator";

interface Props {
  threadId: string | null;
  onMessageSent: () => void;
}

export function ChatWindow({ threadId, onMessageSent }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const firstUserMessage = messages.find((m) => m.role === "user")?.content;

  const scrollToBottom = () =>
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });

  useEffect(() => {
    if (!threadId) { setMessages([]); return; }
    api.getThread(threadId)
      .then((t) => setMessages(t.messages))
      .catch(() => setMessages([]));
  }, [threadId]);

  useEffect(() => { scrollToBottom(); }, [messages, loading]);

  const sendMessage = useCallback(
    async (query: string) => {
      if (!threadId || !query.trim() || loading) return;

      const userMsg: Message = {
        role: "user",
        content: query,
        ts: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setLoading(true);

      try {
        const resp = await api.chat(threadId, query);
        const assistantMsg: Message = {
          role: "assistant",
          content: resp.answer,
          ts: new Date().toISOString(),
          citation_url: resp.citation_url || undefined,
          last_updated: resp.last_updated || undefined,
          used_chunk_ids: resp.used_chunk_ids,
        };
        setMessages((prev) => [...prev, assistantMsg]);
        onMessageSent();
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: "Something went wrong. Please try again.",
            ts: new Date().toISOString(),
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [threadId, loading, onMessageSent]
  );

  const handleSubmit = () => sendMessage(input);

  /* ── No thread selected ── */
  if (!threadId) {
    return (
      <div className="flex flex-col h-full bg-surface-base">
        <Header />
        <Disclaimer />
        <div className="flex-1 flex items-center justify-center px-4">
          <div className="text-center space-y-2">
            <div className="w-12 h-12 rounded-2xl bg-surface-overlay flex items-center justify-center mx-auto mb-4">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#4a5568" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <p className="text-ink-secondary text-sm font-medium">Select a conversation</p>
            <p className="text-ink-muted text-xs">or start a new chat from the sidebar</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-surface-base">
      <Header title={firstUserMessage} />
      <Disclaimer />

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto chat-scroll px-4 py-6 max-w-3xl w-full mx-auto">
        {/* Glow decoration */}
        <div className="pointer-events-none fixed top-0 left-1/2 -translate-x-1/2 w-[600px] h-48 bg-glow-accent" />

        {messages.length === 0 && !loading && (
          <EmptyState onSelectExample={(q) => sendMessage(q)} />
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {loading && <TypingIndicator />}

        <div ref={bottomRef} />
      </div>

      <InputBar
        value={input}
        onChange={setInput}
        onSubmit={handleSubmit}
        disabled={loading}
      />
    </div>
  );
}
