// Kept for backward compat — ChatWindow now uses EmptyState instead.
// This lightweight variant can be used inline if needed.

const EXAMPLES = [
  "What is the expense ratio of HDFC Mid Cap Fund Direct - Growth?",
  "What is the exit load for Bandhan Small Cap Fund Direct - Growth?",
  "What is the benchmark for Nippon India Taiwan Equity Fund Direct - Growth?",
];

interface Props {
  onSelect: (query: string) => void;
}

export function ExampleChips({ onSelect }: Props) {
  return (
    <div className="flex flex-wrap gap-2 justify-center py-4 px-2">
      {EXAMPLES.map((q) => (
        <button
          key={q}
          onClick={() => onSelect(q)}
          className="px-3 py-1.5 rounded-full glass border-gradient text-xs text-ink-secondary hover:text-ink-primary hover:shadow-card transition-all duration-150"
        >
          {q.length > 48 ? q.slice(0, 48) + "…" : q}
        </button>
      ))}
    </div>
  );
}
