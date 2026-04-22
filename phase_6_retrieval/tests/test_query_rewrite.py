"""Tests for query rewriting — rule-based and LLM-mocked."""
from __future__ import annotations

import pytest

from phase_6_retrieval.query_rewrite import QueryRewriter, expand_abbreviations


class TestExpandAbbreviations:
    def test_sip_expanded(self):
        result = expand_abbreviations("What is SIP?")
        assert "Systematic Investment Plan" in result

    def test_ter_expanded(self):
        result = expand_abbreviations("TER for HDFC fund")
        assert "Total Expense Ratio" in result

    def test_elss_expanded(self):
        result = expand_abbreviations("ELSS lock-in period")
        assert "Equity Linked Saving Scheme" in result

    def test_aum_expanded(self):
        result = expand_abbreviations("What is the AUM?")
        assert "Assets Under Management" in result

    def test_nav_expanded(self):
        result = expand_abbreviations("Current NAV of the fund")
        assert "Net Asset Value" in result

    def test_no_abbrev_unchanged(self):
        text = "What is the expense ratio of Bandhan Small Cap?"
        assert expand_abbreviations(text) == text

    def test_case_insensitive(self):
        result = expand_abbreviations("what is sip?")
        assert "Systematic Investment Plan" in result.lower() or "Systematic Investment Plan" in result

    def test_multiple_abbrevs(self):
        result = expand_abbreviations("SIP and TER explained")
        assert "Systematic Investment Plan" in result
        assert "Total Expense Ratio" in result


class TestQueryRewriterRuleBased:
    def test_rewrite_without_client_expands_abbrevs(self):
        rewriter = QueryRewriter(client=None)
        result = rewriter.rewrite("What is the TER?")
        assert "Total Expense Ratio" in result

    def test_rewrite_without_client_ignores_history(self):
        rewriter = QueryRewriter(client=None)
        history = [
            {"role": "user", "content": "Tell me about Bandhan Small Cap"},
            {"role": "assistant", "content": "The expense ratio is 0.41%."},
        ]
        result = rewriter.rewrite("What about its SIP?", history=history)
        assert "Systematic Investment Plan" in result

    def test_rewrite_plain_text_passthrough(self):
        rewriter = QueryRewriter(client=None)
        text = "expense ratio of HDFC Mid Cap Fund"
        assert rewriter.rewrite(text) == text


class TestQueryRewriterWithLLMMock:
    def test_llm_result_returned(self):
        _REWRITE_TEXT = "expense ratio of Bandhan Small Cap Fund Direct - Growth"

        class _Content:
            text = _REWRITE_TEXT

        class _Response:
            content = [_Content()]

        class _Messages:
            @staticmethod
            def create(**kwargs):
                return _Response()

        class _FakeClient:
            messages = _Messages()

        rewriter = QueryRewriter(client=_FakeClient(), model="claude-sonnet-4-6")
        result = rewriter.rewrite("its expense ratio", history=[
            {"role": "user", "content": "Tell me about Bandhan Small Cap"},
        ])
        assert "expense ratio" in result

    def test_llm_failure_falls_back_to_rule_based(self):
        class _BrokenClient:
            class messages:  # noqa: N801
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("network error")

        rewriter = QueryRewriter(client=_BrokenClient(), model="claude-sonnet-4-6")
        result = rewriter.rewrite("What is the TER?")
        # Should fall back to rule-based expansion
        assert "Total Expense Ratio" in result

    def test_empty_llm_response_falls_back(self):
        class _EmptyContent:
            text = ""

        class _EmptyResponse:
            content = [_EmptyContent()]

        class _EmptyMessages:
            @staticmethod
            def create(**kwargs):
                return _EmptyResponse()

        class _EmptyClient:
            messages = _EmptyMessages()

        rewriter = QueryRewriter(client=_EmptyClient(), model="claude-sonnet-4-6")
        result = rewriter.rewrite("What is the TER?")
        assert result  # not empty
