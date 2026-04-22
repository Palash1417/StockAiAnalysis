"""Top-level Guardrails facade — §8.

Usage:
    g = build_guardrails(config)

    # Before retrieval
    input_result = g.check_input(query)
    if not input_result.passed:
        return input_result.refusal_response

    # After generation
    output_result = g.check_output(query, generation_response, candidates)
    if not output_result.passed:
        return insufficient_context_response()   # or a guardrail-specific refusal

build_guardrails(config) reads config/guardrails.yaml by default.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .input_guard import InputGuard, build_input_guard
from .models import InputGuardResult, OutputGuardResult
from .output_guard import OutputGuard, build_output_guard


class Guardrails:
    """Thin facade over InputGuard + OutputGuard."""

    def __init__(self, input_guard: InputGuard, output_guard: OutputGuard):
        self._input = input_guard
        self._output = output_guard

    def check_input(self, query: str) -> InputGuardResult:
        return self._input.check(query)

    def check_output(
        self,
        query: str,
        response: Any,
        candidates: list[Any],
    ) -> OutputGuardResult:
        return self._output.check(query, response, candidates)


def build_guardrails(config: dict[str, Any] | None = None) -> Guardrails:
    """Instantiate Guardrails from a config dict or the default YAML file."""
    if config is None:
        default_path = Path(__file__).parent / "config" / "guardrails.yaml"
        config = yaml.safe_load(default_path.read_text(encoding="utf-8"))

    return Guardrails(
        input_guard=build_input_guard(config),
        output_guard=build_output_guard(config),
    )
