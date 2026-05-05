"""Tests for the judge orchestrator (charon/screen.py)."""

import json

import pytest

from charon import screen
from charon.ai import AIError
from charon.db import (
    add_discovery,
    get_discovery,
    get_judged_counts,
    update_discovery_enrichment,
)
from charon.screen import (
    JudgeError,
    compute_combined,
    compute_combined_weighted,
    judge_batch,
    judge_discovery,
    judge_one_id,
    list_by_status,
    reclassify_batch,
    reclassify_one,
)


PROFILE = {
    "values": {"security_culture": 0.5, "people_treatment": 0.5},
    "dealbreakers": ["on-site work required"],
    "yellow_flags": ["fast-paced"],
    "green_flags": ["async-first"],
    "target_roles": ["AI red team", "AppSec"],
    "judge": {"ready_threshold": 60, "alignment_floor": 50},
}


def _seed_enriched(**overrides):
    defaults = dict(
        ats="workday",
        slug="schellman",
        company="Schellman",
        role="Senior IT Auditor",
        url=overrides.pop("url", f"https://schellman.wd1.myworkdayjobs.com/Careers/job/x/y_R{id(overrides)}"),
        dedupe_hash=overrides.pop("dedupe_hash", f"hash-{id(overrides)}"),
        location="Remote",
        description="",
        posted_at="Posted Today",
        tier="tier_1",
        category="audit",
    )
    full_desc = overrides.pop("full_description", "x" * 1500)
    defaults.update(overrides)
    new_id = add_discovery(**defaults)
    if full_desc:
        update_discovery_enrichment(new_id, "jsonld", full_desc)
    return new_id


def _patch_analyzers(monkeypatch, ghost=20, redflag=15, alignment=80):
    """Patch the three analyzers to deterministic stub results."""
    monkeypatch.setattr(screen, "analyze_ghostbust", lambda text: {
        "ghost_score": ghost,
        "confidence": "high",
        "signals": [{"category": "test", "severity": "green", "finding": "ok"}],
        "summary": f"ghost={ghost}",
    })
    monkeypatch.setattr(screen, "analyze_redflags", lambda text, profile: {
        "redflag_score": redflag,
        "confidence": "high",
        "dealbreakers_found": [],
        "yellow_flags_found": [],
        "green_flags_found": [{"flag": "async", "evidence": "x"}],
        "summary": f"redflag={redflag}",
    })
    monkeypatch.setattr(screen, "analyze_role_alignment", lambda text, target_roles: {
        "alignment_score": alignment,
        "closest_target": "AI red team",
        "overlap": ["EDR"],
        "gaps": [],
        "stepping_stone": False,
        "assessment": f"align={alignment}",
    })


# ── combined-score formula ──────────────────────────────────────────


class TestComputeCombined:
    def test_perfect_scores(self):
        # ghost=0, redflag=0, alignment=100 => combined=100
        assert compute_combined(0, 0, 100) == 100.0

    def test_worst_scores(self):
        # ghost=100, redflag=100, alignment=0 => combined=0
        assert compute_combined(100, 100, 0) == 0.0

    def test_mid_scores(self):
        # ghost=20 (good), redflag=15 (good), alignment=80 (good)
        # = (80 + 85 + 80) / 3 = 81.67
        assert compute_combined(20, 15, 80) == pytest.approx(81.7, abs=0.1)

    def test_clamps_to_100(self):
        assert compute_combined(-50, -50, 200) <= 100.0

    def test_clamps_to_zero(self):
        assert compute_combined(200, 200, -50) >= 0.0


# ── judge_discovery ──────────────────────────────────────────────────


