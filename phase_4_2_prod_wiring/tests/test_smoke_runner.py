from phase_4_2_prod_wiring.adapters import PgFactKV, PgVectorIndex
from phase_4_2_prod_wiring.smoke import StructuralSmokeRunner
from phase_4_2_prod_wiring.smoke.runner import StructuralSmokeConfig


def _seed_chunks(ix: PgVectorIndex, source_ids: list[str], cv: str = "corpus_v1"):
    rows = [
        {
            "corpus_version": cv,
            "chunk_id": f"{sid}#fact#expense_ratio",
            "source_id": sid,
            "scheme": "S",
            "section": None,
            "segment_type": "fact_table",
            "text": "t",
            "embedding": [0.1, 0.1],
            "embed_model_id": "m",
            "chunk_hash": f"h-{sid}",
            "source_url": "u",
            "last_updated": "2026-04-19",
            "dim": 2,
        }
        for sid in source_ids
    ]
    ix.upsert(rows)


def _seed_facts(kv: PgFactKV, pairs):
    for scheme_id, field in pairs:
        kv.put(scheme_id, field, "0.67%", "u", "2026-04-19")


def test_passes_when_everything_present(connect):
    ix = PgVectorIndex(connect)
    kv = PgFactKV(connect)
    required = [("src_001", "expense_ratio"), ("src_002", "expense_ratio")]
    _seed_chunks(ix, ["src_001", "src_002"])
    _seed_facts(kv, required)

    runner = StructuralSmokeRunner(
        ix, kv,
        StructuralSmokeConfig(
            min_chunks=2,
            required_sources=["src_001", "src_002"],
            required_facts=required,
        ),
    )
    assert runner("corpus_v1") == 1.0


def test_fails_when_min_chunks_missed(connect):
    ix = PgVectorIndex(connect)
    kv = PgFactKV(connect)
    _seed_chunks(ix, ["src_001"])
    _seed_facts(kv, [("src_001", "expense_ratio")])

    runner = StructuralSmokeRunner(
        ix, kv,
        StructuralSmokeConfig(
            min_chunks=5,
            required_sources=["src_001"],
            required_facts=[("src_001", "expense_ratio")],
        ),
    )
    rate = runner("corpus_v1")
    assert rate < 1.0


def test_fails_when_source_missing(connect):
    ix = PgVectorIndex(connect)
    kv = PgFactKV(connect)
    _seed_chunks(ix, ["src_001"])
    _seed_facts(kv, [("src_001", "expense_ratio"), ("src_002", "expense_ratio")])

    runner = StructuralSmokeRunner(
        ix, kv,
        StructuralSmokeConfig(
            min_chunks=1,
            required_sources=["src_001", "src_002"],
            required_facts=[
                ("src_001", "expense_ratio"),
                ("src_002", "expense_ratio"),
            ],
        ),
    )
    assert runner("corpus_v1") < 1.0


def test_fails_when_required_fact_absent(connect):
    ix = PgVectorIndex(connect)
    kv = PgFactKV(connect)
    _seed_chunks(ix, ["src_001"])
    # Do not seed the required fact
    runner = StructuralSmokeRunner(
        ix, kv,
        StructuralSmokeConfig(
            min_chunks=1,
            required_sources=["src_001"],
            required_facts=[("src_001", "expense_ratio")],
        ),
    )
    assert runner("corpus_v1") < 1.0


def test_signature_accepts_queries_arg(connect):
    """SmokeRunner alias is Callable[[str, list], float]."""
    ix = PgVectorIndex(connect)
    kv = PgFactKV(connect)
    _seed_chunks(ix, ["src_001"])
    _seed_facts(kv, [("src_001", "expense_ratio")])

    runner = StructuralSmokeRunner(
        ix, kv,
        StructuralSmokeConfig(
            min_chunks=1,
            required_sources=["src_001"],
            required_facts=[("src_001", "expense_ratio")],
        ),
    )
    # Pass something in for `queries` even though the structural runner
    # ignores it; this confirms the signature matches.
    assert runner("corpus_v1", queries=["ignored"]) == 1.0
