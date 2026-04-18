from scraping_service.models import ParsedDocument
from scraping_service.validator import Validator


def _doc(**facts):
    return ParsedDocument(source_id="src_x", scheme="Scheme X", facts=facts)


def test_ok_when_all_required_present():
    v = Validator(
        required_fields=["scheme", "expense_ratio", "exit_load"],
        tracked_fields=["scheme", "expense_ratio", "exit_load", "benchmark"],
    )
    result = v.validate(
        _doc(scheme="Scheme X", expense_ratio="0.67%", exit_load="1%", benchmark="NIFTY")
    )
    assert result.ok is True
    assert result.missing_required == []
    assert result.extraction_ratio == 1.0


def test_missing_required_marks_degraded():
    v = Validator(
        required_fields=["scheme", "expense_ratio", "exit_load"],
        tracked_fields=["scheme", "expense_ratio", "exit_load"],
    )
    result = v.validate(_doc(scheme="Scheme X", expense_ratio="0.67%"))
    assert result.ok is False
    assert result.missing_required == ["exit_load"]
    assert result.error == "missing field: exit_load"


def test_extraction_ratio_for_drift():
    v = Validator(
        required_fields=["scheme"],
        tracked_fields=["scheme", "expense_ratio", "exit_load", "benchmark"],
    )
    result = v.validate(_doc(scheme="Scheme X", expense_ratio="0.67%"))
    assert result.ok is True
    assert result.extraction_ratio == 0.5
