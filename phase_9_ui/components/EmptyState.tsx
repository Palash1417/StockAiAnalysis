interface Props {
  onSelectExample: (query: string) => void;
}

const EXAMPLES = [
  {
    icon: "💹",
    label: "Expense Ratio",
    query: "What is the expense ratio of HDFC Mid Cap Fund Direct - Growth?",
  },
  {
    icon: "🚪",
    label: "Exit Load",
    query: "What is the exit load for Bandhan Small Cap Fund Direct - Growth?",
  },
  {
    icon: "📊",
    label: "Benchmark",
    query: "What is the benchmark for Nippon India Taiwan Equity Fund Direct - Growth?",
  },
];

export function EmptyState({ onSelectExample }: Props) {
  return (
    <div className="flex flex-col items-center justify-center h-full px-6 py-12 animate-fade-in">
      {/* Glow orb */}
      <div className="relative mb-8">
        <div className="absolute inset-0 rounded-full bg-accent opacity-20 blur-2xl scale-150" />
        <div className="relative w-16 h-16 rounded-2xl bg-accent-gradient flex items-center justify-center shadow-glow">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </div>
      </div>

      <h2 className="text-xl font-semibold text-ink-primary mb-2 text-center">
        Ask me about mutual funds
      </h2>
      <p className="text-sm text-ink-secondary text-center max-w-sm mb-8 leading-relaxed">
        Get factual answers about expense ratios, exit loads, minimum SIP, benchmarks, and more from official sources.
      </p>

      {/* Example chips */}
      <div className="w-full max-w-lg space-y-2.5">
        <p className="text-xs text-ink-muted uppercase tracking-widest text-center mb-4">
          Try an example
        </p>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.query}
            onClick={() => onSelectExample(ex.query)}
            className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl glass hover:bg-surface-hover border-gradient transition-all duration-200 hover:shadow-card group text-left"
          >
            <span className="text-xl flex-shrink-0">{ex.icon}</span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-accent-light mb-0.5">{ex.label}</p>
              <p className="text-sm text-ink-secondary truncate group-hover:text-ink-primary transition-colors">
                {ex.query}
              </p>
            </div>
            <svg className="ml-auto flex-shrink-0 text-ink-muted group-hover:text-accent-light transition-colors" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  );
}
