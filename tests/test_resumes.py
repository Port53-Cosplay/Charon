"""One résumé resolver for résumé match, forge and petition.

On the portal, profile.resume_path resolved to a May résumé that both curated
résumés had since replaced, so the score, the attached file and the cover
letter could each describe a different document. Everything now routes
through charon.resumes: GRC-type roles get the GRC résumé, the rest get IR.
"""

import json
from pathlib import Path

import pytest

from charon import resumes
from charon import screen


def _profile(**extra):
    base = {
        "values": {"security_culture": 0.5, "people_treatment": 0.5},
        "dealbreakers": [],
        "yellow_flags": [],
        "green_flags": [],
        "target_roles": ["Detection engineer", "IT auditor"],
        "judge": {
            "ready_threshold": 70,
            "alignment_floor": 50,
            "weights": {
                "ghost": 0.12, "redflag": 0.17, "role_alignment": 0.40,
                "resume_match": 0.12, "monoculture": 0.15,
            },
        },
    }
    base.update(extra)
    return base


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestResolution:
    def test_resumes_block_wins(self, tmp_path):
        prof = _profile(
            resumes={"ir": "/r/ir.docx", "grc": "/r/grc.docx"},
            resume_path="/old/resume",
        )
        assert resumes.resume_paths(prof) == {"ir": "/r/ir.docx", "grc": "/r/grc.docx"}

    def test_legacy_resume_path_still_feeds_ir(self):
        # A profile nobody has migrated (Don's fork, say) keeps working.
        paths = resumes.resume_paths(_profile(resume_path="/old/resume"))
        assert paths["ir"] == "/old/resume"
        assert paths["grc"] == "/old/resume"

    def test_legacy_forge_keys_still_resolve(self):
        prof = _profile(forge={"default_resume_md": "/f/ir.md", "grc_resume_md": "/f/grc.md"})
        assert resumes.resume_paths(prof) == {"ir": "/f/ir.md", "grc": "/f/grc.md"}

    @pytest.mark.parametrize("target,kind", [
        ("IT auditor", "grc"),
        ("GRC analyst", "grc"),
        ("  Compliance Auditor ", "grc"),
        ("Detection engineer", "ir"),
        ("", "ir"),
    ])
    def test_routing(self, target, kind):
        assert resumes.kind_for(target, _profile()) == kind

    def test_custom_grc_targets(self):
        prof = _profile(resumes={"grc_targets": ["privacy analyst"]})
        assert resumes.kind_for("Privacy Analyst", prof) == "grc"
        assert resumes.kind_for("IT auditor", prof) == "ir"

    def test_load_all_is_empty_without_a_resumes_block(self, tmp_path):
        ir = _write(tmp_path, "ir.md", "IR resume")
        assert resumes.load_all(_profile(resume_path=str(ir))) == {}

    def test_load_all_reads_both(self, tmp_path):
        ir = _write(tmp_path, "ir.md", "IR resume text")
        grc = _write(tmp_path, "grc.md", "GRC resume text")
        loaded = resumes.load_all(_profile(resumes={"ir": str(ir), "grc": str(grc)}))
        assert loaded == {"ir": "IR resume text", "grc": "GRC resume text"}


class TestJudgeUsesTheRoutedResume:
    def _patch_analyzers(self, monkeypatch, closest_target, seen):
        monkeypatch.setattr(screen, "analyze_ghostbust", lambda text: {"ghost_score": 10})
        monkeypatch.setattr(
            screen, "analyze_redflags",
            lambda text, profile: {"redflag_score": 10, "dealbreakers_found": []},
        )
        monkeypatch.setattr(
            screen, "analyze_role_alignment",
            lambda text, roles: {"alignment_score": 90, "closest_target": closest_target},
        )

        def match(posting, resume_text):
            seen.append(resume_text)
            return {"match_score": 80}

        monkeypatch.setattr(screen, "analyze_resume_match", match)

    def test_audit_posting_is_matched_against_the_grc_resume(self, monkeypatch):
        seen = []
        self._patch_analyzers(monkeypatch, "IT auditor", seen)
        result = screen.judge_discovery(
            {"full_description": "x" * 900},
            profile=_profile(),
            resume_text="OLD MAY RESUME",
            resumes={"ir": "IR TEXT", "grc": "GRC TEXT"},
        )
        assert seen == ["GRC TEXT"]
        assert result["judgement_detail"]["resume_kind"] == "grc"

    def test_ir_posting_is_matched_against_the_ir_resume(self, monkeypatch):
        seen = []
        self._patch_analyzers(monkeypatch, "Detection engineer", seen)
        result = screen.judge_discovery(
            {"full_description": "x" * 900},
            profile=_profile(),
            resumes={"ir": "IR TEXT", "grc": "GRC TEXT"},
        )
        assert seen == ["IR TEXT"]
        assert result["judgement_detail"]["resume_kind"] == "ir"

    def test_without_resumes_the_single_resume_path_is_unchanged(self, monkeypatch):
        seen = []
        self._patch_analyzers(monkeypatch, "IT auditor", seen)
        screen.judge_discovery(
            {"full_description": "x" * 900},
            profile=_profile(),
            resume_text="ONLY RESUME",
        )
        assert seen == ["ONLY RESUME"]


