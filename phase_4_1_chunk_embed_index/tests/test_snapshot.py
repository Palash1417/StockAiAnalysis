import pytest

from ingestion_pipeline.snapshot import (
    InMemoryCorpusPointer,
    SmokeQuery,
    SmokeTestFailed,
    SnapshotManager,
)


def test_swap_happens_on_full_pass():
    pointer = InMemoryCorpusPointer()
    mgr = SnapshotManager(
        pointer=pointer,
        smoke_queries=[SmokeQuery(query="expense ratio?")],
        smoke_runner=lambda v, q: 1.0,
    )
    live = mgr.try_swap("v1")
    assert live == "v1"
    assert pointer.get_live() == "v1"


def test_swap_blocked_on_any_smoke_failure():
    pointer = InMemoryCorpusPointer()
    pointer.set_live("v1")
    mgr = SnapshotManager(
        pointer=pointer,
        smoke_queries=[SmokeQuery(query="q")],
        smoke_runner=lambda v, q: 0.9,  # 90% pass — not enough
    )
    with pytest.raises(SmokeTestFailed):
        mgr.try_swap("v2")
    assert pointer.get_live() == "v1"  # unchanged — previous snapshot stays live


def test_gc_keeps_last_n_versions():
    pointer = InMemoryCorpusPointer()
    dropped = []
    mgr = SnapshotManager(
        pointer=pointer,
        smoke_queries=[],
        smoke_runner=lambda v, q: 1.0,
        keep_versions=3,
        gc=dropped.extend,
    )
    for i in range(1, 6):
        mgr.try_swap(f"v{i}")

    # Live is v5; anything older than the last 3 (v1, v2) must have been GC'd.
    assert pointer.get_live() == "v5"
    assert set(dropped) >= {"v1", "v2"}
    # v3, v4, v5 are within the keep window and must never be dropped.
    assert "v3" not in dropped
    assert "v4" not in dropped
    assert "v5" not in dropped