class TestJudgeDiscovery:
    def test_passes_above_threshold(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=90)
        # combined = (90+90+90)/3 = 90
        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=PROFILE)
        assert result["screened_status"] == "ready"
        assert result["combined_score"] == 90.0
        assert "ready" not in result["judgement_reason"].lower()  # reason just describes math

    def test_fails_below_threshold(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=80, redflag=80, alignment=20)
        # combined = (20+20+20)/3 = 20
        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=PROFILE)
        assert result["screened_status"] == "rejected"
        assert result["combined_score"] == 20.0

    def test_uses_full_description_over_description(self, monkeypatch):
        captured = {"text": None}
        def capture(text):
            captured["text"] = text
            return {"ghost_score": 0, "confidence": "high", "signals": [], "summary": ""}
        monkeypatch.setattr(screen, "analyze_ghostbust", capture)
        monkeypatch.setattr(screen, "analyze_redflags", lambda t, p: {
            "redflag_score": 0, "confidence": "high",
            "dealbreakers_found": [], "yellow_flags_found": [], "green_flags_found": [],
            "summary": "",
        })
        monkeypatch.setattr(screen, "analyze_role_alignment", lambda t, r: {"alignment_score": 80})

        d = {
            "description": "short fallback",
            "full_description": "x" * 500 + "FULL_TEXT_MARKER",
        }
        judge_discovery(d, profile=PROFILE)
        assert "FULL_TEXT_MARKER" in captured["text"]

    def test_no_description_returns_no_text_error(self, monkeypatch):
        # Should not call any analyzer
        called = {"n": 0}
        def boom(*a, **kw):
            called["n"] += 1
            return {}
        monkeypatch.setattr(screen, "analyze_ghostbust", boom)

        d = {"description": "", "full_description": ""}
        result = judge_discovery(d, profile=PROFILE)
        assert result["screened_status"] == "rejected"
        assert "no usable description" in result["judgement_reason"]
        assert called["n"] == 0

    def test_ai_error_marks_rejected(self, monkeypatch):
        def boom(text):
            raise AIError("oracle silent")
        monkeypatch.setattr(screen, "analyze_ghostbust", boom)

        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=PROFILE)
        assert result["screened_status"] == "rejected"
        assert "AI error" in result["judgement_reason"]

    def test_no_target_roles_skips_role_alignment(self, monkeypatch):
        called = {"n": 0}
        def boom(text, target_roles):
            called["n"] += 1
            return {}
        monkeypatch.setattr(screen, "analyze_role_alignment", boom)
        monkeypatch.setattr(screen, "analyze_ghostbust", lambda t: {
            "ghost_score": 10, "confidence": "high", "signals": [], "summary": ""
        })
        monkeypatch.setattr(screen, "analyze_redflags", lambda t, p: {
            "redflag_score": 10, "confidence": "high",
            "dealbreakers_found": [], "yellow_flags_found": [], "green_flags_found": [],
            "summary": "",
        })

        profile_no_roles = dict(PROFILE)
        profile_no_roles["target_roles"] = []

        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=profile_no_roles)
        # Default 50 alignment score when not invoked
        assert result["alignment_score"] == 50
        assert called["n"] == 0

    def test_threshold_override(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=40, redflag=40, alignment=60)
        # combined = (60+60+60)/3 = 60
        d = {"full_description": "x" * 500}

        # Default profile threshold = 60, so combined=60 passes
        result_default = judge_discovery(d, profile=PROFILE)
        assert result_default["screened_status"] == "ready"

        # Override to 75 — combined=60 fails
        result_strict = judge_discovery(d, profile=PROFILE, threshold=75)
        assert result_strict["screened_status"] == "rejected"


# ── judge_one_id (DB writes) ────────────────────────────────────────


