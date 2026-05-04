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
    judge_batch,
    judge_discovery,
    judge_one_id,
    list_by_status,
)


PROFILE = {
    "values": {"security_culture": 0.5, "people_treatment": 0.5},
    "dealbreakers": ["on-site work required"],
    "yellow_flags": ["fast-paced"],
    "green_flags": ["async-first"],
    "target_roles": ["AI red team", "AppSec"],
    "judge": {"ready_threshold": 60},
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
