import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_8_guardrails.advice_detector import check


class TestAdvisoryDetected:
    def test_i_recommend(self):
        r = check("I recommend investing in this fund for long-term growth.")
        assert r.detected
        assert "i_recommend" in r.flagged_phrases

    def test_i_suggest(self):
        r = check("I suggest you consider this fund.")
        assert r.detected
        assert "i_suggest" in r.flagged_phrases

    def test_i_advise(self):
        r = check("I advise allocating 20% of your portfolio here.")
        assert r.detected
        assert "i_advise" in r.flagged_phrases

    def test_you_should_invest(self):
        r = check("You should invest in this fund now.")
        assert r.detected
        assert "you_should_invest" in r.flagged_phrases

    def test_would_recommend(self):
        r = check("I would recommend this fund for your goals.")
        assert r.detected
        assert "would_recommend" in r.flagged_phrases

    def test_worth_investing(self):
        r = check("This fund is worth investing in for conservative investors.")
        assert r.detected
        assert "worth_investing" in r.flagged_phrases

    def test_consider_investing(self):
        r = check("You should consider investing given the low expense ratio.")
        assert r.detected


class TestFactualAnswerPasses:
    def test_expense_ratio_answer(self):
        r = check(
            "The expense ratio of HDFC Mid Cap Fund Direct - Growth is 0.77%. "
            "Last updated from sources: 2026-04-20."
        )
        assert not r.detected

    def test_exit_load_answer(self):
        r = check(
            "The exit load is 1% if redeemed within 1 year of allotment. "
            "There is no exit load after 1 year."
        )
        assert not r.detected

    def test_lock_in_answer(self):
        r = check(
            "Bandhan Small Cap Fund has no lock-in period. "
            "It is an open-ended equity scheme."
        )
        assert not r.detected

    def test_multiple_flags_returned(self):
        r = check("I recommend this fund and I suggest you invest now.")
        assert r.detected
        assert len(r.flagged_phrases) >= 2