class TestRescore:
    def _seed_ready(self, closest_target="Detection engineer", resume_score=30.0,
                    status="ready", reason="combined 71.0 >= 70"):
        from charon.db import add_discovery, get_connection, update_discovery_judgement

        rid = add_discovery(
            ats="greenhouse", slug="beyondtrust", company="BeyondTrust",
            role="Sr SOC Analyst", url=f"https://example.com/{closest_target}-{status}",
            dedupe_hash=f"rs-{closest_target}-{status}-{resume_score}",
            location="Remote", description="posting " * 200, posted_at=None,
            tier="tier_2", category="security_product_general",
        )
        update_discovery_judgement(
            rid, ghost_score=12, redflag_score=38, alignment_score=92,
            combined_score=77.0, screened_status="ready", judgement_reason=reason,
            judgement_detail={
                "role_alignment": {"closest_target": closest_target},
                "redflags": {"dealbreakers_found": []},
            },
            resume_match_score=resume_score,
        )
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE discoveries SET screened_status = ?, judged_at = ?, "
                "monoculture_score = 35 WHERE id = ?",
                (status, "2026-09-11T20:00:00+00:00", rid),
            )
            conn.commit()
        finally:
            conn.close()
        return rid

    def _files(self, tmp_path):
        ir = _write(tmp_path, "ir.md", "IR resume text")
        grc = _write(tmp_path, "grc.md", "GRC resume text")
        return _profile(resumes={"ir": str(ir), "grc": str(grc)})

    def test_rescore_updates_match_combined_and_keeps_judged_at(self, tmp_path, monkeypatch):
        from charon.db import get_discovery

        rid = self._seed_ready(resume_score=30.0)
        seen = []

        def match(posting, resume_text):
            seen.append(resume_text)
            return {"match_score": 70}

        monkeypatch.setattr(screen, "analyze_resume_match", match)
        out = screen.rescore_resume_batch(profile=self._files(tmp_path), ids=[rid])

        assert seen == ["IR resume text"]
        assert out[0]["old_resume_match"] == 30.0
        assert out[0]["new_resume_match"] == 70.0
        # Recomputed from the stored scores with the new match: ghost 88, redflag 62,
        # alignment 92, resume 70, monoculture 65 under the 0.96-total weights.
        assert out[0]["new_combined"] == 79.2

        row = get_discovery(rid)
        assert row["resume_match_score"] == 70.0
        assert row["combined_score"] == out[0]["new_combined"]
        assert row["judged_at"] == "2026-09-11T20:00:00+00:00"
        detail = json.loads(row["judgement_detail"])
        assert detail["resume_kind"] == "ir"
        assert detail["resume_match"]["match_score"] == 70

    def test_grc_row_is_rescored_against_grc(self, tmp_path, monkeypatch):
        rid = self._seed_ready(closest_target="IT auditor")
        seen = []
        monkeypatch.setattr(
            screen, "analyze_resume_match",
            lambda posting, resume_text: seen.append(resume_text) or {"match_score": 60},
        )
        screen.rescore_resume_batch(profile=self._files(tmp_path), ids=[rid])
        assert seen == ["GRC resume text"]

    def test_applied_and_manually_refused_rows_are_never_touched(self, tmp_path, monkeypatch):
        applied = self._seed_ready(status="applied", resume_score=11.0)
        manual = self._seed_ready(
            status="rejected", resume_score=12.0,
            reason="Manually refused — not interested",
        )
        calls = []
        monkeypatch.setattr(
            screen, "analyze_resume_match",
            lambda *a: calls.append(a) or {"match_score": 99},
        )
        out = screen.rescore_resume_batch(
            profile=self._files(tmp_path), ids=[applied, manual]
        )
        assert out == []
        assert calls == []

    def test_a_failed_call_leaves_the_row_alone(self, tmp_path, monkeypatch):
        from charon.ai import AIError
        from charon.db import get_discovery

        rid = self._seed_ready(resume_score=30.0)

        def boom(*a):
            raise AIError("rate limited")

        monkeypatch.setattr(screen, "analyze_resume_match", boom)
        out = screen.rescore_resume_batch(profile=self._files(tmp_path), ids=[rid])
        assert out[0]["error"] == "rate limited"
        assert get_discovery(rid)["resume_match_score"] == 30.0


class TestPetitionUsesTheRoutedResume:
    def test_unconfigured_grc_resume_names_the_right_key(self, tmp_path):
        from charon.letter import petition_discovery

        d = {
            "id": 7, "company": "Schellman", "role": "Senior IT Auditor",
            "screened_status": "ready", "full_description": "audit " * 200,
            "judgement_detail": json.dumps(
                {"role_alignment": {"closest_target": "IT auditor"}}
            ),
        }
        prof = _profile(forge={"offerings_dir": str(tmp_path)})
        result = petition_discovery(d, profile=prof)
        assert "No GRC resume configured" in result["error"]
        assert "profile.resumes.grc" in result["error"]


class TestOfferingFileChoice:
    def test_prefers_rendered_html_then_finished_documents(self, tmp_path):
        from charon.dashboard import _offering_file

        assert _offering_file(str(tmp_path), "resume") is None
        (tmp_path / "resume.docx").write_bytes(b"PK")
        assert _offering_file(str(tmp_path), "resume") == "resume.docx"
        (tmp_path / "resume.html").write_text("<html></html>", encoding="utf-8")
        assert _offering_file(str(tmp_path), "resume") == "resume.html"


class TestRescoreEndpointGuards:
    def test_needs_ids_or_a_valid_status(self):
        from charon.dashboard import DashboardError, _rescore_resume
        with pytest.raises(DashboardError):
            _rescore_resume(None, None)
        with pytest.raises(DashboardError):
            _rescore_resume(None, "applied")

    def test_refuses_oversized_id_lists(self):
        from charon.dashboard import DashboardError, _rescore_resume
        with pytest.raises(DashboardError, match="At most"):
            _rescore_resume(list(range(500)), None)
