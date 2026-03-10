"""Tests for ghost job analysis logic."""

import pytest

from charon.ai import AIError
from charon.ghostbust import validate_ghostbust_result


class TestValidateGhostbustResult:
    def test_valid_result_passes(self):
        result = {
            "ghost_score": 45,
            "confidence": "medium",
            "signals": [
                {"category": "vagueness", "severity": "yellow", "finding": "No team details"},
            ],
            "summary": "Some concerns noted.",
        }
        validated = validate_ghostbust_result(result)
        assert validated["ghost_score"] == 45
        assert validated["confidence"] == "medium"
        assert len(validated["signals"]) == 1

    def test_score_clamped_to_range(self):
        result = {
            "ghost_score": 150,
            "confidence": "high",
            "signals": [],
            "summary": "Off the charts.",
        }
        validated = validate_ghostbust_result(result)
        assert validated["ghost_score"] == 100

    def test_negative_score_clamped(self):
        result = {
            "ghost_score": -10,
            "confidence": "low",
            "signals": [],
            "summary": "Negative ghost.",
        }
        validated = validate_ghostbust_result(result)
        assert validated["ghost_score"] == 0

    def test_float_score_converted_to_int(self):
        result = {
            "ghost_score": 42.7,
            "confidence": "medium",
            "signals": [],
            "summary": "Float score.",
        }
        validated = validate_ghostbust_result(result)
        assert validated["ghost_score"] == 42
        assert isinstance(validated["ghost_score"], int)

    def test_invalid_confidence_defaults_to_medium(self):
        result = {
            "ghost_score": 50,
            "confidence": "super_high",
            "signals": [],
            "summary": "Bad confidence.",
        }
        validated = validate_ghostbust_result(result)
        assert validated["confidence"] == "medium"

    def test_missing_keys_raises(self):
        with pytest.raises(AIError, match="missing keys"):
            validate_ghostbust_result({"ghost_score": 50})

    def test_non_numeric_score_raises(self):
        result = {
            "ghost_score": "high",
            "confidence": "medium",
            "signals": [],
            "summary": "Bad score type.",
        }
        with pytest.raises(AIError, match="must be a number"):
            validate_ghostbust_result(result)

    def test_signals_not_list_raises(self):
        result = {
            "ghost_score": 50,
            "confidence": "medium",
            "signals": "not a list",
            "summary": "Bad signals.",
        }
        with pytest.raises(AIError, match="must be a list"):
            validate_ghostbust_result(result)

    def test_malformed_signals_filtered(self):
        result = {
            "ghost_score": 50,
            "confidence": "medium",
            "signals": [
                {"category": "vagueness", "severity": "yellow", "finding": "Valid signal"},
                {"category": "bad"},  # missing finding - should be filtered
                "not a dict",  # not a dict - should be filtered
                42,  # not a dict - should be filtered
            ],
            "summary": "Mixed signals.",
        }
        validated = validate_ghostbust_result(result)
        assert len(validated["signals"]) == 1
        assert validated["signals"][0]["finding"] == "Valid signal"

    def test_invalid_severity_normalized(self):
        result = {
            "ghost_score": 50,
            "confidence": "medium",
            "signals": [
                {"category": "test", "severity": "purple", "finding": "Bad severity"},
            ],
            "summary": "Bad severity.",
        }
        validated = validate_ghostbust_result(result)
        assert validated["signals"][0]["severity"] == "yellow"

    def test_missing_summary_gets_default(self):
        result = {
            "ghost_score": 50,
            "confidence": "medium",
            "signals": [],
            "summary": 12345,  # not a string
        }
        validated = validate_ghostbust_result(result)
        assert isinstance(validated["summary"], str)
        assert "Review signals" in validated["summary"]
