import { Message } from "@/lib/api";
import { CitationBadge } from "./CitationBadge";

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end mb-4 animate-slide-up">
        <div className="max-w-[72%] px-4 py-3 rounded-2xl rounded-tr-sm bg-accent-gradient text-white text-sm leading-relaxed shadow-glow-sm">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start mb-4 animate-slide-up">
      {/* Avatar */}
      <div className="w-7 h-7 rounded-full bg-accent-gradient flex items-center justify-center mr-3 flex-shrink-0 mt-1 shadow-glow-sm">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M8 14s1.5 2 4 2 4-2 4-2" />
          <line x1="9" y1="9" x2="9.01" y2="9" />
          <line x1="15" y1="9" x2="15.01" y2="9" />
        </svg>
      </div>

      <div className="max-w-[75%]">
        <div className="glass rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed text-ink-primary shadow-card">
          <p className="whitespace-pre-wrap">{message.content}</p>

          {message.citation_url && (
            <CitationBadge
              url={message.citation_url}
              lastUpdated={message.last_updated}
            />
          )}
        </div>
      </div>
    </div>
  );
}
