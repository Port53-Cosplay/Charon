"""Tests for charon.batch module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from charon.batch import run_batch, _compute_recon_score, _build_results_table, _build_top_detail


# ── _compute_recon_score ─────────────────────────────────────────────


def test_recon_score_all_three():
    result = {
        "ghostbust": {"ghost_score": 20},
        "redflags": {"redflag_score": 30},
        "role_alignment": {"alignment_score": 80},
    }
    # (80 + 70 + 80) / 3 = 76.7
    assert _compute_recon_score(result) == 76.7


def test_recon_score_ghost_only():
    result = {"ghostbust": {"ghost_score": 90}}
    assert _compute_recon_score(result) == 10.0


def test_recon_score_empty():
    assert _compute_recon_score({}) == 0.0


def test_recon_score_ghost_killed():
    """Ghost-killed postings only have ghost data."""
    result = {
        "ghostbust": {"ghost_score": 85},
        "redflags": None,
        "role_alignment": None,
        "stopped_early": True,
    }
    assert _compute_recon_score(result) == 15.0


# ── _build_results_table ────────────────────────────────────────────


def test_results_table_sorted_by_overall():
    entries = [
        {"url": "http://a.com", "overall": 30.0, "ghost": 70, "redflag": 60, "role_align": None, "error": None},
        {"url": "http://b.com", "overall": 80.0, "ghost": 10, "redflag": 20, "role_align": 90, "error": None},
    ]
    table = _build_results_table(entries)
    lines = table.strip().split("\n")
    # b.com (80) should be first data row (after header + separator)
    assert "http://b.com" in lines[2]
    assert "http://a.com" in lines[3]


def test_results_table_shows_errors():
    entries = [
        {"url": "http://bad.com", "overall": 0.0, "ghost": None, "redflag": None, "role_align": None, "error": "Connection refused"},
    ]
    table = _build_results_table(entries)
    assert "(Connection refused)" in table


# ── _build_top_detail ───────────────────────────────────────────────


def test_top_detail_includes_all_sections():
    entry = {
        "url": "http://good.com",
        "overall": 85.0,
        "result": {
            "ghostbust": {
                "ghost_score": 10,
                "confidence": "high",
                "signals": [{"severity": "green", "category": "posting", "finding": "Looks real"}],
            },
            "redflags": {
                "redflag_score": 15,
                "dealbreakers_found": [],
                "yellow_flags_found": [{"flag": "Vague role", "evidence": "No specifics"}],
                "green_flags_found": [{"flag": "Good benefits"}],
            },
            "role_alignment": {
                "alignment_score": 90,
                "closest_target": "Security Analyst",
                "overlap": ["SIEM experience"],
                "gaps": ["Cloud security"],
                "stepping_stone": True,
                "assessment": "Strong fit.",
            },
        },
    }
    detail = _build_top_detail(entry)
    assert "http://good.com" in detail
    assert "Ghost Analysis" in detail
    assert "Red Flags" in detail
    assert "Role Alignment" in detail
    assert "Security Analyst" in detail
    assert "Stepping stone: Yes" in detail


# ── run_batch ────────────────────────────────────────────────────────


def _make_recon_result(ghost=20, redflag=30, role_align=80):
    result = {
        "ghostbust": {"ghost_score": ghost, "confidence": "high", "signals": []},
        "redflags": {"redflag_score": redflag, "dealbreakers_found": [], "yellow_flags_found": [], "green_flags_found": []},
        "role_alignment": {"alignment_score": role_align, "closest_target": "Analyst", "overlap": [], "gaps": [], "stepping_stone": True, "assessment": "OK"},
        "company": "TestCo",
        "stopped_early": False,
    }
    return result, "fake posting text"


@patch("charon.batch.run_hunt_recon")
def test_run_batch_writes_results(mock_recon, tmp_path):
    mock_recon.return_value = _make_recon_result()

    input_file = tmp_path / "jobs.txt"
    input_file.write_text("http://example.com/job1\nhttp://example.com/job2\n", encoding="utf-8")

    summary = run_batch(str(input_file), 75, {})

    assert summary["total"] == 2
    assert summary["errors"] == 0
    assert Path(summary["results_path"]).exists()

    results_text = Path(summary["results_path"]).read_text(encoding="utf-8")
    assert "http://example.com/job1" in results_text
    assert "http://example.com/job2" in results_text


@patch("charon.batch.run_hunt_recon")
def test_run_batch_skips_comments_and_blanks(mock_recon, tmp_path):
    mock_recon.return_value = _make_recon_result()

    input_file = tmp_path / "jobs.txt"
    input_file.write_text("# header comment\nhttp://a.com\n\n# another\nhttp://b.com\n", encoding="utf-8")

    summary = run_batch(str(input_file), 75, {})
    assert summary["total"] == 2
    assert mock_recon.call_count == 2


@patch("charon.batch.run_hunt_recon")
def test_run_batch_handles_errors(mock_recon, tmp_path):
    from charon.fetcher import FetchError
    mock_recon.side_effect = FetchError("Connection refused")

    input_file = tmp_path / "jobs.txt"
    input_file.write_text("http://bad.com\n", encoding="utf-8")

    summary = run_batch(str(input_file), 75, {})
    assert summary["total"] == 1
    assert summary["errors"] == 1
    assert summary["entries"][0]["error"] is not None


@patch("charon.batch.run_hunt_recon")
def test_run_batch_top_file_only_when_above_threshold(mock_recon, tmp_path):
    # All scores below threshold
    mock_recon.return_value = _make_recon_result(ghost=60, redflag=60, role_align=30)

    input_file = tmp_path / "low.txt"
    input_file.write_text("http://meh.com\n", encoding="utf-8")

    summary = run_batch(str(input_file), 75, {})
    assert summary["above_threshold"] == 0
    assert summary["top_path"] is None


@patch("charon.batch.run_hunt_recon")
def test_run_batch_writes_top_file(mock_recon, tmp_path):
    # High scores
    mock_recon.return_value = _make_recon_result(ghost=5, redflag=10, role_align=95)

    input_file = tmp_path / "good.txt"
    input_file.write_text("http://great.com\n", encoding="utf-8")

    summary = run_batch(str(input_file), 75, {})
    assert summary["above_threshold"] == 1
    assert summary["top_path"] is not None
    assert Path(summary["top_path"]).exists()

    top_text = Path(summary["top_path"]).read_text(encoding="utf-8")
    assert "http://great.com" in top_text


@patch("charon.batch.run_hunt_recon")
def test_run_batch_empty_file(mock_recon, tmp_path):
    input_file = tmp_path / "empty.txt"
    input_file.write_text("# just comments\n\n", encoding="utf-8")

    summary = run_batch(str(input_file), 75, {})
    assert summary["total"] == 0
    assert mock_recon.call_count == 0