class TestJudgeOneId:
    def test_writes_results_to_db(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=20, alignment=85)
        new_id = _seed_enriched(dedupe_hash="j-1")

        result = judge_one_id(new_id, profile=PROFILE)
        assert result["screened_status"] == "ready"

        row = get_discovery(new_id)
        assert row["judged_at"] is not None
        assert row["screened_status"] == "ready"
        assert row["combined_score"] == result["combined_score"]
        # judgement_detail stored as JSON
        detail = json.loads(row["judgement_detail"])
        assert "ghostbust" in detail
        assert "redflags" in detail
        assert "role_alignment" in detail

    def test_unknown_id_raises(self):
        with pytest.raises(JudgeError, match="No discovery"):
            judge_one_id(99999, profile=PROFILE)

    def test_skips_already_judged(self, monkeypatch):
        _patch_analyzers(monkeypatch)
        new_id = _seed_enriched(dedupe_hash="j-skip")
        judge_one_id(new_id, profile=PROFILE)  # first run

        # Second run should NOT call analyzers again
        called = {"n": 0}
        def boom(*a, **kw):
            called["n"] += 1
            return {}
        monkeypatch.setattr(screen, "analyze_ghostbust", boom)

        result = judge_one_id(new_id, profile=PROFILE)
        assert "already judged" in (result.get("skipped_reason") or "")
        assert called["n"] == 0

    def test_rejudge_overrides(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=90)
        new_id = _seed_enriched(dedupe_hash="j-rj")
        judge_one_id(new_id, profile=PROFILE)

        # Change scores, force re-judge
        _patch_analyzers(monkeypatch, ghost=80, redflag=80, alignment=20)
        result = judge_one_id(new_id, profile=PROFILE, rejudge=True)
        assert result["screened_status"] == "rejected"
        assert result["combined_score"] < 30

    def test_no_description_does_not_write(self, monkeypatch):
        # Seed an UN-enriched discovery (full_description is None / empty)
        new_id = add_discovery(
            ats="workday", slug="x", company="X", role="Y",
            url="https://x.wd1.myworkdayjobs.com/Careers/job/a/b_R1",
            dedupe_hash="no-desc-1",
        )

        result = judge_one_id(new_id, profile=PROFILE)
        # Should report the no-description state without writing judgement
        assert "no usable description" in (result.get("judgement_reason") or "")

        row = get_discovery(new_id)
        assert row["judged_at"] is None  # Not written to DB


# ── batch ────────────────────────────────────────────────────────────


class TestJudgeBatch:
    def test_only_unjudged_by_default(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=90)
        a = _seed_enriched(dedupe_hash="b-a")
        b = _seed_enriched(dedupe_hash="b-b", url="https://x.wd1.myworkdayjobs.com/x/y")

        # Pre-judge a so only b should be processed
        judge_one_id(a, profile=PROFILE)

        # Track calls
        call_log = []
        def track(text):
            call_log.append(text[:20])
            return {"ghost_score": 10, "confidence": "high", "signals": [], "summary": ""}
        monkeypatch.setattr(screen, "analyze_ghostbust", track)

        results = judge_batch(profile=PROFILE)
        assert len(results) == 1
        assert results[0]["discovery_id"] == b

    def test_filter_by_ats(self, monkeypatch):
        _patch_analyzers(monkeypatch)
        wd = _seed_enriched(dedupe_hash="bf-wd")
        gh = _seed_enriched(
            ats="greenhouse", slug="example", company="Example Co",
            url="https://boards.greenhouse.io/example/jobs/1",
            dedupe_hash="bf-gh",
        )
        results = judge_batch(ats="workday", profile=PROFILE)
        assert all(r["discovery_id"] == wd for r in results)

    def test_rejudge_with_status_ready_filter(self, monkeypatch):
        # Seed three discoveries; pre-judge so each gets a different status
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=90)  # ready
        a = _seed_enriched(dedupe_hash="sf-a")
        judge_one_id(a, profile=PROFILE)
        assert get_discovery(a)["screened_status"] == "ready"

        _patch_analyzers(monkeypatch, ghost=85, redflag=85, alignment=10)  # rejected (alignment floor)
        b = _seed_enriched(dedupe_hash="sf-b",
                           url="https://x.wd1.myworkdayjobs.com/x/y/2")
        judge_one_id(b, profile=PROFILE)
        assert get_discovery(b)["screened_status"] == "rejected"

        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=90)  # ready
        c = _seed_enriched(dedupe_hash="sf-c",
                           url="https://x.wd1.myworkdayjobs.com/x/y/3")
        judge_one_id(c, profile=PROFILE)
        assert get_discovery(c)["screened_status"] == "ready"

        # Track which IDs the analyzers see during rejudge
        seen_ids = []
        original = screen.analyze_ghostbust
        def track(text):
            seen_ids.append(text[:20])  # crude per-call marker
            return original(text)
        # Re-stub with a tracker
        _patch_analyzers(monkeypatch, ghost=20, redflag=20, alignment=85)
        original = screen.analyze_ghostbust
        def with_tracking(text):
            seen_ids.append("called")
            return original(text)
        monkeypatch.setattr(screen, "analyze_ghostbust", with_tracking)

        # Rejudge ONLY the ready ones (a and c), skip the rejected (b)
        results = judge_batch(profile=PROFILE, rejudge=True, status="ready")

        assert len(results) == 2
        result_ids = {r["discovery_id"] for r in results}
        assert a in result_ids
        assert c in result_ids
        assert b not in result_ids
        # ghostbust should have been called exactly twice (once per ready row)
        assert len(seen_ids) == 2

    def test_rejudge_picks_up_judged(self, monkeypatch):
        _patch_analyzers(monkeypatch)
        a = _seed_enriched(dedupe_hash="rj-a")
        judge_one_id(a, profile=PROFILE)

        results = judge_batch(profile=PROFILE, rejudge=True, limit=1)
        assert any(r["discovery_id"] == a for r in results)


