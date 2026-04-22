from phase_4_2_prod_wiring.adapters import PgCorpusPointer


def test_initial_live_is_none(connect):
    assert PgCorpusPointer(connect).get_live() is None


def test_set_live_records_history(connect):
    p = PgCorpusPointer(connect)
    p.set_live("corpus_v1")
    assert p.get_live() == "corpus_v1"
    assert p.history() == ["corpus_v1"]


def test_set_live_twice_records_both_versions(connect):
    p = PgCorpusPointer(connect)
    p.set_live("corpus_v1")
    p.set_live("corpus_v2")
    assert p.get_live() == "corpus_v2"
    assert p.history() == ["corpus_v1", "corpus_v2"]


def test_set_live_idempotent_for_history(connect):
    p = PgCorpusPointer(connect)
    p.set_live("corpus_v1")
    p.set_live("corpus_v1")
    assert p.history() == ["corpus_v1"]
