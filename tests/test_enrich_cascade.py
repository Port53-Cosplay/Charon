"""End-to-end tests for the enrichment cascade orchestrator."""

from pathlib import Path

import pytest

from charon import enrich as enrich_pkg
from charon.db import (
    add_discovery,
    get_discovery,
    get_enrichment_counts,
    get_unenriched_discoveries,
)
from charon.enrich import (
    EnrichError,
    ats_css,
    enrich_batch,
    enrich_discovery,
    enrich_one_id,
    jsonld,
    llm,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _seed_discovery(**overrides):
    defaults = dict(
        ats="workday",
        slug="schellman",
        company="Schellman",
        role="Senior Engineer",
        url="https://schellman.wd1.myworkdayjobs.com/en-US/Careers/job/Tampa/Senior_R1",
        dedupe_hash=overrides.pop("dedupe_hash", "test-hash-1"),
        location="Tampa, FL",
        description="",  # Workday-style: empty by Phase 6 design
        posted_at="Posted 2 Days Ago",
        tier="tier_1",
        category="audit",
    )
    defaults.update(overrides)
    return add_discovery(**defaults)


class TestSkipPath:
    def test_long_existing_description_skipped(self, monkeypatch):
        # Greenhouse-style: gather already populated description
        long_desc = "x" * 800  # well over the 500 threshold
        new_id = _seed_discovery(
            ats="greenhouse",
            description=long_desc,
            url="https://boards.greenhouse.io/example/jobs/1",
            dedupe_hash="skip-1",
        )

        # No HTTP fetch should happen — fail loudly if it does
        def boom(url):
            raise AssertionError("fetch_html should not be called on skip path")
        monkeypatch.setattr(enrich_pkg, "fetch_html", boom)

        result = enrich_one_id(new_id, profile=None, force=False)
        assert result["tier"] == "skipped"
        assert result["full_description"] == long_desc

        row = get_discovery(new_id)
        assert row["enrichment_tier"] == "skipped"
        assert row["full_description"] == long_desc

    def test_force_overrides_skip(self, monkeypatch):
        long_desc = "y" * 800
        new_id = _seed_discovery(
            ats="greenhouse",
            description=long_desc,
            url="https://boards.greenhouse.io/example/jobs/2",
            dedupe_hash="skip-2",
        )

        # With force=True, fetch IS called → return JSON-LD html
        jsonld_html = (FIXTURES / "jsonld_workday.html").read_text(encoding="utf-8")
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: jsonld_html)

        result = enrich_one_id(new_id, profile=None, force=True)
        assert result["tier"] == "jsonld"
        assert "Senior Detection Engineer" in result["full_description"]


class TestTier1JSONLD:
    def test_jsonld_path(self, monkeypatch):
        new_id = _seed_discovery(dedupe_hash="t1-1")
        jsonld_html = (FIXTURES / "jsonld_workday.html").read_text(encoding="utf-8")
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: jsonld_html)

        # Must not fall through to AI
        def boom(*a, **kw):
            raise AssertionError("LLM tier should not run when JSON-LD succeeds")
        monkeypatch.setattr(llm, "extract_description", boom)

        result = enrich_one_id(new_id, profile=None)
        assert result["tier"] == "jsonld"
        assert "SOC" in result["full_description"]


class TestTier2ATSCSS:
    def test_falls_through_when_no_jsonld(self, monkeypatch):
        new_id = _seed_discovery(dedupe_hash="t2-1")
        # Fixture has the description in a workday automation div, no JSON-LD
        wd_html = (FIXTURES / "workday_job_page.html").read_text(encoding="utf-8")
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: wd_html)

        def boom(*a, **kw):
            raise AssertionError("LLM tier should not run when CSS tier succeeds")
        monkeypatch.setattr(llm, "extract_description", boom)

        result = enrich_one_id(new_id, profile=None)
        assert result["tier"] == "ats_css"
        assert "Build SIEM and EDR detections" in result["full_description"]


