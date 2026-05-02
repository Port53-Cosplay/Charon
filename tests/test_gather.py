"""Tests for the gather package — registry, dedupe, orchestrator, Greenhouse adapter."""

import json
from pathlib import Path

import httpx
import pytest

from charon import gather
from charon.db import add_application, get_discoveries
from charon.gather import (
    GatherError,
    gather_employer,
    gather_registry,
    list_employers,
    load_registry,
    make_dedupe_hash,
    normalize_url,
)
from charon.gather import greenhouse


FIXTURES = Path(__file__).parent / "fixtures"


# ── registry loader ──────────────────────────────────────────────────


class TestRegistryLoader:
    def test_loads_real_companies_yaml(self):
        registry = load_registry()
        assert "greenhouse" in registry
        # Sanity: at least one slug we know is in the file
        slugs = {e["slug"] for e in registry["greenhouse"] if isinstance(e, dict)}
        assert "datadog" in slugs

    def test_override_via_env(self, tmp_path, monkeypatch):
        custom = tmp_path / "companies.yaml"
        custom.write_text(
            "gather:\n"
            "  greenhouse:\n"
            "    - slug: testco\n"
            "      name: Test Company\n"
            "      tier: tier_2\n"
            "      category: appsec\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("CHARON_REGISTRY", str(custom))
        registry = load_registry()
        assert registry["greenhouse"][0]["slug"] == "testco"

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHARON_REGISTRY", str(tmp_path / "does-not-exist.yaml"))
        with pytest.raises(GatherError, match="No companies.yaml"):
            load_registry()

    def test_malformed_missing_gather_key(self, tmp_path, monkeypatch):
        bad = tmp_path / "companies.yaml"
        bad.write_text("not_gather:\n  - foo\n", encoding="utf-8")
        monkeypatch.setenv("CHARON_REGISTRY", str(bad))
        with pytest.raises(GatherError, match="gather"):
            load_registry()


class TestListEmployers:
    def test_flatten_all(self):
        registry = {
            "greenhouse": [{"slug": "a", "name": "A"}, {"slug": "b", "name": "B"}],
            "lever": [{"slug": "c", "name": "C"}],
        }
        pairs = list_employers(registry)
        assert len(pairs) == 3

    def test_filter_by_ats(self):
        registry = {
            "greenhouse": [{"slug": "a", "name": "A"}],
            "lever": [{"slug": "c", "name": "C"}],
        }
        pairs = list_employers(registry, ats="greenhouse")
        assert len(pairs) == 1
        assert pairs[0][1]["slug"] == "a"

    def test_skips_entries_without_slug(self):
        registry = {"greenhouse": [{"name": "no slug"}, {"slug": "ok", "name": "OK"}]}
        pairs = list_employers(registry)
        assert len(pairs) == 1


# ── dedupe utilities ─────────────────────────────────────────────────


class TestNormalizeURL:
    def test_strips_trailing_slash(self):
        assert normalize_url("https://x.com/jobs/1/") == "https://x.com/jobs/1"

    def test_strips_query(self):
        assert normalize_url("https://x.com/jobs/1?utm=x") == "https://x.com/jobs/1"

    def test_strips_fragment(self):
        assert normalize_url("https://x.com/jobs/1#apply") == "https://x.com/jobs/1"

    def test_lowercases_host(self):
        assert normalize_url("https://X.COM/Jobs") == "https://x.com/Jobs"


class TestMakeDedupeHash:
    def test_stable_across_query_changes(self):
        a = make_dedupe_hash("greenhouse", "https://x.com/jobs/1")
        b = make_dedupe_hash("greenhouse", "https://x.com/jobs/1?ref=email")
        assert a == b

    def test_different_per_ats(self):
        a = make_dedupe_hash("greenhouse", "https://x.com/jobs/1")
        b = make_dedupe_hash("lever", "https://x.com/jobs/1")
        assert a != b


# ── Greenhouse adapter ───────────────────────────────────────────────


def _greenhouse_mock_client(payload: dict, status_code: int = 200) -> httpx.Client:
    """Build an httpx client that returns the given JSON for any request."""
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, json={"error": "test"})
        return httpx.Response(200, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestGreenhouseAdapter:
    def test_fetches_and_normalizes(self):
        payload = json.loads((FIXTURES / "greenhouse_sample.json").read_text(encoding="utf-8"))
        client = _greenhouse_mock_client(payload)
        try:
            jobs = greenhouse.fetch_jobs("example", entry={"name": "Example Co"}, client=client)
        finally:
            client.close()

        assert len(jobs) == 3
        first = jobs[0]
        assert first["company"] == "Example Co"
        assert first["role"] == "Senior Security Engineer, Detection & Response"
        assert first["url"] == "https://boards.greenhouse.io/example/jobs/4001"
        assert first["location"] == "Remote - United States"
        # HTML-escaped content should be unescaped + tag-stripped
        assert "We're looking for a senior detection engineer" in first["description"]
        assert "EDR" in first["description"]
        assert "<p>" not in first["description"]
        assert first["posted_at"] == "2026-04-25T18:30:00Z"

    def test_string_location(self):
        payload = json.loads((FIXTURES / "greenhouse_sample.json").read_text(encoding="utf-8"))
        client = _greenhouse_mock_client(payload)
        try:
            jobs = greenhouse.fetch_jobs("example", client=client)
        finally:
            client.close()
        # Third job has a string location
        assert jobs[2]["location"] == "San Francisco, CA"

    def test_404_raises_gather_error(self):
        client = _greenhouse_mock_client({}, status_code=404)
        try:
            with pytest.raises(GatherError, match="404"):
                greenhouse.fetch_jobs("nonexistent-slug", client=client)
        finally:
            client.close()

    def test_empty_jobs_returns_empty_list(self):
        client = _greenhouse_mock_client({"jobs": []})
        try:
            jobs = greenhouse.fetch_jobs("empty", client=client)
        finally:
            client.close()
        assert jobs == []

    def test_missing_jobs_field_returns_empty(self):
        client = _greenhouse_mock_client({"meta": {"total": 0}})
        try:
            jobs = greenhouse.fetch_jobs("empty", client=client)
        finally:
            client.close()
        assert jobs == []

    def test_empty_slug_raises(self):
        with pytest.raises(GatherError, match="empty"):
            greenhouse.fetch_jobs("")

    def test_skips_jobs_missing_url_or_title(self):
        payload = {
            "jobs": [
                {"title": "Has title but no URL"},
                {"absolute_url": "https://example.com/jobs/1", "title": "Real job"},
                {"absolute_url": "https://example.com/jobs/2"},  # no title
            ]
        }
        client = _greenhouse_mock_client(payload)
        try:
            jobs = greenhouse.fetch_jobs("example", client=client)
        finally:
            client.close()
        assert len(jobs) == 1
        assert jobs[0]["role"] == "Real job"


# ── orchestration end-to-end ─────────────────────────────────────────


class TestGatherEmployer:
    def test_writes_new_discoveries(self, monkeypatch):
        payload = json.loads((FIXTURES / "greenhouse_sample.json").read_text(encoding="utf-8"))

        def fake_fetch(slug, *, entry=None, client=None):
            assert slug == "example"
            return [
                {
                    "company": "Example Co",
                    "role": j["title"],
                    "url": j["absolute_url"],
                    "location": (j["location"]["name"] if isinstance(j["location"], dict) else j["location"]),
                    "description": j.get("content", ""),
                    "posted_at": j.get("updated_at"),
                }
                for j in payload["jobs"]
            ]

        monkeypatch.setattr(greenhouse, "fetch_jobs", fake_fetch)

        entry = {"slug": "example", "name": "Example Co", "tier": "tier_2", "category": "appsec"}
        summary = gather_employer("greenhouse", entry)

        assert summary["fetched"] == 3
        assert summary["new"] == 3
        assert summary["dupes"] == 0
        assert summary["error"] is None

        rows = get_discoveries(slug="example")
        assert len(rows) == 3
        assert rows[0]["tier"] == "tier_2"
        assert rows[0]["category"] == "appsec"

    def test_dedupes_on_second_run(self, monkeypatch):
        payload = json.loads((FIXTURES / "greenhouse_sample.json").read_text(encoding="utf-8"))

        def fake_fetch(slug, *, entry=None, client=None):
            return [
                {
                    "company": "Example Co",
                    "role": j["title"],
                    "url": j["absolute_url"],
                    "description": "",
                    "posted_at": j.get("updated_at"),
                }
                for j in payload["jobs"]
            ]
        monkeypatch.setattr(greenhouse, "fetch_jobs", fake_fetch)
        entry = {"slug": "example", "name": "Example Co"}

        first = gather_employer("greenhouse", entry)
        second = gather_employer("greenhouse", entry)

        assert first["new"] == 3
        assert second["new"] == 0
        assert second["dupes"] == 3

    def test_dry_run_does_not_write(self, monkeypatch):
        def fake_fetch(slug, *, entry=None, client=None):
            return [{
                "company": "Example Co",
                "role": "SRE",
                "url": "https://boards.greenhouse.io/example/jobs/dryrun",
                "description": "",
            }]
        monkeypatch.setattr(greenhouse, "fetch_jobs", fake_fetch)
        entry = {"slug": "example", "name": "Example Co"}

        summary = gather_employer("greenhouse", entry, dry_run=True)
        assert summary["new"] == 1
        assert get_discoveries(slug="example") == []

    def test_skip_employer_in_applications(self, monkeypatch):
        called = {"n": 0}

        def fake_fetch(slug, *, entry=None, client=None):
            called["n"] += 1
            return []
        monkeypatch.setattr(greenhouse, "fetch_jobs", fake_fetch)

        entry = {"slug": "datadog", "name": "Datadog"}
        summary = gather_employer("greenhouse", entry, skip_companies={"datadog"})

        assert summary["skipped"] == -1
        assert called["n"] == 0  # adapter never invoked

    def test_skip_per_job_company(self, monkeypatch):
        def fake_fetch(slug, *, entry=None, client=None):
            return [
                {"company": "Datadog", "role": "X", "url": "https://x/1"},
                {"company": "Other", "role": "Y", "url": "https://x/2"},
            ]
        monkeypatch.setattr(greenhouse, "fetch_jobs", fake_fetch)
        entry = {"slug": "mixed", "name": "Mixed"}

        summary = gather_employer("greenhouse", entry, skip_companies={"datadog"})
        assert summary["fetched"] == 2
        assert summary["new"] == 1
        assert summary["skipped"] == 1

    def test_adapter_error_captured_in_summary(self, monkeypatch):
        def boom(slug, *, entry=None, client=None):
            raise GatherError("404 from upstream")
        monkeypatch.setattr(greenhouse, "fetch_jobs", boom)
        entry = {"slug": "broken", "name": "Broken"}

        summary = gather_employer("greenhouse", entry)
        assert summary["error"] == "404 from upstream"
        assert summary["new"] == 0


class TestGatherRegistry:
    def test_filter_by_slug(self, monkeypatch, tmp_path):
        custom = tmp_path / "companies.yaml"
        custom.write_text(
            "gather:\n"
            "  greenhouse:\n"
            "    - { slug: alpha, name: Alpha }\n"
            "    - { slug: beta,  name: Beta }\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("CHARON_REGISTRY", str(custom))

        seen = []
        def fake_fetch(slug, *, entry=None, client=None):
            seen.append(slug)
            return []
        monkeypatch.setattr(greenhouse, "fetch_jobs", fake_fetch)

        gather_registry(slug="beta", rate_limit_seconds=0)
        assert seen == ["beta"]

    def test_unimplemented_ats_reports_error_not_crash(self, monkeypatch, tmp_path):
        custom = tmp_path / "companies.yaml"
        custom.write_text(
            "gather:\n"
            "  workday:\n"
            "    - slug: schellman\n"
            "      name: Schellman\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("CHARON_REGISTRY", str(custom))

        results = gather_registry(rate_limit_seconds=0)
        assert len(results) == 1
        assert "not yet implemented" in (results[0]["error"] or "")
