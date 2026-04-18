from ingestion_pipeline.normalizer import normalize_for_display, normalize_for_hash


def test_currency_standardized():
    assert normalize_for_display("Rs. 500") == "₹500"
    assert normalize_for_display("INR 1,000") == "₹1,000"


def test_percentage_standardized():
    assert normalize_for_display("0.67 %") == "0.67%"


def test_whitespace_collapsed():
    assert normalize_for_display("a   b\n\nc") == "a b c"


def test_nfkc_applied():
    # Full-width digits → ASCII
    assert normalize_for_display("０.67％") == "0.67%"


def test_hash_normalization_lowercases():
    assert normalize_for_hash("HDFC Mid Cap") == "hdfc mid cap"
    # Display preserves case
    assert normalize_for_display("HDFC Mid Cap") == "HDFC Mid Cap"
