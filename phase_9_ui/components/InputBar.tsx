"use client";

import { useRef, useEffect } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
}

const MAX_CHARS = 2000;

export function InputBar({ value, onChange, onSubmit, disabled }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  const remaining = MAX_CHARS - value.length;
  const isNearLimit = remaining < 100;
  const canSend = value.trim().length > 0 && !disabled && value.length <= MAX_CHARS;

  return (
    <div className="border-t border-border bg-surface-raised/80 backdrop-blur-md px-4 py-3">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-end gap-3 glass rounded-2xl px-4 py-3 transition-all duration-200 focus-within:border-accent-border focus-within:shadow-glow-sm">
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a factual question about a mutual fund scheme…"
            disabled={disabled}
            maxLength={MAX_CHARS}
            className="flex-1 bg-transparent resize-none text-sm text-ink-primary placeholder-ink-muted focus:outline-none disabled:opacity-40 leading-relaxed min-h-[24px]"
          />

          {/* Character counter + send */}
          <div className="flex items-center gap-2 flex-shrink-0 pb-0.5">
            {isNearLimit && (
              <span className={`text-xs tabular-nums ${remaining < 20 ? "text-danger" : "text-warn"}`}>
                {remaining}
              </span>
            )}
            <button
              onClick={onSubmit}
              disabled={!canSend}
              title="Send (Enter)"
              className="w-8 h-8 rounded-xl bg-accent-gradient flex items-center justify-center text-white shadow-glow-sm hover:shadow-glow disabled:opacity-30 disabled:shadow-none transition-all duration-150 active:scale-95"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>

        <p className="text-center text-xs text-ink-muted mt-2">
          Facts-only · No investment advice · Press{" "}
          <kbd className="px-1 py-0.5 rounded bg-surface-overlay border border-border text-ink-muted font-mono text-[10px]">Enter</kbd>{" "}
          to send
        </p>
      </div>
    </div>
  );
}
