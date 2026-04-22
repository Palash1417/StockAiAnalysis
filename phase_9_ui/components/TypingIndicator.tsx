export function TypingIndicator() {
  return (
    <div className="flex justify-start mb-4 animate-fade-in">
      {/* Avatar */}
      <div className="w-7 h-7 rounded-full bg-accent-gradient flex items-center justify-center mr-2 flex-shrink-0 mt-1 shadow-glow-sm">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M8 14s1.5 2 4 2 4-2 4-2" />
          <line x1="9" y1="9" x2="9.01" y2="9" />
          <line x1="15" y1="9" x2="15.01" y2="9" />
        </svg>
      </div>

      <div className="glass rounded-2xl rounded-tl-sm px-4 py-3 shadow-card">
        <div className="flex items-center gap-1.5">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-ink-secondary animate-pulse-dot"
              style={{ animationDelay: `${i * 0.18}s` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
