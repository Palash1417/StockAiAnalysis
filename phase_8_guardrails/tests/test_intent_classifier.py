import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_8_guardrails.intent_classifier import IntentClassifier, build_intent_classifier
from phase_8_guardrails.models import Intent


@pytest.fixture
def clf():
    return IntentClassifier(client=None)


class TestFactualIntent:
    def test_expense_ratio_query(self, clf):
        r = clf.classify("What is the expense ratio of HDFC Mid Cap Fund?")
        assert r.intent == Intent.FACTUAL

    def test_exit_load_query(self, clf):
        r = clf.classify("What is the exit load for Bandhan Small Cap Fund?")
        assert r.intent == Intent.FACTUAL

    def test_min_sip_query(self, clf):
        r = clf.classify("What is the minimum SIP amount for Nippon Taiwan Fund?")
        assert r.intent == Intent.FACTUAL

    def test_benchmark_query(self, clf):
        r = clf.classify("What is the benchmark index for HDFC Mid Cap Fund Direct?")
        assert r.intent == Intent.FACTUAL


class TestAdvisoryIntent:
    def test_should_i_invest(self, clf):
        r = clf.classify("Should I invest in HDFC Mid Cap Fund?")
        assert r.intent == Intent.ADVISORY

    def test_recommend_query(self, clf):
        r = clf.classify("Can you recommend a good mutual fund?")
        assert r.intent == Intent.ADVISORY

    def test_which_is_better(self, clf):
        r = clf.classify("Which fund is better, HDFC Mid Cap or Bandhan Small Cap?")
        assert r.intent == Intent.ADVISORY

    def test_worth_investing(self, clf):
        r = clf.classify("Is Bandhan Small Cap Fund worth investing in?")
        assert r.intent == Intent.ADVISORY


class TestPerformanceCalcIntent:
    def test_returns_query(self, clf):
        r = clf.classify("What are the returns of HDFC Mid Cap Fund?")
        assert r.intent == Intent.PERFORMANCE_CALC

    def test_cagr_query(self, clf):
        r = clf.classify("What is the CAGR of Nippon Taiwan Equity Fund?")
        assert r.intent == Intent.PERFORMANCE_CALC

    def test_past_performance(self, clf):
        r = clf.classify("Show me the past performance of Bandhan Small Cap Fund")
        assert r.intent == Intent.PERFORMANCE_CALC


class TestOutOfScopeIntent:
    def test_unknown_fund(self, clf):
        r = clf.classify("What is the expense ratio of SBI Bluechip Fund?")
        assert r.intent == Intent.OUT_OF_SCOPE

    def test_non_mf_topic(self, clf):
        r = clf.classify("What is the weather in Mumbai today?")
        assert r.intent == Intent.OUT_OF_SCOPE

    def test_build_factory_rule_based(self):
        clf = build_intent_classifier({"use_llm": False})
        assert isinstance(clf, IntentClassifier)
        assert clf._client is None