# ── list_by_status ──────────────────────────────────────────────────


class TestListByStatus:
    def test_lists_ready(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=5, redflag=5, alignment=95)
        new_id = _seed_enriched(dedupe_hash="ls-r")
        judge_one_id(new_id, profile=PROFILE)

        rows = list_by_status("ready")
        ids = [r["id"] for r in rows]
        assert new_id in ids

    def test_lists_rejected(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=80, redflag=80, alignment=10)
        new_id = _seed_enriched(dedupe_hash="ls-rej")
        judge_one_id(new_id, profile=PROFILE)

        rows = list_by_status("rejected")
        ids = [r["id"] for r in rows]
        assert new_id in ids

    def test_excludes_unjudged(self, monkeypatch):
        # Seed an enriched but unjudged discovery
        new_id = _seed_enriched(dedupe_hash="ls-un")

        rows = list_by_status("rejected")
        # Even though screened_status defaults to 'new', list_by_status
        # filters to judged-only — so this row must NOT appear
        assert new_id not in [r["id"] for r in rows]

    def test_invalid_status_raises(self):
        with pytest.raises(JudgeError, match="status must be"):
            list_by_status("nonsense")


# ── stats ────────────────────────────────────────────────────────────


class TestAlignmentFloor:
    def test_low_alignment_rejected_even_when_combined_passes(self, monkeypatch):
        # ghost=10, redflag=20, alignment=25
        # combined = (90+80+25)/3 = 65 → above 60 threshold
        # but alignment 25 < floor 50 → rejected
        _patch_analyzers(monkeypatch, ghost=10, redflag=20, alignment=25)
        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=PROFILE)
        assert result["screened_status"] == "rejected"
        assert "alignment 25 < floor 50" in result["judgement_reason"]

    def test_alignment_at_floor_passes_through_combined_check(self, monkeypatch):
        # alignment=50 (at floor), combined = (90+80+50)/3 = 73.3 → ready
        _patch_analyzers(monkeypatch, ghost=10, redflag=20, alignment=50)
        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=PROFILE)
        assert result["screened_status"] == "ready"

    def test_floor_override_via_profile(self, monkeypatch):
        # floor=70, alignment=65 → rejected even though combined would pass
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=65)
        # combined = (90+90+65)/3 = 81.7 — well above 60
        strict_profile = dict(PROFILE)
        strict_profile["judge"] = dict(PROFILE["judge"])
        strict_profile["judge"]["alignment_floor"] = 70

        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=strict_profile)
        assert result["screened_status"] == "rejected"
        assert "floor 70" in result["judgement_reason"]


