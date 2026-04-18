from ingestion_pipeline.chunker import Chunker
from ingestion_pipeline.models import ParsedDocument
from ingestion_pipeline.segmenter import DocumentSegmenter


def _doc(**kwargs):
    defaults = dict(
        source_id="src_002",
        scheme="Bandhan Small Cap Fund Direct - Growth",
        source_url="https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
        last_updated="2026-04-19",
    )
    defaults.update(kwargs)
    return ParsedDocument(**defaults)


# ---------------------------------------------------------------------------
# Segmenter
# ---------------------------------------------------------------------------
def test_segmenter_emits_fact_and_section_and_table():
    doc = _doc(
        facts={"expense_ratio": "0.67%", "exit_load": "1%"},
        sections=[
            {"heading": "Investment Objective", "body": "long enough prose " * 20, "level": 2}
        ],
        tables=[
            {
                "index": 0,
                "caption": "Top Holdings",
                "headers": ["Name", "Weight"],
                "rows": [["A", "5%"], ["B", "3%"]],
            }
        ],
    )
    segments = DocumentSegmenter().segment(doc)
    types = [s.segment_type for s in segments]
    assert "fact_table" in types
    assert "section_text" in types
    assert "table" in types


def test_segmenter_skips_empty_sections():
    doc = _doc(
        facts={"scheme": "x"},
        sections=[{"heading": "Empty", "body": "   "}],
    )
    segments = DocumentSegmenter().segment(doc)
    assert all(s.segment_type != "section_text" for s in segments)


# ---------------------------------------------------------------------------
# Fact-table chunks — §5.3.1
# ---------------------------------------------------------------------------
def test_fact_chunks_are_atomic_and_templated():
    doc = _doc(facts={"expense_ratio": "0.67%", "exit_load": "1%"})
    segments = DocumentSegmenter().segment(doc)
    chunks = Chunker().chunk(segments)

    fact_chunks = [c for c in chunks if c.segment_type == "fact_table"]
    ids = {c.chunk_id for c in fact_chunks}
    assert "src_002#fact#expense_ratio" in ids
    assert "src_002#fact#exit_load" in ids

    er = next(c for c in fact_chunks if c.chunk_id.endswith("expense_ratio"))
    assert "0.67%" in er.text
    assert er.scheme in er.text
    assert er.metadata["field_name"] == "expense_ratio"
    assert er.metadata["raw_value"] == "0.67%"


def test_fact_chunks_skip_empty_values():
    doc = _doc(facts={"expense_ratio": "0.67%", "exit_load": ""})
    chunks = Chunker().chunk(DocumentSegmenter().segment(doc))
    fact_ids = {c.chunk_id for c in chunks if c.segment_type == "fact_table"}
    assert "src_002#fact#expense_ratio" in fact_ids
    assert "src_002#fact#exit_load" not in fact_ids


# ---------------------------------------------------------------------------
# Section-text chunks — §5.3.2
# ---------------------------------------------------------------------------
def test_section_chunks_prefixed_with_heading():
    body = "This is the first sentence. " + ("filler words " * 200)
    doc = _doc(
        facts={"scheme": "x"},
        sections=[{"heading": "Investment Objective", "body": body, "level": 2}],
    )
    chunks = Chunker(target_tokens=80, overlap_tokens=10, min_tokens=10).chunk(
        DocumentSegmenter().segment(doc)
    )
    section_chunks = [c for c in chunks if c.segment_type == "section_text"]
    assert section_chunks, "expected at least one section chunk"
    assert all(c.text.startswith("Section: Investment Objective") for c in section_chunks)
    ids = [c.chunk_id for c in section_chunks]
    assert ids[0].endswith("#c0")


def test_section_splits_into_multiple_chunks_when_over_target():
    body = ". ".join(f"sentence number {i}" for i in range(200))
    doc = _doc(
        facts={"scheme": "x"},
        sections=[{"heading": "Long", "body": body, "level": 2}],
    )
    chunks = Chunker(target_tokens=50, overlap_tokens=5, min_tokens=5).chunk(
        DocumentSegmenter().segment(doc)
    )
    sec = [c for c in chunks if c.segment_type == "section_text"]
    assert len(sec) > 1, "long body should split into multiple chunks"


# ---------------------------------------------------------------------------
# Table chunks — §5.3.3
# ---------------------------------------------------------------------------
def test_table_chunks_respect_row_limit_and_include_header():
    rows = [[f"r{i}_a", f"r{i}_b"] for i in range(14)]
    doc = _doc(
        facts={"scheme": "x"},
        tables=[
            {
                "index": 0,
                "caption": "Holdings",
                "headers": ["Name", "Weight"],
                "rows": rows,
            }
        ],
    )
    chunks = Chunker().chunk(DocumentSegmenter().segment(doc))
    tbl = [c for c in chunks if c.segment_type == "table"]
    # 14 rows / 6 per chunk → 3 chunks
    assert len(tbl) == 3
    for c in tbl:
        assert "| Name | Weight |" in c.text
        assert c.text.startswith("**Holdings**")
