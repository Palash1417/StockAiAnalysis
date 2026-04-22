"""Phase 7 — Generator: §7.1 prompt contract + §7.2 model + §7.3 output schema.

Entry points:
  Generator.generate(request) -> GenerationResponse
  build_generator(config)     -> Generator

The Generator calls Groq in JSON mode, parses the structured response,
and falls back to INSUFFICIENT_CONTEXT on any failure so the caller always
gets a well-formed GenerationResponse.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from phase_6_retrieval.models import CandidateChunk

from .models import GenerationRequest, GenerationResponse, insufficient_context_response
from .prompt import build_messages

log = logging.getLogger(__name__)

_KNOWN_SOURCE_URLS = {
    "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth",
    "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
}


class Generator:
    """Calls Groq to produce a structured GenerationResponse.

    Parameters
    ----------
    client:
        A ``groq.Groq()`` instance (or any object with a
        ``chat.completions.create`` method matching the Groq SDK).
    model:
        Groq model identifier (default: ``llama-3.3-70b-versatile``).
    temperature:
        0.0–0.2 for factual consistency (§7.2).
    max_tokens:
        Upper bound on LLM output tokens; 512 is ample for ≤3 sentences + JSON.
    """

    def __init__(
        self,
        client: Any,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.1,
        max_tokens: int = 512,
    ):
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Return a GenerationResponse.  Never raises — falls back on any error."""
        if not request.candidates or request.below_threshold:
            log.info(
                "generate: no usable candidates (below_threshold=%s, n=%d) — INSUFFICIENT_CONTEXT",
                request.below_threshold,
                len(request.candidates),
            )
            return insufficient_context_response()

        messages = build_messages(request)
        try:
            raw = self._call_llm(messages)
        except Exception as exc:
            log.warning("LLM call failed: %s — INSUFFICIENT_CONTEXT", exc)
            return insufficient_context_response()

        try:
            return _parse_response(raw, request.candidates)
        except Exception as exc:
            log.warning("response parse failed: %s — INSUFFICIENT_CONTEXT", exc)
            return insufficient_context_response()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_llm(self, messages: list[dict[str, str]]) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(
    raw: str,
    candidates: list[CandidateChunk],
) -> GenerationResponse:
    """Parse the LLM's JSON output into a GenerationResponse.

    Validates:
    - sentinel path → returns insufficient_context_response()
    - citation_url must be in the known source registry; falls back to top chunk
    - last_updated derived from the cited chunk if missing
    - confidence clamped to [0.0, 1.0]
    """
    data: dict[str, Any] = json.loads(raw)

    # LLM chose to signal insufficient context
    if data.get("sentinel") == "INSUFFICIENT_CONTEXT":
        return insufficient_context_response()

    answer: str = str(data.get("answer", "")).strip()
    if not answer:
        raise ValueError("empty answer in LLM response")

    # --- citation URL ---------------------------------------------------
    citation_url: str = str(data.get("citation_url", "")).strip()
    if citation_url not in _KNOWN_SOURCE_URLS:
        # Fall back to the source_url of the top-ranked candidate
        citation_url = candidates[0].source_url if candidates else ""

    # --- last_updated from the cited chunk ------------------------------
    last_updated: str = str(data.get("last_updated", "")).strip()
    if not last_updated:
        last_updated = _last_updated_for_url(citation_url, candidates)

    # --- confidence -----------------------------------------------------
    try:
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    # --- used_chunk_ids -------------------------------------------------
    raw_ids = data.get("used_chunk_ids", [])
    used_chunk_ids: list[str] = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []

    return GenerationResponse(
        answer=answer,
        citation_url=citation_url,
        last_updated=last_updated,
        confidence=confidence,
        used_chunk_ids=used_chunk_ids,
    )


def _last_updated_for_url(url: str, candidates: list[CandidateChunk]) -> str:
    for c in candidates:
        if c.source_url == url:
            return c.last_updated
    return candidates[0].last_updated if candidates else ""


# ---------------------------------------------------------------------------
# Anthropic httpx client (no SDK needed)
# ---------------------------------------------------------------------------

class _AnthropicClient:
    """Minimal Anthropic Messages API client using httpx.

    Exposes the same ``chat.completions.create`` shape the Generator uses,
    so it can be swapped in without changing Generator._call_llm.
    """

    def __init__(self, api_key: str, timeout: float = 30.0):
        import httpx  # already in requirements
        self._api_key = api_key
        self._timeout = timeout
        self._http = httpx.Client(timeout=timeout)

    class _Choice:
        def __init__(self, content: str):
            self.message = type("M", (), {"content": content})()

    class _Resp:
        def __init__(self, content: str):
            self.choices = [_AnthropicClient._Choice(content)]

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, *, model: str, messages: list, temperature: float,
               max_tokens: int, response_format: dict | None = None, **_):
        # Map Groq/OpenAI model names → Claude model
        claude_model = _map_to_claude(model)
        # Strip system message into system param
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        user_msgs = [m for m in messages if m["role"] != "system"]
        payload: dict[str, Any] = {
            "model": claude_model,
            "max_tokens": max_tokens,
            "messages": user_msgs,
        }
        if system:
            payload["system"] = system
        if response_format and response_format.get("type") == "json_object":
            payload["system"] = (payload.get("system", "") +
                                 "\nRespond ONLY with valid JSON. No markdown fences.").strip()
        resp = self._http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        content = resp.json()["content"][0]["text"]
        return _AnthropicClient._Resp(content)


def _map_to_claude(model: str) -> str:
    """Map Groq model names to the equivalent Claude model."""
    if "claude" in model.lower():
        return model
    # Default to Haiku for speed/cost; override via api.yaml generation.model
    return "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_generator(config: dict[str, Any]) -> Generator:
    """Instantiate a Generator from a config dict.

    Provider selection (in order):
      1. ``ANTHROPIC_API_KEY`` in env  → _AnthropicClient (httpx, no SDK)
      2. ``GROQ_API_KEY`` in env       → groq.Groq SDK
    """
    gen_cfg = config.get("generation", config)   # tolerate flat or nested
    model = gen_cfg.get("model", "llama-3.3-70b-versatile")
    temperature = float(gen_cfg.get("temperature", 0.1))
    max_tokens = int(gen_cfg.get("max_tokens", 512))

    groq_key = os.environ.get("GROQ_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if groq_key:
        log.info("Generator: using Groq SDK model=%s", model)
        try:
            import groq  # type: ignore
            client = groq.Groq(api_key=groq_key, timeout=30.0)
        except Exception as exc:
            log.warning("groq import failed (%s) — client is None", exc)
            client = None  # type: ignore
    elif anthropic_key:
        log.info("Generator: using Anthropic API (httpx) model=%s", _map_to_claude(model))
        client = _AnthropicClient(api_key=anthropic_key, timeout=30.0)
    else:
        log.warning("Neither GROQ_API_KEY nor ANTHROPIC_API_KEY set — Generator will fail")
        client = None  # type: ignore

    return Generator(client=client, model=model, temperature=temperature, max_tokens=max_tokens)


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load generation.yaml; falls back to defaults if path not given."""
    if config_path is None:
        config_path = Path(__file__).parent / "config" / "generation.yaml"
    return yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
