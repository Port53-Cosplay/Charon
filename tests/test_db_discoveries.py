"""Tests for the discoveries table CRUD helpers."""

import pytest

from charon.db import (
    add_application,
    add_discovery,
    discovery_exists,
    expire_ready_discoveries,
    get_applied_companies,
    get_connection,
    get_discoveries,
    get_discovery,
    get_discovery_counts,
    get_enrichable_discoveries,
    get_expirable_discoveries,
    get_unenriched_discoveries,
    update_application_status,
    update_discovery_judgement,
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


def _seed_judged(dedupe_hash, status="ready", judged_at=None):
    """Seed a discovery, judge it, optionally backdate judged_at."""
    new_id = _seed_discovery(dedupe_hash=dedupe_hash,
                             url=f"https://example.com/{dedupe_hash}")
    update_discovery_judgement(
        new_id,
        ghost_score=10,
        redflag_score=10,
        alignment_score=80,
        combined_score=80.0,
        screened_status=status,
        judgement_reason="combined 80.0 >= 60",
    )
    if judged_at is not None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE discoveries SET judged_at = ? WHERE id = ?",
                (judged_at, new_id),
            )
            conn.commit()
        finally:
            conn.close()
    return new_id


class TestExpire:
    OLD = "2026-01-01T00:00:00+00:00"

    def test_expire_all_ready(self):
        r1 = _seed_judged("ex-1")
        r2 = _seed_judged("ex-2")
        rej = _seed_judged("ex-3", status="rejected")
        fresh = _seed_discovery(dedupe_hash="ex-4", url="https://example.com/ex-4")

        count = expire_ready_discoveries()
        assert count == 2
        for rid in (r1, r2):
            row = get_discovery(rid)
            assert row["screened_status"] == "expired"
            assert row["expired_at"] is not None
            # The judge's verdict survives the archive
            assert row["judgement_reason"] == "combined 80.0 >= 60"
        assert get_discovery(rej)["screened_status"] == "rejected"
        assert get_discovery(fresh)["screened_status"] == "new"

    def test_expire_before_cutoff_only_flips_old(self):
        old = _seed_judged("ex-old", judged_at=self.OLD)
        recent = _seed_judged("ex-new")

        count = expire_ready_discoveries(before="2026-06-01")
        assert count == 1
        assert get_discovery(old)["screened_status"] == "expired"
        assert get_discovery(recent)["screened_status"] == "ready"

    def test_expire_before_accepts_z_suffix(self):
        old = _seed_judged("ex-z", judged_at=self.OLD)
        assert expire_ready_discoveries(before="2026-06-01T00:00:00Z") == 1
        assert get_discovery(old)["screened_status"] == "expired"

    def test_expire_older_than_days(self):
        old = _seed_judged("ex-days-old", judged_at=self.OLD)
        recent = _seed_judged("ex-days-new")

        count = expire_ready_discoveries(older_than_days=30)
        assert count == 1
        assert get_discovery(old)["screened_status"] == "expired"
        assert get_discovery(recent)["screened_status"] == "ready"

    def test_both_cutoffs_raises(self):
        with pytest.raises(ValueError, match="not both"):
            expire_ready_discoveries(before="2026-06-01", older_than_days=30)

    def test_garbage_before_raises(self):
        with pytest.raises(ValueError, match="Invalid ISO"):
            expire_ready_discoveries(before="last tuesday")

    def test_preview_matches_mutator(self):
        _seed_judged("ex-pv-1", judged_at=self.OLD)
        _seed_judged("ex-pv-2", judged_at=self.OLD)
        _seed_judged("ex-pv-3")

        preview_ids = {r["id"] for r in get_expirable_discoveries(before="2026-06-01")}
        count = expire_ready_discoveries(before="2026-06-01")
        assert count == len(preview_ids)
        expired_ids = {
            r["id"] for r in get_discoveries(status="expired")
        }
        assert expired_ids == preview_ids

    def test_judgement_writer_rejects_expired_status(self):
        new_id = _seed_discovery(dedupe_hash="ex-guard",
                                 url="https://example.com/ex-guard")
        with pytest.raises(ValueError, match="screened_status must be"):
            update_discovery_judgement(
                new_id,
                ghost_score=10,
                redflag_score=10,
                alignment_score=80,
                combined_score=80.0,
                screened_status="expired",
                judgement_reason="nope",
            )

    def test_rejudge_clears_expired_at(self):
        rid = _seed_judged("ex-revive")
        expire_ready_discoveries()
        assert get_discovery(rid)["expired_at"] is not None

        update_discovery_judgement(
            rid,
            ghost_score=10,
            redflag_score=10,
            alignment_score=85,
            combined_score=85.0,
            screened_status="ready",
            judgement_reason="revived",
        )
        row = get_discovery(rid)
        assert row["screened_status"] == "ready"
        assert row["expired_at"] is None

    def test_expired_rows_stay_out_of_enrich_pools(self):
        # A judged row whose enrichment later failed would re-enter the
        # enrichable pool if the picker only excluded 'rejected'.
        rid = _seed_judged("ex-pool")
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE discoveries SET enrichment_tier = 'failed' WHERE id = ?",
                (rid,),
            )
            conn.commit()
        finally:
            conn.close()
        expire_ready_discoveries()

        assert rid not in [r["id"] for r in get_enrichable_discoveries()]
        assert rid not in [r["id"] for r in get_unenriched_discoveries()]
