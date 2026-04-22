interface Props {
  url: string;
  lastUpdated?: string;
}

function schemeLabel(url: string): string {
  if (url.includes("nippon")) return "Nippon India Taiwan Equity Fund";
  if (url.includes("bandhan")) return "Bandhan Small Cap Fund";
  if (url.includes("hdfc"))    return "HDFC Mid Cap Fund";
  if (url.includes("amfi"))    return "AMFI Investor Education";
  return "Source";
}

export function CitationBadge({ url, lastUpdated }: Props) {
  const label = schemeLabel(url);

  return (
    <div className="mt-3 pt-3 border-t border-border-subtle flex flex-wrap items-center gap-2">
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent-muted border border-accent-border text-xs text-accent-light hover:bg-accent hover:text-white transition-all duration-150 group"
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-80">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
        {label}
      </a>

      {lastUpdated && (
        <span className="text-xs text-ink-muted">
          Last updated: {lastUpdated}
        </span>
      )}
    </div>
  );
}
