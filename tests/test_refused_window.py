"""The Refused tab's recency window.

Ordering every refusal ever by score turns the tab into an all-time hall of
fame: the best posting Charon has ever seen sits on top permanently. It's
also a bad comparison, since the board mix behind the pool changes, so a
score from four months ago and one from last week aren't measuring the same
market. The window keeps the view to recent judgements.
"""

from datetime import datetime, timedelta, timezone

from charon import dashboard
from charon.db import (
    add_discovery,
    get_connection,
    get_discoveries,
    update_discovery_judgement,
)


def _seed_refused(dedupe_hash, *, days_ago, score=60.0):
    new_id = add_discovery(
        ats="greenhouse",
        slug="vanta",
        company="Vanta",
        role="Senior Security Operations Analyst",
        url=f"https://example.com/{dedupe_hash}",
        dedupe_hash=dedupe_hash,
        location="Remote",
        description="A real posting, at length. " * 30,
        posted_at="2026-05-14T12:00:00Z",
        tier="tier_3",
        category="security_product_general",
    )
    update_discovery_judgement(
        new_id,
        ghost_score=10,
        redflag_score=10,
        alignment_score=40,
        combined_score=score,
        screened_status="rejected",
        judgement_reason=f"combined {score} < 70",
    )
    judged_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE discoveries SET judged_at = ? WHERE id = ?", (judged_at, new_id)
        )
        conn.commit()
    finally:
        conn.close()
    return new_id


class TestWindowFilter:
    def test_default_window_hides_the_old_high_scorer(self):
        # The exact situation: a four-month-old near-miss outscoring
        # everything recent, pinned to the top of the tab forever.
        _seed_refused("rw-old", days_ago=120, score=77.5)
        _seed_refused("rw-new", days_ago=3, score=61.0)
        shown = dashboard._refused_discoveries()
        assert [r["company"] for r in shown] == ["Vanta"]
        assert len(shown) == 1
        assert shown[0]["combined_score"] == 61.0

    def test_all_time_still_shows_everything(self):
        _seed_refused("rw-old2", days_ago=120, score=77.5)
        _seed_refused("rw-new2", days_ago=3, score=61.0)
        shown = dashboard._refused_discoveries(days=None)
        assert len(shown) == 2
        # Still score-ordered within the window.
        assert shown[0]["combined_score"] == 77.5

    def test_ninety_day_window_is_between(self):
        _seed_refused("rw-120", days_ago=120)
        _seed_refused("rw-60", days_ago=60)
        _seed_refused("rw-3", days_ago=3)
        assert len(dashboard._refused_discoveries(days=30)) == 1
        assert len(dashboard._refused_discoveries(days=90)) == 2
        assert len(dashboard._refused_discoveries(days=None)) == 3

    def test_boundary_row_just_inside_the_window(self):
        _seed_refused("rw-edge", days_ago=29)
        assert len(dashboard._refused_discoveries(days=30)) == 1


class TestCounts:
    def test_count_tracks_the_window(self):
        _seed_refused("rc-old", days_ago=120)
        _seed_refused("rc-new", days_ago=3)
        assert dashboard._count_refused(30) == 1
        assert dashboard._count_refused(None) == 2

    def test_window_does_not_touch_the_refused_stat(self):
        # The stats band counts every refusal — archiving a view is not
        # deleting data, and the lifetime figure should not move.
        _seed_refused("rs-old", days_ago=120)
        _seed_refused("rs-new", days_ago=3)
        assert dashboard._stats()["refused"] == 2


class TestGetDiscoveriesFilter:
    def test_judged_since_is_parameterized_and_filters(self):
        _seed_refused("gd-old", days_ago=120)
        recent = _seed_refused("gd-new", days_ago=1)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        rows = get_discoveries(status="rejected", judged_since=cutoff)
        assert [r["id"] for r in rows] == [recent]

    def test_no_filter_returns_both(self):
        _seed_refused("gd-old2", days_ago=120)
        _seed_refused("gd-new2", days_ago=1)
        assert len(get_discoveries(status="rejected")) == 2
