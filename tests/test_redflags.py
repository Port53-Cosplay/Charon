"""Tests for red flag analysis logic."""

import pytest

from charon.ai import AIError
from charon.redflags import validate_redflags_result


class TestValidateRedflagsResult:
    def _make_valid(self, **overrides):
        base = {
            "redflag_score": 50,
            "confidence": "medium",
            "dealbreakers_found": [],
            "yellow_flags_found": [],
            "green_flags_found": [],
            "summary": "Test summary.",
        }
        base.update(overrides)
        return base

    def test_valid_result_passes(self):
        result = self._make_valid(
            dealbreakers_found=[
                {"flag": "RTO required", "evidence": "in-office culture", "interpretation": "Not remote"}
            ],
            green_flags_found=[
                {"flag": "Salary posted", "evidence": "$150k-$200k"}
            ],
        )
        validated = validate_redflags_result(result)
        assert validated["redflag_score"] == 50
        assert len(validated["dealbreakers_found"]) == 1
        assert len(validated["green_flags_found"]) == 1

    def test_score_clamped_high(self):
        result = self._make_valid(redflag_score=200)
        assert validate_redflags_result(result)["redflag_score"] == 100

    def test_score_clamped_low(self):
        result = self._make_valid(redflag_score=-5)
        assert validate_redflags_result(result)["redflag_score"] == 0

    def test_float_score_to_int(self):
        result = self._make_valid(redflag_score=67.8)
        validated = validate_redflags_result(result)
        assert validated["redflag_score"] == 67
        assert isinstance(validated["redflag_score"], int)

    def test_non_numeric_score_raises(self):
        result = self._make_valid(redflag_score="bad")
        with pytest.raises(AIError, match="must be a number"):
            validate_redflags_result(result)

    def test_missing_keys_raises(self):
        with pytest.raises(AIError, match="missing keys"):
            validate_redflags_result({"redflag_score": 50})

    def test_invalid_confidence_defaults(self):
        result = self._make_valid(confidence="extreme")
        assert validate_redflags_result(result)["confidence"] == "medium"

    def test_dealbreakers_not_list_raises(self):
        result = self._make_valid(dealbreakers_found="not a list")
        with pytest.raises(AIError, match="must be a list"):
            validate_redflags_result(result)

    def test_malformed_dealbreakers_filtered(self):
        result = self._make_valid(dealbreakers_found=[
            {"flag": "Valid", "evidence": "quote", "interpretation": "bad"},
            {"evidence": "no flag key"},  # missing 'flag'
            "not a dict",
            42,
        ])
        validated = validate_redflags_result(result)
        assert len(validated["dealbreakers_found"]) == 1
        assert validated["dealbreakers_found"][0]["flag"] == "Valid"

    def test_malformed_greens_filtered(self):
        result = self._make_valid(green_flags_found=[
            {"flag": "Good thing", "evidence": "proof"},
            {"no_flag": "missing key"},
            None,
        ])
        validated = validate_redflags_result(result)
        assert len(validated["green_flags_found"]) == 1

    def test_green_flags_not_list_raises(self):
        result = self._make_valid(green_flags_found="not a list")
        with pytest.raises(AIError, match="must be a list"):
            validate_redflags_result(result)

    def test_missing_evidence_defaults_empty(self):
        result = self._make_valid(dealbreakers_found=[
            {"flag": "No evidence provided"}
        ])
        validated = validate_redflags_result(result)
        assert validated["dealbreakers_found"][0]["evidence"] == ""
        assert validated["dealbreakers_found"][0]["interpretation"] == ""

    def test_summary_non_string_gets_default(self):
        result = self._make_valid(summary=999)
        validated = validate_redflags_result(result)
        assert isinstance(validated["summary"], str)
        assert "Review flags" in validated["summary"]