class TestTier3LLM:
    def test_falls_through_to_llm(self, monkeypatch):
        new_id = _seed_discovery(dedupe_hash="t3-1")
        # HTML with no JSON-LD AND no recognized ATS selector
        bare_html = "<html><body><div class='unknown'>some job text we cannot extract structurally</div></body></html>"
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: bare_html)

        called = {"n": 0}
        def fake_llm(text, model="claude-haiku-4-5", profile=None):
            called["n"] += 1
            return "LLM-extracted description content here, definitely above the 100 char floor for the result handler."
        monkeypatch.setattr(llm, "extract_description", fake_llm)

        result = enrich_one_id(new_id, profile=None)
        assert result["tier"] == "ai_fallback"
        assert "LLM-extracted" in result["full_description"]
        assert called["n"] == 1

    def test_llm_returns_none_marks_failed(self, monkeypatch):
        new_id = _seed_discovery(dedupe_hash="t3-2")
        bare_html = "<html><body>nothing extractable</body></html>"
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: bare_html)
        monkeypatch.setattr(llm, "extract_description", lambda *a, **kw: None)

        result = enrich_one_id(new_id, profile=None)
        assert result["tier"] == "failed"

    def test_llm_error_marks_failed(self, monkeypatch):
        new_id = _seed_discovery(dedupe_hash="t3-3")
        bare_html = "<html><body>nothing extractable</body></html>"
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: bare_html)

        def raise_llm(*a, **kw):
            raise llm.LLMError("API down")
        monkeypatch.setattr(llm, "extract_description", raise_llm)

        result = enrich_one_id(new_id, profile=None)
        assert result["tier"] == "failed"
        assert "API down" in (result.get("error") or "")


class TestFetchFailure:
    def test_fetch_error_marks_failed(self, monkeypatch):
        new_id = _seed_discovery(dedupe_hash="ff-1")
        from charon.fetcher import FetchError
        def boom(url):
            raise FetchError("HTTP 503. The gates are closed.")
        monkeypatch.setattr(enrich_pkg, "fetch_html", boom)

        result = enrich_one_id(new_id, profile=None)
        assert result["tier"] == "failed"
        assert "503" in (result.get("error") or "")


class TestBatch:
    def test_only_unenriched_by_default(self, monkeypatch):
        new1 = _seed_discovery(dedupe_hash="b1")
        new2 = _seed_discovery(dedupe_hash="b2",
                               url="https://schellman.wd1.myworkdayjobs.com/Careers/job/X/Y_R2")
        # Pre-mark one as enriched
        from charon.db import update_discovery_enrichment
        update_discovery_enrichment(new2, "jsonld", "Existing description")

        jsonld_html = (FIXTURES / "jsonld_workday.html").read_text(encoding="utf-8")
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: jsonld_html)

        results = enrich_batch(profile=None, rate_limit_seconds=0)
        # Only new1 should be processed; new2 stays as it was
        assert len(results) == 1
        assert results[0]["discovery_id"] == new1

    def test_force_reenriches(self, monkeypatch):
        new1 = _seed_discovery(dedupe_hash="bf1")
        from charon.db import update_discovery_enrichment
        update_discovery_enrichment(new1, "jsonld", "Old description value")

        jsonld_html = (FIXTURES / "jsonld_workday.html").read_text(encoding="utf-8")
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: jsonld_html)

        results = enrich_batch(profile=None, rate_limit_seconds=0, force=True)
        assert len(results) >= 1

    def test_filter_by_ats(self, monkeypatch):
        wd_id = _seed_discovery(dedupe_hash="bA-wd",
                                url="https://schellman.wd1.myworkdayjobs.com/Careers/job/A/B_R1")
        gh_id = _seed_discovery(
            ats="greenhouse",
            slug="example",
            company="Example Co",
            url="https://boards.greenhouse.io/example/jobs/77",
            dedupe_hash="bA-gh",
            description="",  # force fetch
        )

        jsonld_html = (FIXTURES / "jsonld_workday.html").read_text(encoding="utf-8")
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: jsonld_html)

        results = enrich_batch(ats="workday", profile=None, rate_limit_seconds=0)
        assert all(r["discovery_id"] == wd_id for r in results)


class TestStats:
    def test_counts_by_tier(self, monkeypatch):
        new1 = _seed_discovery(dedupe_hash="st-1")
        new2 = _seed_discovery(dedupe_hash="st-2",
                               url="https://schellman.wd1.myworkdayjobs.com/Careers/job/X/Y_R2")

        jsonld_html = (FIXTURES / "jsonld_workday.html").read_text(encoding="utf-8")
        monkeypatch.setattr(enrich_pkg, "fetch_html", lambda url: jsonld_html)

        enrich_one_id(new1, profile=None)
        enrich_one_id(new2, profile=None)

        counts = get_enrichment_counts()
        assert counts.get("jsonld") == 2


class TestErrorPaths:
    def test_unknown_id_raises(self):
        with pytest.raises(EnrichError, match="No discovery"):
            enrich_one_id(99999)