class TestReclassify:
    def test_reclassify_changes_status_after_floor_change(self, monkeypatch):
        """Old run let alignment=25 ready through (no floor); new floor rejects it."""
        # Seed without the floor in the scenario
        no_floor_profile = dict(PROFILE)
        no_floor_profile["judge"] = {"ready_threshold": 60, "alignment_floor": 0}

        _patch_analyzers(monkeypatch, ghost=10, redflag=20, alignment=25)
        new_id = _seed_enriched(dedupe_hash="rc-1")
        judge_one_id(new_id, profile=no_floor_profile)

        row = get_discovery(new_id)
        assert row["screened_status"] == "ready"  # passed without floor

        # Now apply a stricter profile (floor=50) and reclassify
        new = reclassify_one(row, profile=PROFILE)  # floor=50
        assert new is not None
        assert new["screened_status"] == "rejected"
        assert "floor 50" in new["judgement_reason"]

    def test_reclassify_preserves_judgement_detail(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=85)
        new_id = _seed_enriched(dedupe_hash="rc-2")
        judge_one_id(new_id, profile=PROFILE)

        row_before = get_discovery(new_id)
        detail_before = row_before["judgement_detail"]
        assert detail_before is not None  # full analyzer JSON written

        # Reclassify with a tougher floor — should change status
        strict_profile = dict(PROFILE)
        strict_profile["judge"] = {"ready_threshold": 60, "alignment_floor": 90}
        reclassify_batch(profile=strict_profile)

        row_after = get_discovery(new_id)
        # Detail must NOT have been clobbered to NULL
        assert row_after["judgement_detail"] == detail_before
        # But status should reflect the new floor
        assert row_after["screened_status"] == "rejected"

    def test_reclassify_no_ai_calls(self, monkeypatch):
        """reclassify_batch must not call any analyzer."""
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=80)
        new_id = _seed_enriched(dedupe_hash="rc-3")
        judge_one_id(new_id, profile=PROFILE)

        # Replace analyzers with bombs
        def boom(*a, **kw):
            raise AssertionError("reclassify must not call analyzers")
        monkeypatch.setattr(screen, "analyze_ghostbust", boom)
        monkeypatch.setattr(screen, "analyze_redflags", boom)
        monkeypatch.setattr(screen, "analyze_role_alignment", boom)

        # Run reclassify — must not raise
        results = reclassify_batch(profile=PROFILE)
        assert any(r["discovery_id"] == new_id for r in results)

    def test_reclassify_skips_unjudged(self, monkeypatch):
        new_id = _seed_enriched(dedupe_hash="rc-4")
        # Don't judge — leave unjudged
        results = reclassify_batch(profile=PROFILE)
        assert all(r["discovery_id"] != new_id for r in results)

    def test_reclassify_threshold_override(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=20, redflag=20, alignment=70)
        # combined = (80+80+70)/3 = 76.7 — passes default threshold 60
        new_id = _seed_enriched(dedupe_hash="rc-5")
        judge_one_id(new_id, profile=PROFILE)
        assert get_discovery(new_id)["screened_status"] == "ready"

        # Tighten threshold to 80 — should now flip to rejected
        reclassify_batch(profile=PROFILE, threshold=80)
        assert get_discovery(new_id)["screened_status"] == "rejected"


