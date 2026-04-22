"""RAG pipeline orchestrator — §16 request lifecycle.

Steps (per §16):
  1.  Input guard (PII + injection + intent)
  2.  Query rewrite using last 4 thread turns
  3.  Hybrid retrieve  →  RRF  →  rerank  →  top-5
  4.  If below threshold → INSUFFICIENT_CONTEXT
  5.  Generate (Groq JSON mode)
  6.  Output guard (advice + length + citation + groundedness)
  7.  Return ChatResponse

build_pipeline(config) wires all components from previous phases.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .models import ChatResponse

log = logging.getLogger(__name__)

_AMFI_URL = "https://www.amfiindia.com/investor-corner"


def _refusal_chat_response(thread_id: str, message: str) -> ChatResponse:
    return ChatResponse(
        thread_id=thread_id,
        answer=message,
        citation_url=_AMFI_URL,
        last_updated="",
        confidence=0.0,
        used_chunk_ids=[],
        sentinel="REFUSAL",
        refusal=True,
    )


def _insufficient_chat_response(thread_id: str) -> ChatResponse:
    return ChatResponse(
        thread_id=thread_id,
        answer=(
            "I couldn't find this information in the mutual fund sources I have access to. "
            "For general guidance please visit AMFI's investor education page."
        ),
        citation_url=_AMFI_URL,
        last_updated="",
        confidence=0.0,
        used_chunk_ids=[],
        sentinel="INSUFFICIENT_CONTEXT",
    )


class RAGPipeline:
    """Thin orchestrator that sequences guardrails → retrieve → generate → guard.

    All heavy dependencies (retriever, generator, guardrails) are injected so
    the pipeline is easily testable with mocks.
    """

    def __init__(self, guardrails: Any, retriever: Any, generator: Any):
        self._guardrails = guardrails
        self._retriever = retriever
        self._generator = generator

    async def run(
        self,
        thread_id: str,
        query: str,
        thread_history: list[dict[str, str]],
    ) -> ChatResponse:
        loop = asyncio.get_running_loop()

        # 1. Input guard
        try:
            input_result = await asyncio.wait_for(
                loop.run_in_executor(None, self._guardrails.check_input, query),
                timeout=5.0,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning("input guard failed: %s — passing through", exc)
            from phase_8_guardrails.models import InputGuardResult
            input_result = InputGuardResult(passed=True)
        if not input_result.passed:
            return _refusal_chat_response(thread_id, input_result.refusal_response or "")

        # 2 + 3. Retrieve (query rewrite happens inside HybridRetriever)
        try:
            retrieval = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._retriever.retrieve(
                        query, thread_history=thread_history
                    ),
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            log.error("retrieval timed out after 30s — embedder may still be loading")
            return _insufficient_chat_response(thread_id)
        except Exception as exc:
            log.error("retrieval failed: %s", exc)
            return _insufficient_chat_response(thread_id)

        # 4. Below-threshold path
        if retrieval.below_threshold or not retrieval.candidates:
            return _insufficient_chat_response(thread_id)

        # 5. Generate
        try:
            from phase_7_generation.models import GenerationRequest

            gen_request = GenerationRequest(
                query=query,
                candidates=retrieval.candidates,
                below_threshold=retrieval.below_threshold,
                thread_history=thread_history,
            )
            gen_response = await loop.run_in_executor(
                None, self._generator.generate, gen_request
            )
        except Exception as exc:
            log.error("generation failed: %s", exc)
            return _insufficient_chat_response(thread_id)

        if gen_response.sentinel == "INSUFFICIENT_CONTEXT":
            return _insufficient_chat_response(thread_id)

        # 6. Output guard
        try:
            output_result = await loop.run_in_executor(
                None,
                lambda: self._guardrails.check_output(
                    query, gen_response, retrieval.candidates
                ),
            )
        except Exception as exc:
            log.warning("output guard failed: %s — passing through", exc)
            output_result = None

        if output_result is not None and not output_result.passed:
            return _insufficient_chat_response(thread_id)

        final_answer = (
            (output_result.sanitized_answer if output_result else None)
            or gen_response.answer
        )

        return ChatResponse(
            thread_id=thread_id,
            answer=final_answer,
            citation_url=gen_response.citation_url,
            last_updated=gen_response.last_updated,
            confidence=gen_response.confidence,
            used_chunk_ids=gen_response.used_chunk_ids,
            sentinel=gen_response.sentinel,
            refusal=False,
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _warmup_embedder(embedder: Any) -> None:
    """Pre-load the embedding model in the startup (main) thread.

    On Windows, importing torch for the first time inside a thread-pool thread
    can hang indefinitely.  Calling embed_batch here — synchronously during
    app startup — ensures the DLLs are loaded before the first request arrives.
    A timeout guards against hanging at startup; if it fires we log a warning
    and continue (the 30-second retrieval timeout in pipeline.run will still
    protect individual requests).
    """
    import threading, signal

    result: list[Any] = []
    exc_holder: list[Exception] = []

    def _run() -> None:
        try:
            embedder.embed_batch(["warmup"])
            result.append(True)
        except Exception as e:
            exc_holder.append(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=60)
    if t.is_alive():
        log.warning(
            "embedder warmup timed out after 60 s — torch may be misconfigured. "
            "Try reinstalling PyTorch CPU-only: "
            "pip install torch --index-url https://download.pytorch.org/whl/cpu"
        )
    elif exc_holder:
        log.warning("embedder warmup raised %s — will retry on first request", exc_holder[0])
    else:
        log.info("embedder warmup complete")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_pipeline(config: dict[str, Any]) -> RAGPipeline:
    """Build a RAGPipeline from config.

    Retriever backend: ``in_memory`` (default) | ``chroma`` | ``pgvector``.
    Generation always requires ``GROQ_API_KEY`` in env.
    Guardrails use rule-based classifiers by default (no LLM needed).
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    # --- Guardrails ---
    from phase_8_guardrails.guardrails import build_guardrails
    guardrails = build_guardrails(config.get("guardrails", {}))

    # --- Embedder ---
    embed_cfg = config.get("embedder", {"provider": "fake"})
    from phase_4_1_chunk_embed_index.ingestion_pipeline.embedder.embedder import (
        build_embedder,
    )
    embedder = build_embedder(embed_cfg)

    # Warm up the embedder in the main thread so torch/sentence-transformers
    # DLLs are loaded before the first request hits a worker thread.
    # On Windows, torch can hang when imported for the first time inside a
    # thread-pool thread — loading it here (startup, main thread) avoids that.
    _warmup_embedder(embedder)

    # --- Retriever ---
    retriever_cfg = config.get("retriever", {})
    backend = retriever_cfg.get("backend", "in_memory")

    score_threshold = retriever_cfg.get("score_threshold", 0.01)

    if backend == "chroma":
        retriever = _build_chroma_retriever(config, embedder, score_threshold)
    else:
        retriever = _build_in_memory_retriever(config, embedder, score_threshold)

    # --- Generator ---
    from phase_7_generation.generator import build_generator
    generator = build_generator(config.get("generation", {}))

    return RAGPipeline(guardrails=guardrails, retriever=retriever, generator=generator)


