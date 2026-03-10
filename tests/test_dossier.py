"""Tests for company dossier logic."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from charon.ai import AIError
from charon.dossier import (
    validate_dossier_result,
    compute_weighted_score,
    save_dossier_markdown,
    VALID_DIMENSIONS,
)


def _make_dim(score=50.0, evidence=None, assessment="Test assessment."):
    return {
        "score": score,
        "evidence": evidence or ["Test evidence"],
        "assessment": assessment,
    }


def _make_valid(**overrides):
    base = {
        "company": "TestCorp",
        "summary": "Test summary.",
        "overall_score": 50.0,
        "dimensions": {d: _make_dim() for d in VALID_DIMENSIONS},
        "verdict": "Test verdict.",
    }
    base.update(overrides)
    return base


class TestValidateDossierResult:
    def test_valid_result_passes(self):
        result = _make_valid()
        validated = validate_dossier_result(result)
        assert validated["company"] == "TestCorp"
        assert len(validated["dimensions"]) == 6

    def test_missing_keys_raises(self):
        with pytest.raises(AIError, match="missing keys"):
            validate_dossier_result({"company": "X"})

    def test_dimensions_not_dict_raises(self):
        result = _make_valid(dimensions="not a dict")
        with pytest.raises(AIError, match="must be a mapping"):
            validate_dossier_result(result)

    def test_missing_dimension_gets_defaults(self):
        result = _make_valid()
        result["dimensions"] = {"security_culture": _make_dim(score=80)}
        validated = validate_dossier_result(result)
        # Missing dims should get defaults
        assert "people_treatment" in validated["dimensions"]
        assert validated["dimensions"]["people_treatment"]["score"] == 50.0

    def test_score_clamped_high(self):
        result = _make_valid()
        result["dimensions"]["security_culture"]["score"] = 200
        validated = validate_dossier_result(result)
        assert validated["dimensions"]["security_culture"]["score"] == 100.0

    def test_score_clamped_low(self):
        result = _make_valid()
        result["dimensions"]["security_culture"]["score"] = -10
        validated = validate_dossier_result(result)
        assert validated["dimensions"]["security_culture"]["score"] == 0.0

    def test_non_numeric_score_defaults(self):
        result = _make_valid()
        result["dimensions"]["security_culture"]["score"] = "high"
        validated = validate_dossier_result(result)
        assert validated["dimensions"]["security_culture"]["score"] == 50.0

    def test_overall_score_recomputed(self):
        result = _make_valid()
        for dim in result["dimensions"]:
            result["dimensions"][dim]["score"] = 80
        result["overall_score"] = 999  # should be overridden
        validated = validate_dossier_result(result)
        assert validated["overall_score"] == 80.0

    def test_evidence_not_list_coerced(self):
        result = _make_valid()
        result["dimensions"]["security_culture"]["evidence"] = "single string"
        validated = validate_dossier_result(result)
        assert validated["dimensions"]["security_culture"]["evidence"] == ["single string"]

    def test_empty_company_defaults(self):
        result = _make_valid(company="")
        validated = validate_dossier_result(result)
        assert validated["company"] == "Unknown"

    def test_non_string_summary_defaults(self):
        result = _make_valid(summary=42)
        validated = validate_dossier_result(result)
        assert isinstance(validated["summary"], str)


class TestComputeWeightedScore:
    def test_equal_weights(self):
        dims = {d: {"score": 80.0} for d in VALID_DIMENSIONS}
        weights = {d: 0.2 for d in VALID_DIMENSIONS}
        assert compute_weighted_score(dims, weights) == 80.0

    def test_weighted_heavily(self):
        dims = {
            "security_culture": {"score": 100.0},
            "people_treatment": {"score": 0.0},
            "leadership_transparency": {"score": 0.0},
            "work_life_balance": {"score": 0.0},
            "compensation": {"score": 0.0},
        }
        weights = {
            "security_culture": 1.0,
            "people_treatment": 0.0,
            "leadership_transparency": 0.0,
            "work_life_balance": 0.0,
            "compensation": 0.0,
        }
        # Only security_culture has weight
        assert compute_weighted_score(dims, weights) == 100.0

    def test_empty_weights_returns_zero(self):
        dims = {d: {"score": 80.0} for d in VALID_DIMENSIONS}
        assert compute_weighted_score(dims, {}) == 0.0

    def test_missing_dimension_in_weights(self):
        dims = {"security_culture": {"score": 90.0}}
        weights = {"security_culture": 0.5, "nonexistent": 0.5}
        # Only security_culture matches
        assert compute_weighted_score(dims, weights) == 90.0


class TestSaveDossierMarkdown:
    def test_saves_file(self):
        result = _make_valid()
        result["weighted_score"] = 65.0
        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / ".charon" / "dossiers"
            save_dir.mkdir(parents=True)
            with patch("charon.dossier.Path.home", return_value=Path(tmpdir)):
                filepath = save_dossier_markdown(result, str(save_dir))
            assert filepath.exists()
            content = filepath.read_text(encoding="utf-8")
            assert "TestCorp" in content
            assert "65.0/100" in content

    def test_filename_sanitized(self):
        result = _make_valid(company="Evil; rm -rf / Corp")
        result["weighted_score"] = 50.0
        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / ".charon" / "dossiers"
            save_dir.mkdir(parents=True)
            with patch("charon.dossier.Path.home", return_value=Path(tmpdir)):
                filepath = save_dossier_markdown(result, str(save_dir))
            # Dangerous shell metacharacters must be stripped
            assert ";" not in filepath.name
            assert "/" not in filepath.stem

    def test_security_path_traversal_in_company_name(self):
        result = _make_valid(company="../../etc/cron.d/evil")
        result["weighted_score"] = 50.0
        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / ".charon" / "dossiers"
            save_dir.mkdir(parents=True)
            with patch("charon.dossier.Path.home", return_value=Path(tmpdir)):
                filepath = save_dossier_markdown(result, str(save_dir))
            # File should be in save_dir, not traversed out
            assert str(filepath).startswith(str(save_dir))

    def test_long_company_name_truncated(self):
        result = _make_valid(company="A" * 200)
        result["weighted_score"] = 50.0
        with tempfile.TemporaryDirectory() as tmpdir:
            save_dir = Path(tmpdir) / ".charon" / "dossiers"
            save_dir.mkdir(parents=True)
            with patch("charon.dossier.Path.home", return_value=Path(tmpdir)):
                filepath = save_dossier_markdown(result, str(save_dir))
            assert len(filepath.stem) <= 90  # 80 + "_dossier"

    def test_rejects_path_outside_charon_dir(self):
        """Directory traversal protection enforces saves within ~/.charon/."""
        result = _make_valid()
        result["weighted_score"] = 50.0
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(OSError, match="must be within"):
                save_dossier_markdown(result, tmpdir)