class TestComputeCombinedWeighted:
    def test_three_components_no_weights_equal_to_old_formula(self):
        # Without weights, falls back to equal averaging across given components
        old = compute_combined(20, 15, 80)
        new = compute_combined_weighted(
            ghost=20, redflag=15, alignment=80, resume_match=None, weights=None,
        )
        assert old == new

    def test_four_components_no_weights_average(self):
        # ghost=20, redflag=15, alignment=80, resume_match=70
        # = (80 + 85 + 80 + 70) / 4 = 78.75
        result = compute_combined_weighted(
            ghost=20, redflag=15, alignment=80, resume_match=70, weights=None,
        )
        assert result == pytest.approx(78.8, abs=0.1)

    def test_weights_shift_score(self):
        # Heavily weight resume_match; resume_match=20 should drag combined down
        weights = {"ghost": 0.0, "redflag": 0.0, "role_alignment": 0.1, "resume_match": 0.9}
        # Components: g=100-20=80, r=100-15=85, a=80, rm=20
        # weighted: (0*80 + 0*85 + 0.1*80 + 0.9*20) / 1.0 = 26
        result = compute_combined_weighted(
            ghost=20, redflag=15, alignment=80, resume_match=20, weights=weights,
        )
        assert result == pytest.approx(26.0, abs=0.1)

    def test_zero_weights_falls_back_to_equal(self):
        # All zero weights → equal weighting fallback
        weights = {"ghost": 0.0, "redflag": 0.0, "role_alignment": 0.0, "resume_match": 0.0}
        result = compute_combined_weighted(
            ghost=0, redflag=0, alignment=100, resume_match=100, weights=weights,
        )
        # Should fall back to equal: (100+100+100+100)/4 = 100
        assert result == 100.0

    def test_legacy_row_no_resume_match_uses_three_components(self):
        weights = {"ghost": 0.15, "redflag": 0.20, "role_alignment": 0.25, "resume_match": 0.40}
        # resume_match=None → only the first three weights apply
        # Components: g=100-20=80, r=100-15=85, a=80
        # active weights: 0.15, 0.20, 0.25 (sum=0.60)
        # weighted: (0.15*80 + 0.20*85 + 0.25*80) / 0.60
        # = (12 + 17 + 20) / 0.60 = 49/0.60 = 81.67
        result = compute_combined_weighted(
            ghost=20, redflag=15, alignment=80, resume_match=None, weights=weights,
        )
        assert result == pytest.approx(81.7, abs=0.1)


class TestResumeMatchIntegration:
    def test_judge_discovery_calls_resume_analyzer_when_text_passed(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=80)
        captured = {}

        def fake_resume(posting, resume):
            captured["posting"] = posting[:30]
            captured["resume"] = resume[:30]
            return {
                "match_score": 65,
                "confidence": "medium",
                "match_type": "adjacent",
                "overlap": ["EDR experience"],
                "gaps": ["No AI/ML"],
                "transferable": [],
                "summary": "Adjacent fit.",
            }
        monkeypatch.setattr(screen, "analyze_resume_match", fake_resume)

        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=PROFILE, resume_text="MY RESUME TEXT")

        assert result["resume_match_score"] == 65.0
        assert "MY RESUME" in captured["resume"]
        # Detail should include resume_match block
        assert "resume_match" in result["judgement_detail"]

    def test_judge_discovery_skips_resume_when_text_none(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=80)

        def boom(*a, **kw):
            raise AssertionError("resume analyzer should not run when resume_text is None")
        monkeypatch.setattr(screen, "analyze_resume_match", boom)

        d = {"full_description": "x" * 500}
        result = judge_discovery(d, profile=PROFILE, resume_text=None)
        assert result["resume_match_score"] is None
        assert "resume_match" not in (result["judgement_detail"] or {})

    def test_judge_batch_loads_resume_once(self, tmp_path, monkeypatch):
        # Write a fake resume file
        resume_file = tmp_path / "r.md"
        resume_file.write_text("# Test Resume\n\nSecurity Analyst, 5 years EDR.", encoding="utf-8")

        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=80)

        load_count = {"n": 0}
        original_load = screen.load_resume_text

        def counting_load(path):
            load_count["n"] += 1
            return original_load(path)
        monkeypatch.setattr(screen, "load_resume_text", counting_load)

        analyze_count = {"n": 0}
        def fake_resume(posting, resume):
            analyze_count["n"] += 1
            return {
                "match_score": 70, "confidence": "high", "match_type": "adjacent",
                "overlap": [], "gaps": [], "transferable": [], "summary": "x",
            }
        monkeypatch.setattr(screen, "analyze_resume_match", fake_resume)

        # Seed two enriched discoveries
        a = _seed_enriched(dedupe_hash="rm-batch-1")
        b = _seed_enriched(dedupe_hash="rm-batch-2",
                           url="https://x.wd1.myworkdayjobs.com/x/y/2")

        profile_with_resume = dict(PROFILE)
        profile_with_resume["resume_path"] = str(resume_file)

        judge_batch(profile=profile_with_resume)

        # Resume loaded ONCE for the batch, analyzer called per discovery
        assert load_count["n"] == 1
        assert analyze_count["n"] == 2

    def test_judge_batch_no_resume_path_skips_loading(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=80)

        def boom_load(path):
            raise AssertionError("load_resume_text should not be called when resume_path is empty")
        monkeypatch.setattr(screen, "load_resume_text", boom_load)

        def boom_analyze(*a, **kw):
            raise AssertionError("analyze_resume_match should not be called")
        monkeypatch.setattr(screen, "analyze_resume_match", boom_analyze)

        new_id = _seed_enriched(dedupe_hash="no-resume-1")
        # PROFILE has no resume_path → batch must not attempt to load
        results = judge_batch(profile=PROFILE)
        assert len(results) >= 1


