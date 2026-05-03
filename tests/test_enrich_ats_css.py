"""Tests for tier 2: per-ATS CSS selector library."""

from pathlib import Path

import pytest

from charon.enrich import ats_css


FIXTURES = Path(__file__).parent / "fixtures"


class TestWorkdaySelectors:
    def test_extracts_from_jobpostingdescription_div(self):
        html = (FIXTURES / "workday_job_page.html").read_text(encoding="utf-8")
        result = ats_css.extract_description(html, "workday")
        assert result is not None
        assert "Senior Detection Engineer" in result
        assert "Build SIEM and EDR detections" in result
        # Stripped tags
        assert "<h3>" not in result
        # Header/footer noise excluded
        assert "Copyright" not in result


class TestGreenhouseSelectors:
    def test_extracts_from_content_div(self):
        html = (FIXTURES / "greenhouse_job_page.html").read_text(encoding="utf-8")
        result = ats_css.extract_description(html, "greenhouse")
        assert result is not None
        assert "Application Security Engineer" in result
        assert "Lead threat modeling" in result


class TestNoMatch:
    def test_unknown_ats_returns_none(self):
        html = "<html><body><div>content</div></body></html>"
        assert ats_css.extract_description(html, "unknown") is None

    def test_no_matching_selector(self):
        html = "<html><body><div class='not-a-known-selector'>x</div></body></html>"
        assert ats_css.extract_description(html, "greenhouse") is None

    def test_empty_html(self):
        assert ats_css.extract_description("", "greenhouse") is None

    def test_too_short_content_filtered(self):
        # A matching div but with content under the 100-char threshold
        html = '<html><body><div id="content">tiny</div></body></html>'
        assert ats_css.extract_description(html, "greenhouse") is None
