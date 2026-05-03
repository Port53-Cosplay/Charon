"""Tests for tier 1: JSON-LD JobPosting extractor."""

from pathlib import Path

import pytest

from charon.enrich import jsonld


FIXTURES = Path(__file__).parent / "fixtures"


class TestJSONLDExtraction:
    def test_extracts_simple_jobposting(self):
        html = (FIXTURES / "jsonld_workday.html").read_text(encoding="utf-8")
        result = jsonld.extract_description(html)
        assert result is not None
        assert "Senior Detection Engineer to join our SOC" in result
        # HTML inside the description should be stripped
        assert "<p>" not in result
        assert "<ul>" not in result
        assert "Build SIEM rules" in result
        assert "Tune EDR coverage" in result

    def test_extracts_from_graph(self):
        html = (FIXTURES / "jsonld_graph.html").read_text(encoding="utf-8")
        result = jsonld.extract_description(html)
        assert result is not None
        assert "SOC 2 program" in result

    def test_returns_none_when_no_jobposting(self):
        html = (FIXTURES / "jsonld_no_jobposting.html").read_text(encoding="utf-8")
        assert jsonld.extract_description(html) is None

    def test_no_script_tag(self):
        assert jsonld.extract_description("<html><body>nothing</body></html>") is None

    def test_empty_input(self):
        assert jsonld.extract_description("") is None

    def test_malformed_json_ignored(self):
        html = """
        <script type="application/ld+json">
        { not valid json
        </script>
        <script type="application/ld+json">
        {"@type": "JobPosting", "description": "Real description here, long enough."}
        </script>
        """
        result = jsonld.extract_description(html)
        assert result is not None
        assert "Real description here" in result

    def test_handles_html_entity_encoded_json(self):
        # Some sites HTML-encode their JSON-LD
        html = """
        <script type="application/ld+json">
        {&quot;@type&quot;: &quot;JobPosting&quot;, &quot;description&quot;: &quot;Encoded description content here.&quot;}
        </script>
        """
        result = jsonld.extract_description(html)
        assert result is not None
        assert "Encoded description content" in result

    def test_empty_description_field_skipped(self):
        html = """
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Engineer", "description": ""}
        </script>
        <script type="application/ld+json">
        {"@type": "JobPosting", "description": "Real one with content here."}
        </script>
        """
        result = jsonld.extract_description(html)
        assert result is not None
        assert "Real one with content" in result
