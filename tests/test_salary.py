"""Tests for the salary-intel lookup.

The lookup is offered on every card, prepped or not, so the folder
handling is the part worth pinning down: it uses the forge folder when
one exists and creates that same path when it doesn't.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from charon.db import add_discovery, get_connection
from charon.salary import SALARY_FILENAME, SalaryError, suggest_salary_for_discovery


AI_RESULT = {
    "currency": "USD",
    "low": 105000,
    "mid": 118000,
    "high": 130000,
    "confidence": "medium",
    "posted_range": None,
    "reasoning": "Market data converges around $110K.",
    "resume_factors": "Five years of investigation work.",
    "negotiation": "Open at $122K.",
    "sources": ["ZipRecruiter - $109,846"],
}


@pytest.fixture
def discovery_id():
    return add_discovery(
        ats="greenhouse",
        slug="testcorp",
        company="TestCorp",
        role="Senior SOC Analyst",
        url="https://example.com/jobs/1",
        dedupe_hash="salary-test-1",
        description="x" * 600,
    )


def _set_offerings_path(discovery_id, path):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE discoveries SET offerings_path = ? WHERE id = ?",
            (str(path), discovery_id),
        )
        conn.commit()
    finally:
        conn.close()


def _run(discovery_id, offerings_dir, result=None):
    profile = {"forge": {"offerings_dir": str(offerings_dir)}, "resume_path": ""}
    with patch("charon.profile.load_profile", return_value=profile), \
         patch("charon.ai.query_claude_web_search_json", return_value=result or AI_RESULT):
        return suggest_salary_for_discovery(discovery_id)


class TestFolderHandling:
    def test_creates_folder_when_row_has_none(self, discovery_id, tmp_path):
        offerings = tmp_path / "offerings"
        summary = _run(discovery_id, offerings)

        written = Path(summary["path"])
        assert written.name == SALARY_FILENAME
        assert written.is_file()
        # Same naming forge would have used: <company>-<role>-<id>
        assert written.parent.name == f"testcorp-senior-soc-analyst-{discovery_id}"
        assert written.parent.parent == offerings

    def test_uses_existing_offerings_folder(self, discovery_id, tmp_path):
        existing = tmp_path / "already-prepped"
        existing.mkdir()
        _set_offerings_path(discovery_id, existing)

        summary = _run(discovery_id, tmp_path / "offerings")

        assert Path(summary["path"]).parent == existing
        assert (existing / SALARY_FILENAME).is_file()

    def test_recreates_folder_recorded_but_missing_on_disk(self, discovery_id, tmp_path):
        gone = tmp_path / "deleted-by-hand"
        _set_offerings_path(discovery_id, gone)

        summary = _run(discovery_id, tmp_path / "offerings")

        assert Path(summary["path"]).parent == gone
        assert gone.is_dir()

    def test_unknown_discovery_raises(self, tmp_path):
        with pytest.raises(SalaryError, match="No discovery"):
            _run(999999, tmp_path / "offerings")


class TestResultValidation:
    def test_non_numeric_range_raises(self, discovery_id, tmp_path):
        bad = dict(AI_RESULT, mid="a lot")
        with pytest.raises(SalaryError, match="unusable range"):
            _run(discovery_id, tmp_path / "offerings", result=bad)

    def test_nothing_written_when_range_unusable(self, discovery_id, tmp_path):
        offerings = tmp_path / "offerings"
        bad = dict(AI_RESULT, low=None)
        with pytest.raises(SalaryError):
            _run(discovery_id, offerings, result=bad)

        folder = offerings / f"testcorp-senior-soc-analyst-{discovery_id}"
        assert not (folder / SALARY_FILENAME).exists()

    def test_summary_carries_structured_fields(self, discovery_id, tmp_path):
        summary = _run(discovery_id, tmp_path / "offerings")

        assert summary["low"] == 105000
        assert summary["mid"] == 118000
        assert summary["high"] == 130000
        assert summary["currency"] == "USD"
        assert summary["confidence"] == "medium"
        assert summary["company"] == "TestCorp"
