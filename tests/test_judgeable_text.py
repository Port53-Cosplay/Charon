"""The judgeable predicate: a row that arrived with its own description.

Greenhouse, Lever and Ashby hand over the full posting at gather time, so
most of those rows never need an enrichment fetch. The pickers used to
insist on enrichment_tier anyway, which stranded any row the cull revived
after the last enrichment pass — it showed up as "stuck" forever while
carrying a perfectly readable 6,000-char description.
"""

from charon import dashboard
from charon.db import (
    USABLE_DESCRIPTION_CHARS,
    add_discovery,
    get_connection,
    get_unjudged_discoveries,
    mark_discovery_rejected,
)

LONG = "Security engineer wanted. " * 40  # comfortably over the threshold
SHORT = "Apply on our site."


def _seed(dedupe_hash, *, description=LONG, full_description=None, tier=None):
    new_id = add_discovery(
        ats="greenhouse",
        slug="brex",
        company="Brex",
        role="Systems Analyst II",
        url=f"https://example.com/{dedupe_hash}",
        dedupe_hash=dedupe_hash,
        location="Seattle, Washington, United States",
        description=description,
        posted_at="2026-08-25T12:00:00Z",
        tier="tier_3",
        category="security_product_general",
    )
    sets, params = [], []
    if full_description is not None:
        sets.append("full_description = ?")
        params.append(full_description)
    if tier is not None:
        sets.append("enrichment_tier = ?")
        params.append(tier)
    if sets:
        conn = get_connection()
        try:
            conn.execute(
                f"UPDATE discoveries SET {', '.join(sets)} WHERE id = ?",
                (*params, new_id),
            )
            conn.commit()
        finally:
            conn.close()
    return new_id


class TestJudgePicker:
    def test_gathered_description_is_judgeable_without_enrichment(self):
        rid = _seed("jt-gathered")
        assert len(LONG) >= USABLE_DESCRIPTION_CHARS
        assert rid in [r["id"] for r in get_unjudged_discoveries()]

    def test_short_description_is_not_judgeable(self):
        rid = _seed("jt-short", description=SHORT)
        assert rid not in [r["id"] for r in get_unjudged_discoveries()]

    def test_failed_enrichment_with_gathered_text_is_still_judgeable(self):
        # The fetch failed, but the ATS already gave us the posting — the
        # analyzers fall back to `description`, so there's work to do here.
        rid = _seed("jt-failed", tier="failed")
        assert rid in [r["id"] for r in get_unjudged_discoveries()]

    def test_failed_enrichment_with_no_text_stays_out(self):
        rid = _seed("jt-failed-empty", description="", tier="failed")
        assert rid not in [r["id"] for r in get_unjudged_discoveries()]

    def test_enriched_text_alone_is_enough(self):
        rid = _seed("jt-enriched", description="", full_description=LONG,
                    tier="jsonld")
        assert rid in [r["id"] for r in get_unjudged_discoveries()]

    def test_require_enriched_false_still_takes_everything(self):
        rid = _seed("jt-nothing", description="")
        assert rid in [
            r["id"] for r in get_unjudged_discoveries(require_enriched=False)
        ]


class TestStatsAgree:
    def test_judgeable_count_matches_the_picker(self):
        _seed("jt-s1")
        _seed("jt-s2")
        _seed("jt-s3", description=SHORT)
        expected = len(get_unjudged_discoveries())
        assert dashboard._stats()["judgeable"] == expected
        assert dashboard._count_judgeable() == expected

    def test_row_with_its_own_description_is_not_stuck(self):
        _seed("jt-notstuck")
        assert dashboard._stats()["awaiting_enrich"] == 0

    def test_row_with_no_description_is_stuck(self):
        _seed("jt-stuck", description="")
        assert dashboard._stats()["awaiting_enrich"] == 1

    def test_refused_rows_are_neither_stuck_nor_judgeable(self):
        # mark_discovery_rejected backfills judged_at, which is what keeps a
        # refused row out of the judge picker. Go through the real helper so
        # this test can't pass on a half-state the app never creates.
        mark_discovery_rejected(_seed("jt-rejected", description=""), "not for me")
        mark_discovery_rejected(_seed("jt-rejected-long"), "not for me")
        s = dashboard._stats()
        assert s["awaiting_enrich"] == 0
        assert s["judgeable"] == 0
