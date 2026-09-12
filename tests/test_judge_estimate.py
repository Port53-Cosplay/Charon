"""The judge gate's time estimate.

It used to multiply a guessed 3-6s per row and then divide by the worker
count, which promised 4-7 minutes for a 290-row batch that took 85. The
estimate now comes from completion timestamps of recent judging, which
already include whatever parallelism was in play.
"""

from datetime import datetime, timedelta, timezone

from charon import dashboard
from charon.db import add_discovery, get_connection, update_discovery_judgement


def _seed_judged(dedupe_hash, judged_at):
    new_id = add_discovery(
        ats="greenhouse",
        slug="vanta",
        company="Vanta",
        role="Security Analyst",
        url=f"https://example.com/{dedupe_hash}",
        dedupe_hash=dedupe_hash,
        location="Remote",
        description="x" * 900,
        posted_at=None,
        tier="tier_3",
        category="security_product_general",
    )
    update_discovery_judgement(
        new_id,
        ghost_score=10,
        redflag_score=10,
        alignment_score=80,
        combined_score=65.0,
        screened_status="rejected",
        judgement_reason="combined 65.0 < 70",
    )
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE discoveries SET judged_at = ? WHERE id = ?", (judged_at, new_id)
        )
        conn.commit()
    finally:
        conn.close()
    return new_id


def _seed_run(count, gap_secs, start=None):
    t = start or (datetime.now(timezone.utc) - timedelta(hours=1))
    for i in range(count):
        _seed_judged(f"je-{gap_secs}-{i}-{t.timestamp()}", (t + timedelta(seconds=i * gap_secs)).isoformat())


class TestMeasurement:
    def test_no_history_falls_back_and_says_so(self):
        est = dashboard._ferry_judge_estimates(100)
        assert est["time_basis"] == "estimated"
        assert est["secs_per_row_low"] == float(dashboard._JUDGE_SECS_LOW)

    def test_measures_from_completion_gaps(self):
        _seed_run(30, 5)
        est = dashboard._ferry_judge_estimates(120)
        assert est["time_basis"] == "measured"
        assert 4 <= est["secs_per_row_low"] <= 6
        assert 4 <= est["secs_per_row_high"] <= 6
        # 120 rows at ~5s each is ~10 minutes, not 10/workers.
        assert 8 <= est["est_minutes_low"] <= 12

    def test_a_slow_pace_is_reported_honestly(self):
        _seed_run(30, 18)
        est = dashboard._ferry_judge_estimates(290)
        assert est["time_basis"] == "measured"
        # The real case: 290 rows at ~18s is well over an hour.
        assert est["est_minutes_high"] >= 60

    def test_idle_gaps_between_batches_are_ignored(self):
        # Two runs hours apart; the gap between them is a pause, not a row.
        base = datetime.now(timezone.utc) - timedelta(hours=6)
        _seed_run(16, 4, start=base)
        _seed_run(16, 4, start=base + timedelta(hours=3))
        est = dashboard._ferry_judge_estimates(60)
        assert est["time_basis"] == "measured"
        assert est["secs_per_row_high"] < 10

    def test_cost_is_unchanged_by_the_timing_work(self):
        est = dashboard._ferry_judge_estimates(100)
        assert est["cost_low"] == 8.0
        assert est["cost_high"] == 11.0
