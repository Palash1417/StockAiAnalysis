import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_8_guardrails.length_enforcer import enforce, split_sentences


class TestSplitSentences:
    def test_single_sentence(self):
        assert split_sentences("Hello world.") == ["Hello world."]

    def test_two_sentences(self):
        parts = split_sentences("First sentence. Second sentence.")
        assert len(parts) == 2

    def test_three_sentences(self):
        text = "One. Two. Three."
        parts = split_sentences(text)
        assert len(parts) == 3

    def test_percentage_not_split(self):
        # "0.67%" should not trigger a split
        text = "The expense ratio is 0.67%. The exit load is 1%."
        parts = split_sentences(text)
        assert len(parts) == 2


class TestEnforce:
    def test_within_limit_unchanged(self):
        text = "One sentence only."
        assert enforce(text, max_sentences=3) == text

    def test_exactly_three_unchanged(self):
        text = "First. Second. Third."
        result = enforce(text, max_sentences=3)
        assert result == text

    def test_four_sentences_truncated_to_three(self):
        text = "One. Two. Three. Four."
        result = enforce(text, max_sentences=3)
        parts = split_sentences(result)
        assert len(parts) == 3

    def test_truncated_result_ends_with_punctuation(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = enforce(text, max_sentences=3)
        assert result[-1] in ".!?"

    def test_empty_string(self):
        assert enforce("", max_sentences=3) == ""

    def test_custom_max_sentences(self):
        text = "A. B. C. D. E."
        result = enforce(text, max_sentences=2)
        parts = split_sentences(result)
        assert len(parts) == 2
