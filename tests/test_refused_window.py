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


class TestPayloadSize:
    """The Refused list shipped whole job descriptions for 200 rows — 4.2MB
    per window switch. List views now send a preview and serve the rest from
    /api/description/<id>."""

    def _seed_with_text(self, dedupe_hash, chars):
        rid = _seed_refused(dedupe_hash, days_ago=2)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE discoveries SET full_description = ? WHERE id = ?",
                ("y" * chars, rid),
            )
            conn.commit()
        finally:
            conn.close()
        return rid

    def test_long_posting_is_truncated_with_a_flag(self):
        self._seed_with_text("pl-long", 20000)
        row = dashboard._refused_discoveries()[0]
        assert row["description_truncated"] is True
        assert len(row["full_description"]) == dashboard.DESCRIPTION_PREVIEW_CHARS
        assert row["description_chars"] == 20000

    def test_short_posting_is_sent_whole(self):
        self._seed_with_text("pl-short", 120)
        row = dashboard._refused_discoveries()[0]
        assert row["description_truncated"] is False
        assert len(row["full_description"]) == 120

    def test_uncapped_callers_still_get_everything(self):
        # The Ready tab shows a couple of rows; it has no reason to truncate.
        from charon.db import get_discovery
        rid = self._seed_with_text("pl-full", 20000)
        row = dashboard._summarize_discovery(get_discovery(rid))
        assert row["description_truncated"] is False
        assert len(row["full_description"]) == 20000

    def test_preview_is_a_prefix_of_the_real_text(self):
        rid = self._seed_with_text("pl-prefix", 5000)
        from charon.db import get_discovery
        full = get_discovery(rid)["full_description"]
        row = dashboard._refused_discoveries()[0]
        assert full.startswith(row["full_description"])


class TestDeferredDigest:
    """judgement_digest was 94% of the Refused payload (~13KB a row). List
    views leave it out; /api/detail/<id> serves it when a card opens."""

    def _seed_with_digest(self, dedupe_hash):
        import json
        rid = _seed_refused(dedupe_hash, days_ago=2)
        detail = {
            "redflags": {
                "dealbreakers_found": [
                    {"flag": "on-site", "evidence": "x" * 400,
                     "interpretation": "y" * 400},
                ],
            },
            "ghostbust": {"summary": "z" * 400, "signals": []},
        }
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE discoveries SET judgement_detail = ? WHERE id = ?",
                (json.dumps(detail), rid),
            )
            conn.commit()
        finally:
            conn.close()
        return rid

    def test_list_payload_omits_the_digest(self):
        self._seed_with_digest("dd-list")
        row = dashboard._refused_discoveries()[0]
        assert row["judgement_digest"] is None
        assert row["digest_deferred"] is True

    def test_uncapped_callers_keep_it(self):
        from charon.db import get_discovery
        rid = self._seed_with_digest("dd-full")
        row = dashboard._summarize_discovery(get_discovery(rid))
        assert row["digest_deferred"] is False
        assert row["judgement_digest"] is not None
        assert row["judgement_digest"]["redflags"]["dealbreakers"]

    def test_analyzer_text_never_reaches_the_list_payload(self):
        import json
        for i in range(5):
            self._seed_with_digest(f"dd-size-{i}")
        listed = json.dumps(dashboard._refused_discoveries())
        # The evidence and interpretation strings are the bulk of a digest.
        assert "x" * 400 not in listed
        assert "y" * 400 not in listed

        from charon.db import get_discoveries
        rows = [r for r in get_discoveries(status="rejected") if r.get("judged_at")]
        whole = json.dumps([dashboard._summarize_discovery(r) for r in rows])
        assert len(listed) < len(whole)
