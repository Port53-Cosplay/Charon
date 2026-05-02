"""Tests for the discoveries table CRUD helpers."""

import pytest

from charon.db import (
    add_application,
    add_discovery,
    discovery_exists,
    get_applied_companies,
    get_discoveries,
    get_discovery,
    get_discovery_counts,
    update_application_status,
)


def _seed_discovery(**overrides):
    defaults = dict(
        ats="greenhouse",
        slug="datadog",
        company="Datadog",
        role="Senior Engineer",
        url="https://boards.greenhouse.io/datadog/jobs/12345",
        dedupe_hash="hash-12345",
        location="Remote",
        description="A real job, probably.",
        posted_at="2026-04-15T12:00:00Z",
        tier="tier_3",
        category="security_product_general",
    )
    defaults.update(overrides)
    return add_discovery(**defaults)


class TestAddDiscovery:
    def test_inserts_returns_id(self):
        new_id = _seed_discovery()
        assert isinstance(new_id, int)
        assert new_id > 0

    def test_dedupe_returns_none(self):
        first = _seed_discovery()
        second = _seed_discovery()
        assert first is not None
        assert second is None

    def test_dedupe_only_on_hash_not_url(self):
        # Same URL but different ats key — should be allowed because the
        # adapter is responsible for forming a hash that scopes by ATS.
        a = _seed_discovery(dedupe_hash="hash-A")
        b = _seed_discovery(dedupe_hash="hash-B")
        assert a is not None and b is not None and a != b


class TestDiscoveryQueries:
    def test_get_discovery_by_id(self):
        new_id = _seed_discovery()
        row = get_discovery(new_id)
        assert row is not None
        assert row["company"] == "Datadog"
        assert row["screened_status"] == "new"

    def test_get_discovery_missing(self):
        assert get_discovery(99999) is None

    def test_filter_by_ats(self):
        _seed_discovery(dedupe_hash="g1")
        _seed_discovery(ats="lever", slug="sysdig", company="Sysdig",
                        url="https://jobs.lever.co/sysdig/abc", dedupe_hash="l1")
        results = get_discoveries(ats="greenhouse")
        assert all(r["ats"] == "greenhouse" for r in results)
        assert len(results) >= 1

    def test_filter_by_slug(self):
        _seed_discovery(dedupe_hash="g2")
        _seed_discovery(slug="cloudflare", company="Cloudflare",
                        url="https://boards.greenhouse.io/cloudflare/jobs/9", dedupe_hash="cf1")
        results = get_discoveries(slug="cloudflare")
        assert len(results) == 1
        assert results[0]["slug"] == "cloudflare"

    def test_filter_by_status(self):
        _seed_discovery(dedupe_hash="status1")
        # All inserts default to 'new'
        results = get_discoveries(status="new")
        assert all(r["screened_status"] == "new" for r in results)
        assert get_discoveries(status="ready") == []


class TestDiscoveryExists:
    def test_returns_true_after_insert(self):
        _seed_discovery(dedupe_hash="exists-1")
        assert discovery_exists("exists-1") is True

    def test_returns_false_for_unknown(self):
        assert discovery_exists("nope-not-here") is False


class TestDiscoveryCounts:
    def test_empty(self):
        assert get_discovery_counts() == {}

    def test_grouped_by_ats(self):
        _seed_discovery(dedupe_hash="c1")
        _seed_discovery(dedupe_hash="c2",
                        url="https://boards.greenhouse.io/datadog/jobs/2")
        _seed_discovery(ats="lever", slug="sysdig", company="Sysdig",
                        url="https://jobs.lever.co/sysdig/x", dedupe_hash="lc1")
        counts = get_discovery_counts()
        assert counts.get("greenhouse") == 2
        assert counts.get("lever") == 1


class TestAppliedCompaniesSkip:
    def test_includes_active_applications(self):
        add_application(company="Datadog", role="SRE")
        applied = get_applied_companies()
        assert "datadog" in applied

    def test_excludes_rejected(self):
        app_id = add_application(company="RejectedCorp", role="Engineer")
        update_application_status(app_id, "rejected")
        applied = get_applied_companies()
        assert "rejectedcorp" not in applied

    def test_excludes_ghosted(self):
        app_id = add_application(company="GhostedCorp", role="Engineer")
        update_application_status(app_id, "ghosted")
        applied = get_applied_companies()
        assert "ghostedcorp" not in applied

    def test_includes_interviewing(self):
        app_id = add_application(company="ActiveCorp", role="Engineer")
        update_application_status(app_id, "interviewing")
        applied = get_applied_companies()
        assert "activecorp" in applied
