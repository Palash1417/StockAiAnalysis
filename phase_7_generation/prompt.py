"""Prompt construction for Phase 7 generation — §7.1."""
from __future__ import annotations

from phase_6_retrieval.models import CandidateChunk

from .models import GenerationRequest

# ---------------------------------------------------------------------------
# System prompt (§7.1 contract)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are a facts-only Mutual Fund FAQ assistant. You answer questions strictly \
from the provided context chunks — nothing else.

Rules you MUST follow:
1. Answer in at most 3 sentences. No more.
2. Cite exactly ONE source URL — the source_url of the single most relevant chunk.
3. End your answer with this footer on its own line:
   Last updated from sources: <YYYY-MM-DD>
   (use the last_updated date of the chunk you cited)
4. If the context does not contain enough information to answer the question,
   return ONLY this JSON and nothing else:
   {"sentinel": "INSUFFICIENT_CONTEXT"}
5. Never offer investment advice, recommendations, performance comparisons,
   return calculations, or opinions on which fund is better.
6. Do not invent facts. If a number is not in the context, say so or use §4.

Output format — return valid JSON only, no markdown fences:
{
  "answer": "<your factual answer, max 3 sentences, ending with the Last updated footer>",
  "citation_url": "<source_url of the most relevant chunk>",
  "last_updated": "<YYYY-MM-DD from that chunk>",
  "confidence": <float 0.0–1.0 reflecting how well the context supports your answer>,
  "used_chunk_ids": ["<chunk_id_1>", "<chunk_id_2>"]
}
"""

# ---------------------------------------------------------------------------
# Context formatter
# ---------------------------------------------------------------------------

def format_context(candidates: list[CandidateChunk]) -> str:
    """Render retrieval candidates into the <context> block sent to the LLM."""
    if not candidates:
        return "<context>\n(no chunks retrieved)\n</context>"

    parts = ["<context>"]
    for i, c in enumerate(candidates, 1):
        parts.append(
            f"\n[{i}] chunk_id={c.chunk_id}"
            f" | type={c.segment_type}"
            f" | scheme={c.scheme or 'unknown'}"
            f" | score={c.score:.3f}"
            f" | source_url={c.source_url}"
            f" | last_updated={c.last_updated}"
        )
        parts.append(c.text)
    parts.append("</context>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Full message list builder
# ---------------------------------------------------------------------------

def build_messages(request: GenerationRequest) -> list[dict[str, str]]:
    """Return the complete messages list for the Groq chat completion call.

    Structure:
      [system]
      [assistant/user history — last 4 turns, max 8 messages]
      [user: query + context]
    """
    context_block = format_context(request.candidates)
    user_content = (
        f"Question: {request.query}\n\n"
        f"{context_block}\n\n"
        "Answer using only the context above. Return valid JSON."
    )

    # last 4 turns = 8 messages (user + assistant pairs)
    history = (request.thread_history or [])[-8:]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_content},
    ]
