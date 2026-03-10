"""Tests for hunt pipeline orchestration."""

import pytest

from charon.hunt import extract_company_name


class TestExtractCompanyName:
    def test_at_pattern(self):
        text = "Senior Engineer at Acme Corp is looking for talent."
        assert extract_company_name(text) == "Acme Corp"

    def test_about_pattern(self):
        text = "About CrowdStrike\nWe are a leading cybersecurity company."
        assert extract_company_name(text) == "CrowdStrike"

    def test_join_pattern(self):
        text = "Join Anthropic\nWe're building safe AI systems."
        assert extract_company_name(text) == "Anthropic"

    def test_hiring_pattern(self):
        text = "Google is hiring for security roles."
        assert extract_company_name(text) == "Google"

    def test_no_match_returns_none(self):
        text = "some vague job posting with no company info whatsoever."
        assert extract_company_name(text) is None

    def test_too_short_name_rejected(self):
        text = "at X is hiring now."
        # Single character company names should be rejected
        assert extract_company_name(text) is None

    def test_very_long_name_rejected(self):
        long_name = "A" * 100
        text = f"About {long_name}\nWe do stuff."
        assert extract_company_name(text) is None


class TestComputeHuntScore:
    """Test the hunt score computation logic."""

    def test_perfect_scores(self):
        from charon.cli import _compute_hunt_score

        result = {
            "ghostbust": {"ghost_score": 0},
            "redflags": {"redflag_score": 0},
            "dossier": {"weighted_score": 100},
        }
        assert _compute_hunt_score(result) == 100.0

    def test_worst_scores(self):
        from charon.cli import _compute_hunt_score

        result = {
            "ghostbust": {"ghost_score": 100},
            "redflags": {"redflag_score": 100},
            "dossier": {"weighted_score": 0},
        }
        assert _compute_hunt_score(result) == 0.0

    def test_ghost_only(self):
        from charon.cli import _compute_hunt_score

        result = {
            "ghostbust": {"ghost_score": 30},
            "redflags": None,
            "dossier": None,
        }
        assert _compute_hunt_score(result) == 70.0

    def test_no_dossier(self):
        from charon.cli import _compute_hunt_score

        result = {
            "ghostbust": {"ghost_score": 20},
            "redflags": {"redflag_score": 40},
            "dossier": None,
        }
        # (80 + 60) / 2 = 70
        assert _compute_hunt_score(result) == 70.0

    def test_empty_result(self):
        from charon.cli import _compute_hunt_score

        result = {"ghostbust": None, "redflags": None, "dossier": None}
        assert _compute_hunt_score(result) == 0.0