class TestKeyboardInterruptPropagates:
    """Ctrl+C must abort the batch loop — not get swallowed as an AIError
    that marks one row rejected and moves on. Regression test for the bug
    where ai.py converted KeyboardInterrupt into AIError."""

    def test_keyboard_interrupt_propagates_through_judge_discovery(self, monkeypatch):
        def cancel(text):
            raise KeyboardInterrupt
        monkeypatch.setattr(screen, "analyze_ghostbust", cancel)
        # Other analyzers shouldn't be reached
        def boom(*a, **kw):
            raise AssertionError("Should not be reached after KeyboardInterrupt")
        monkeypatch.setattr(screen, "analyze_redflags", boom)
        monkeypatch.setattr(screen, "analyze_role_alignment", boom)

        d = {"full_description": "x" * 500}
        with pytest.raises(KeyboardInterrupt):
            judge_discovery(d, profile=PROFILE)

    def test_keyboard_interrupt_aborts_batch(self, monkeypatch):
        # Two enriched rows; first call raises KeyboardInterrupt
        a = _seed_enriched(dedupe_hash="ki-a")
        b = _seed_enriched(dedupe_hash="ki-b",
                           url="https://x.wd1.myworkdayjobs.com/x/y/2")

        call_count = {"n": 0}
        def maybe_cancel(text):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise KeyboardInterrupt
            return {"ghost_score": 0, "confidence": "high", "signals": [], "summary": ""}
        monkeypatch.setattr(screen, "analyze_ghostbust", maybe_cancel)
        monkeypatch.setattr(screen, "analyze_redflags", lambda t, p: {
            "redflag_score": 0, "confidence": "high",
            "dealbreakers_found": [], "yellow_flags_found": [], "green_flags_found": [],
            "summary": "",
        })
        monkeypatch.setattr(screen, "analyze_role_alignment", lambda t, r: {"alignment_score": 80})

        with pytest.raises(KeyboardInterrupt):
            judge_batch(profile=PROFILE)

        # Only the first analyzer call should have happened — the loop
        # must NOT have advanced to the second row
        assert call_count["n"] == 1


class TestStats:
    def test_counts_by_status(self, monkeypatch):
        _patch_analyzers(monkeypatch, ghost=10, redflag=10, alignment=90)
        a = _seed_enriched(dedupe_hash="st-a")
        judge_one_id(a, profile=PROFILE)

        _patch_analyzers(monkeypatch, ghost=80, redflag=80, alignment=10)
        b = _seed_enriched(dedupe_hash="st-b", url="https://x.wd1.myworkdayjobs.com/x/y/2")
        judge_one_id(b, profile=PROFILE)

        counts = get_judged_counts()
        assert counts.get("ready") == 1
        assert counts.get("rejected") == 1
