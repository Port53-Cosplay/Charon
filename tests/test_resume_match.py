"""Tests for the resume_match analyzer (loader + result validation)."""

from pathlib import Path

import pytest

from charon.resume_match import (
    ResumeMatchError,
    _resolve_resume_path,
    load_resume_text,
    validate_match_result,
)


class TestLoaderPathResolution:
    def test_file_path_returned_directly(self, tmp_path):
        f = tmp_path / "resume.md"
        f.write_text("# resume", encoding="utf-8")
        resolved = _resolve_resume_path(str(f))
        assert resolved == f

    def test_directory_picks_md_first(self, tmp_path):
        (tmp_path / "resume.txt").write_text("txt", encoding="utf-8")
        (tmp_path / "resume.md").write_text("md", encoding="utf-8")
        resolved = _resolve_resume_path(str(tmp_path))
        assert resolved.suffix == ".md"

    def test_directory_falls_back_to_docx(self, tmp_path):
        (tmp_path / "x.docx").write_bytes(b"docx-bytes")
        resolved = _resolve_resume_path(str(tmp_path))
        assert resolved.suffix == ".docx"

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(ResumeMatchError, match="does not exist"):
            _resolve_resume_path(str(tmp_path / "nonexistent"))

    def test_empty_directory_raises(self, tmp_path):
        with pytest.raises(ResumeMatchError, match="No resume file"):
            _resolve_resume_path(str(tmp_path))


class TestLoadResumeText:
    def test_loads_md(self, tmp_path):
        f = tmp_path / "r.md"
        f.write_text("# DeAnna Shanks\n\nSecurity Analyst.\n", encoding="utf-8")
        text = load_resume_text(str(f))
        assert "DeAnna Shanks" in text
        assert "Security Analyst" in text

    def test_loads_txt(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text("Plain text resume content here.", encoding="utf-8")
        text = load_resume_text(str(f))
        assert "Plain text" in text

    def test_unsupported_format_raises(self, tmp_path):
        f = tmp_path / "r.html"
        f.write_text("<html>nope</html>", encoding="utf-8")
        with pytest.raises(ResumeMatchError, match="Unsupported"):
            load_resume_text(str(f))

    def test_empty_file_raises(self, tmp_path):
        f = tmp_path / "r.md"
        f.write_text("   \n  \n", encoding="utf-8")
        with pytest.raises(ResumeMatchError, match="empty"):
            load_resume_text(str(f))


class TestValidateResult:
    def test_normalizes_score_clamp(self):
        result = validate_match_result({
            "match_score": 150,
            "match_type": "direct",
            "overlap": ["x"],
            "gaps": [],
            "summary": "ok",
        })
        assert result["match_score"] == 100

    def test_unknown_match_type_defaults_to_stretch(self):
        result = validate_match_result({
            "match_score": 50,
            "match_type": "perfect",  # not in enum
            "overlap": [],
            "gaps": [],
            "summary": "x",
        })
        assert result["match_type"] == "stretch"

    def test_missing_required_key_raises(self):
        from charon.ai import AIError
        with pytest.raises(AIError, match="missing keys"):
            validate_match_result({
                "match_score": 50,
                "match_type": "direct",
                # missing overlap, gaps, summary
            })

    def test_non_list_overlap_normalized(self):
        result = validate_match_result({
            "match_score": 50,
            "match_type": "adjacent",
            "overlap": "not a list",  # wrong type
            "gaps": [],
            "summary": "x",
        })
        assert result["overlap"] == []
