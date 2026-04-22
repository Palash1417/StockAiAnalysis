from phase_4_2_prod_wiring.adapters import PgFactKV


def test_put_then_get(connect):
    kv = PgFactKV(connect)
    kv.put("src_001", "expense_ratio", "0.67%", "https://groww.in/x", "2026-04-19")
    row = kv.get("src_001", "expense_ratio")
    assert row == {
        "value": "0.67%",
        "source_url": "https://groww.in/x",
        "last_updated": "2026-04-19",
    }


def test_get_missing_returns_none(connect):
    assert PgFactKV(connect).get("src_001", "nope") is None


def test_put_overwrites_value(connect):
    kv = PgFactKV(connect)
    kv.put("src_001", "expense_ratio", "0.67%", "u1", "2026-04-01")
    kv.put("src_001", "expense_ratio", "0.70%", "u2", "2026-04-19")
    row = kv.get("src_001", "expense_ratio")
    assert row["value"] == "0.70%"
    assert row["source_url"] == "u2"
    assert row["last_updated"] == "2026-04-19"
