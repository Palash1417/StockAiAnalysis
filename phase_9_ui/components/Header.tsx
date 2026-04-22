interface Props {
  title?: string;
}

export function Header({ title }: Props) {
  return (
    <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-surface-raised/80 backdrop-blur-md">
      <div className="flex items-center gap-3 min-w-0">
        {/* Bot icon */}
        <div className="w-7 h-7 rounded-lg bg-accent-gradient flex items-center justify-center flex-shrink-0 shadow-glow-sm">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <path d="M8 14s1.5 2 4 2 4-2 4-2" />
            <line x1="9" y1="9" x2="9.01" y2="9" />
            <line x1="15" y1="9" x2="15.01" y2="9" />
          </svg>
        </div>
        <div className="min-w-0">
          <h1 className="text-sm font-semibold text-ink-primary truncate">
            {title ?? "New conversation"}
          </h1>
          <p className="text-xs text-ink-muted">Mutual Fund FAQ Assistant</p>
        </div>
      </div>

      {/* Status badge */}
      <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-surface-overlay border border-border text-xs text-ink-secondary">
        <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
        Live data
      </div>
    </header>
  );
}
