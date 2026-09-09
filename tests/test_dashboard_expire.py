"""Tests for the dashboard's expire surface: stats, unreject, /api/expire helper."""

import pytest

from charon import dashboard
from charon.dashboard import DashboardError
from charon.db import (
    add_discovery,
    expire_ready_discoveries,
    get_connection,
    get_discovery,
    update_discovery_judgement,
)


def _seed_ready(dedupe_hash, judged_at=None):
    new_id = add_discovery(
        ats="greenhouse",
        slug="datadog",
        company="Datadog",
        role="Engineer",
        url=f"https://example.com/{dedupe_hash}",
        dedupe_hash=dedupe_hash,
        location="Remote",
        description="",
        posted_at="2026-04-15T12:00:00Z",
        tier="tier_3",
        category="security_product_general",
    )
    update_discovery_judgement(
        new_id,
        ghost_score=10,
        redflag_score=10,
        alignment_score=80,
        combined_score=80.0,
        screened_status="ready",
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


class TestStatsExpired:
    def test_expired_count_and_ready_decrement(self):
        _seed_ready("dx-1")
        _seed_ready("dx-2")
        expire_ready_discoveries()
        _seed_ready("dx-3")

        s = dashboard._stats()
        assert s["expired"] == 2
        assert s["ready"] == 1

    def test_awaiting_enrich_excludes_expired(self):
        rid = _seed_ready("dx-enrich")
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE discoveries SET enrichment_tier = 'failed' WHERE id = ?",
                (rid,),
            )
            conn.commit()
        finally:
            conn.close()
        before = dashboard._stats()["awaiting_enrich"]
        expire_ready_discoveries()
        after = dashboard._stats()["awaiting_enrich"]
        assert after == before - 1


class TestUnrejectExpired:
    def test_unreject_revives_expired(self):
        rid = _seed_ready("dx-unrej")
        expire_ready_discoveries()
        assert get_discovery(rid)["screened_status"] == "expired"

        rec = dashboard._unreject_discovery(rid)
        assert rec["new_status"] == "ready"
        row = get_discovery(rid)
        assert row["screened_status"] == "ready"
        assert row["expired_at"] is None

    def test_unreject_still_blocks_other_statuses(self):
        new_id = add_discovery(
            ats="greenhouse",
            slug="x",
            company="X",
            role="Y",
            url="https://example.com/dx-new",
            dedupe_hash="dx-new",
            location=None,
            description="",
            posted_at=None,
            tier=None,
            category=None,
        )
        with pytest.raises(DashboardError, match="isn't refused or expired"):
            dashboard._unreject_discovery(new_id)


class TestExpireStaleReady:
    OLD = "2026-01-01T00:00:00+00:00"

    def test_flips_only_old_rows(self):
        old = _seed_ready("dx-old", judged_at=self.OLD)
        fresh = _seed_ready("dx-fresh")

        result = dashboard._expire_stale_ready(30)
        assert result["expired"] == 1
        assert get_discovery(old)["screened_status"] == "expired"
        assert get_discovery(fresh)["screened_status"] == "ready"

    def test_days_out_of_range_raises(self):
        with pytest.raises(DashboardError, match="between 1 and 3650"):
            dashboard._expire_stale_ready(0)

    def test_refuses_while_pipeline_busy(self, monkeypatch):
        monkeypatch.setattr(dashboard, "_pipeline_busy", lambda: "judge")
        with pytest.raises(DashboardError, match="already running"):
            dashboard._expire_stale_ready(30)