def _build_in_memory_retriever(config: dict, embedder: Any, score_threshold: float = 0.01) -> Any:
    from phase_6_retrieval.adapters.in_memory_retriever import (
        InMemoryBM25Retriever,
        InMemoryDenseRetriever,
    )
    from phase_6_retrieval.reranker import build_reranker
    from phase_6_retrieval.query_rewrite import build_query_rewriter
    from phase_6_retrieval.retriever import HybridRetriever

    dense = InMemoryDenseRetriever()
    sparse = InMemoryBM25Retriever()
    reranker = build_reranker(config.get("reranker", {"type": "passthrough"}))
    rewriter = build_query_rewriter(config.get("query_rewrite", {"use_llm": False}))

    class _FakePointer:
        def get_live(self):
            return "live"

    return HybridRetriever(
        embedder=embedder,
        dense=dense,
        sparse=sparse,
        reranker=reranker,
        corpus_pointer=_FakePointer(),
        query_rewriter=rewriter,
        score_threshold=score_threshold,
    )


def _build_chroma_retriever(config: dict, embedder: Any, score_threshold: float = 0.01) -> Any:
    """Build a retriever backed by Chroma Cloud + in-memory BM25."""
    import os
    from phase_5_ingestion_cli.adapters.chroma_vector_index import ChromaVectorIndex
    from phase_6_retrieval.adapters.in_memory_retriever import InMemoryBM25Retriever
    from phase_6_retrieval.reranker import build_reranker
    from phase_6_retrieval.query_rewrite import build_query_rewriter
    from phase_6_retrieval.retriever import HybridRetriever

    chroma_cfg = config.get("chroma", {})
    chroma_index = ChromaVectorIndex(
        api_key=os.environ.get("CHROMA_API_KEY", chroma_cfg.get("api_key", "")),
        tenant=os.environ.get("CHROMA_TENANT", chroma_cfg.get("tenant", "")),
        database=os.environ.get("CHROMA_DATABASE", chroma_cfg.get("database", "default")),
        collection_name=chroma_cfg.get("collection", "mf_rag"),
    )

    class _ChromaDenseRetriever:
        def __init__(self, index: ChromaVectorIndex, emb: Any):
            self._index = index
            self._embedder = emb

        def search(self, query_vec, corpus_version, top_k, scheme_filter=None):
            return self._index.query(
                query_vec, top_k=top_k, corpus_version=corpus_version,
                scheme_filter=scheme_filter,
            )

    dense = _ChromaDenseRetriever(chroma_index, embedder)
    sparse = InMemoryBM25Retriever()
    reranker = build_reranker(config.get("reranker", {"type": "passthrough"}))
    rewriter = build_query_rewriter(config.get("query_rewrite", {"use_llm": False}))

    class _ChromaPointer:
        def get_live(self):
            return ""   # Chroma index ignores corpus_version filter

    return HybridRetriever(
        embedder=embedder,
        dense=dense,
        sparse=sparse,
        reranker=reranker,
        corpus_pointer=_ChromaPointer(),
        query_rewriter=rewriter,
        score_threshold=score_threshold,
    )
