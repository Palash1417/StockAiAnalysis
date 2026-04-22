"use client";

import { ThreadSummary } from "@/lib/api";

interface Props {
  threads: ThreadSummary[];
  activeThreadId: string | null;
  onSelectThread: (id: string) => void;
  onNewChat: () => void;
  onDeleteThread: (id: string) => void;
}

function timeLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffH = diffMs / (1000 * 60 * 60);
  if (diffH < 1) return "Just now";
  if (diffH < 24) return `${Math.floor(diffH)}h ago`;
  return d.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
}

export function ThreadSidebar({
  threads,
  activeThreadId,
  onSelectThread,
  onNewChat,
  onDeleteThread,
}: Props) {
  return (
    <aside className="w-64 flex-shrink-0 flex flex-col h-full bg-surface-raised border-r border-border">
      {/* Brand */}
      <div className="px-4 pt-5 pb-4">
        <div className="flex items-center gap-2.5 mb-5">
          <div className="w-8 h-8 rounded-xl bg-accent-gradient flex items-center justify-center shadow-glow-sm flex-shrink-0">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-ink-primary leading-tight">MF FAQ</p>
            <p className="text-[10px] text-ink-muted leading-tight">Mutual Fund Assistant</p>
          </div>
        </div>

        {/* New chat */}
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl bg-accent-gradient text-white text-sm font-medium shadow-glow-sm hover:shadow-glow transition-shadow duration-200 active:scale-[0.98]"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New conversation
        </button>
      </div>

      {/* Thread list */}
      <div className="px-2 mb-1">
        <p className="px-2 text-[10px] font-medium text-ink-muted uppercase tracking-widest">
          Recent
        </p>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 space-y-0.5 pb-2">
        {threads.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 gap-2">
            <div className="w-10 h-10 rounded-xl bg-surface-overlay flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#4a5568" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <p className="text-xs text-ink-muted text-center">No conversations yet</p>
          </div>
        )}

        {threads.map((t) => {
          const isActive = activeThreadId === t.thread_id;
          return (
            <div key={t.thread_id} className="group relative flex items-center">
              <button
                onClick={() => onSelectThread(t.thread_id)}
                className={`flex-1 text-left rounded-xl px-3 py-2.5 transition-all duration-150 min-w-0 ${
                  isActive
                    ? "bg-accent-muted border border-accent-border text-ink-primary"
                    : "text-ink-secondary hover:bg-surface-overlay hover:text-ink-primary"
                }`}
              >
                <p className="text-xs font-medium truncate leading-snug">
                  {t.preview ?? "New conversation"}
                </p>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[10px] text-ink-muted">{timeLabel(t.created_at)}</span>
                  {t.message_count > 0 && (
                    <>
                      <span className="text-ink-faint">·</span>
                      <span className="text-[10px] text-ink-muted">
                        {Math.floor(t.message_count / 2)} msg
                        {t.message_count > 2 ? "s" : ""}
                      </span>
                    </>
                  )}
                </div>
              </button>

              {/* Delete button — visible on hover */}
              <button
                onClick={(e) => { e.stopPropagation(); onDeleteThread(t.thread_id); }}
                title="Delete"
                className="absolute right-2 hidden group-hover:flex w-6 h-6 items-center justify-center rounded-lg text-ink-muted hover:text-danger hover:bg-surface-float transition-colors duration-150"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                  <path d="M10 11v6M14 11v6" />
                </svg>
              </button>
            </div>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-border px-4 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-full bg-surface-overlay flex items-center justify-center">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2.5">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <span className="text-[10px] text-ink-muted">3 schemes · Groww source</span>
        </div>
        <p className="text-[10px] text-ink-muted leading-relaxed">
          Data refreshes daily at 09:15 IST
        </p>
      </div>
    </aside>
  );
}
