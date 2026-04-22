import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_8_guardrails.pii_scrubber import scrub


class TestPANDetection:
    def test_pan_detected(self):
        result = scrub("My PAN is ABCDE1234F")
        assert result.found
        assert "PAN" in result.types

    def test_pan_redacted_in_scrubbed_text(self):
        result = scrub("PAN: ABCDE1234F please help")
        assert "ABCDE1234F" not in result.scrubbed_text
        assert "[REDACTED_PAN]" in result.scrubbed_text

    def test_pan_lowercase_not_matched(self):
        # PAN must be all caps by format — lowercase is not a PAN
        result = scrub("abcde1234f is not a pan")
        assert not result.found


class TestAadhaarDetection:
    def test_aadhaar_12_digits_detected(self):
        result = scrub("My Aadhaar is 234567891234")
        assert result.found
        assert "Aadhaar" in result.types

    def test_aadhaar_spaced_detected(self):
        result = scrub("Aadhaar: 2345 6789 1234")
        assert result.found
        assert "Aadhaar" in result.types

    def test_aadhaar_redacted(self):
        result = scrub("Aadhaar 234567891234 is mine")
        assert "234567891234" not in result.scrubbed_text


class TestEmailDetection:
    def test_email_detected(self):
        result = scrub("Contact me at user@example.com")
        assert result.found
        assert "email" in result.types

    def test_email_redacted(self):
        result = scrub("Send to test.user+tag@domain.co.in")
        assert "test.user+tag@domain.co.in" not in result.scrubbed_text
        assert "[REDACTED_EMAIL]" in result.scrubbed_text


class TestPhoneDetection:
    def test_indian_mobile_detected(self):
        result = scrub("Call me on 9876543210")
        assert result.found
        assert "phone" in result.types

    def test_plus91_prefix_detected(self):
        result = scrub("My number is +919876543210")
        assert result.found
        assert "phone" in result.types

    def test_phone_redacted(self):
        result = scrub("Call 8123456789 for support")
        assert "8123456789" not in result.scrubbed_text


class TestCleanText:
    def test_clean_query_not_flagged(self):
        result = scrub("What is the expense ratio of HDFC Mid Cap Fund?")
        assert not result.found
        assert result.types == []

    def test_scrubbed_text_unchanged_when_clean(self):
        query = "What is the exit load for Bandhan Small Cap Fund?"
        result = scrub(query)
        assert result.scrubbed_text == query

    def test_multiple_pii_types_detected(self):
        result = scrub("PAN ABCDE1234F email user@test.com phone 9876543210")
        assert len(result.types) >= 2
