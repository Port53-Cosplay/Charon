"""Tests for charon/tailor.py — forge logic, slugification, verifier, model routing."""

from pathlib import Path

import pytest

from charon import tailor
from charon.tailor import (
    ForgeError,
    forge_discovery,
    offerings_folder,
    slugify,
    verify_against_source,
)


# ── slugification ───────────────────────────────────────────────────


class TestSlugify:
    def test_basic(self):
        assert slugify("Coalfire") == "coalfire"

    def test_with_punctuation(self):
        assert slugify("Associate, SOC Assessment") == "associate-soc-assessment"

    def test_collapses_runs(self):
        assert slugify("a   b---c") == "a-b-c"

    def test_strips_edge_hyphens(self):
        assert slugify("- middle -") == "middle"

    def test_truncates(self):
        long = "x" * 100
        assert len(slugify(long, max_len=20)) == 20

    def test_truncate_does_not_leave_trailing_hyphen(self):
        assert slugify("aaa-bbb-ccc-ddd-eee", max_len=10) == "aaa-bbb-cc"

    def test_empty_yields_unknown(self):
        assert slugify("") == "unknown"
        assert slugify("---") == "unknown"


class TestOfferingsFolder:
    def test_path_structure(self, tmp_path):
        d = {"id": 42, "company": "Coalfire", "role": "Senior SOC Analyst"}
        path = offerings_folder(d, base_dir=str(tmp_path))
        assert path == tmp_path / "coalfire-senior-soc-analyst-42"

    def test_handles_missing_company(self, tmp_path):
        d = {"id": 1, "role": "Engineer"}
        path = offerings_folder(d, base_dir=str(tmp_path))
        assert "unknown" in path.name


# ── verifier ────────────────────────────────────────────────────────


class TestVerifyAgainstSource:
    def test_clean_when_all_numbers_in_source(self):
        source = "I have 5 years of experience with Splunk. 47% improvement in detection rate."
        generated = "5 years of experience. 47% improvement."
        assert verify_against_source(generated, source) == []

    def test_flags_fabricated_metric(self):
        source = "5 years of experience."
        generated = "5 years of experience. 99% reduction in incidents."  # 99 is fabricated
        unverified = verify_against_source(generated, source)
        assert "99%" in unverified

    def test_passes_single_digit_freely(self):
        # Single digits are too noisy to flag — likely formatting
        source = "x"
        generated = "1. First bullet\n2. Second bullet\n3. Third"
        # The string parsing will tokenize "1", "2", "3" — all single digits
        unverified = verify_against_source(generated, source)
        assert unverified == []

    def test_handles_comma_thousands(self):
        source = "Processed 10,000 records."
        generated = "Processed 10000 records."  # different formatting
        unverified = verify_against_source(generated, source)
        assert unverified == []

    def test_handles_percent_variation(self):
        source = "Reduced false positives by 30 percent."
        generated = "Reduced false positives by 30%."
        unverified = verify_against_source(generated, source)
        assert unverified == []

    def test_year_in_output_not_in_source_flagged(self):
        source = "Worked at Acme."
        generated = "Worked at Acme from 2019 to 2024."
        unverified = verify_against_source(generated, source)
        assert "2019" in unverified or "2024" in unverified

    def test_empty_inputs(self):
        assert verify_against_source("", "anything") == []
        assert verify_against_source("anything", "") == []


# ── forge_discovery (with mocked AI) ────────────────────────────────


PROFILE = {
    "values": {"security_culture": 0.5, "people_treatment": 0.5},
    "dealbreakers": [],
    "yellow_flags": [],
    "green_flags": [],
    "target_roles": ["AI red team"],
    "judge": {"ready_threshold": 60, "alignment_floor": 50},
}


def _ready_discovery(**overrides):
    base = {
        "id": 100,
        "company": "Coalfire",
        "role": "Associate, SOC Assessment",
        "url": "https://jobs.lever.co/coalfire/abc",
        "screened_status": "ready",
        "combined_score": 75.0,
        "full_description": "We're hiring an associate. Must have SOC 2 / ISO experience. " * 5,
        "location": "Remote",
    }
    base.update(overrides)
    return base


class TestForgeDiscovery:
    """Forge attaches one of two curated résumés — no LLM, no tailoring.

    These replace tests written for the retired LLM-tailoring forge, which
    asserted on prompt contents and invented-claim lists that the static
    version has no reason to produce.
    """

    @staticmethod
    def _profile(tmp_path, *, ir=None, grc=None):
        prof = dict(PROFILE)
        prof["forge"] = {"offerings_dir": str(tmp_path / "offerings")}
        resumes = {}
        if ir is not None:
            resumes["ir"] = str(ir)
        if grc is not None:
            resumes["grc"] = str(grc)
        if resumes:
            prof["resumes"] = resumes
        return prof

    @staticmethod
    def _with_target(closest_target, **overrides):
        import json
        detail = {"role_alignment": {"closest_target": closest_target}}
        return _ready_discovery(judgement_detail=json.dumps(detail), **overrides)

    @staticmethod
    def _resumes(tmp_path):
        ir = tmp_path / "DeAnnaShanks_Resume_IR_2Page.docx"
        grc = tmp_path / "DeAnnaShanks_Resume_AuditGRC_2Page.docx"
        ir.write_bytes(b"PK\x03\x04 IR resume bytes")
        grc.write_bytes(b"PK\x03\x04 GRC resume bytes")
        return ir, grc

    def test_ir_role_gets_the_ir_resume_as_docx(self, tmp_path):
        ir, grc = self._resumes(tmp_path)
        result = forge_discovery(
            self._with_target("Detection engineer"),
            profile=self._profile(tmp_path, ir=ir, grc=grc),
        )
        assert result.get("error") is None
        assert result["resume_kind"] == "IR"
        out = Path(result["resume_path"])
        assert out.name == "resume.docx"
        assert out.read_bytes() == ir.read_bytes()

    def test_grc_role_gets_the_grc_resume(self, tmp_path):
        ir, grc = self._resumes(tmp_path)
        result = forge_discovery(
            self._with_target("IT auditor"),
            profile=self._profile(tmp_path, ir=ir, grc=grc),
        )
        assert result["resume_kind"] == "GRC"
        assert Path(result["resume_path"]).read_bytes() == grc.read_bytes()

    def test_markdown_resume_still_lands_as_resume_md(self, tmp_path):
        md = tmp_path / "ir.md"
        md.write_text("# DeAnna Shanks\n\nDFIR.", encoding="utf-8")
        result = forge_discovery(
            self._with_target("Detection engineer"),
            profile=self._profile(tmp_path, ir=md),
        )
        assert Path(result["resume_path"]).name == "resume.md"

    def test_audit_trail_names_the_source_and_makes_no_ai_calls(self, tmp_path):
        ir, grc = self._resumes(tmp_path)
        result = forge_discovery(
            self._with_target("GRC analyst"),
            profile=self._profile(tmp_path, ir=ir, grc=grc),
        )
        audit = Path(result["audit_path"]).read_text(encoding="utf-8")
        assert "DeAnnaShanks_Resume_AuditGRC_2Page.docx" in audit
        assert "No AI calls were made" in audit
        assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}

    def test_unconfigured_resume_is_a_clear_error(self, tmp_path):
        result = forge_discovery(
            self._with_target("Detection engineer"),
            profile=self._profile(tmp_path),
        )
        assert "No IR resume configured" in result["error"]
        assert "profile.resumes.ir" in result["error"]

    def test_directory_instead_of_file_is_rejected(self, tmp_path):
        folder = tmp_path / "resume_dir"
        folder.mkdir()
        result = forge_discovery(
            self._with_target("Detection engineer"),
            profile=self._profile(tmp_path, ir=folder),
        )
        assert "is a directory" in result["error"]

    def test_non_ready_discovery_is_refused(self, tmp_path):
        ir, grc = self._resumes(tmp_path)
        result = forge_discovery(
            self._with_target("Detection engineer", screened_status="rejected"),
            profile=self._profile(tmp_path, ir=ir, grc=grc),
        )
        assert "not 'ready'" in result["error"]

    def test_existing_resume_is_left_alone_without_force(self, tmp_path):
        ir, grc = self._resumes(tmp_path)
        prof = self._profile(tmp_path, ir=ir, grc=grc)
        d = self._with_target("Detection engineer")
        first = forge_discovery(d, profile=prof)
        ir.write_bytes(b"PK\x03\x04 edited IR resume")
        second = forge_discovery(d, profile=prof)
        assert "skipped_reason" in second
        assert Path(first["resume_path"]).read_bytes() == b"PK\x03\x04 IR resume bytes"

    def test_force_replaces_and_clears_the_other_format(self, tmp_path):
        md = tmp_path / "old.md"
        md.write_text("old markdown resume", encoding="utf-8")
        d = self._with_target("Detection engineer")
        first = forge_discovery(d, profile=self._profile(tmp_path, ir=md))
        folder = Path(first["offerings_path"])
        assert (folder / "resume.md").exists()

        ir, grc = self._resumes(tmp_path)
        forge_discovery(d, profile=self._profile(tmp_path, ir=ir, grc=grc), force=True)
        assert (folder / "resume.docx").exists()
        assert not (folder / "resume.md").exists()


# ── model routing ───────────────────────────────────────────────────


class TestModelRouting:
    def test_openrouter_prefix_dispatches(self, monkeypatch):
        captured = {}
        def fake_or(system, user, model, max_tokens, profile):
            captured["model"] = model
            return ("# x\n", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate_via_openrouter", fake_or)
        monkeypatch.setattr(tailor, "_generate_via_anthropic",
                            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("anthropic should not be called")))

        tailor._generate("sys", "user", model="openrouter:google/gemini-flash-2-0",
                         max_tokens=100, profile=None)
        assert captured["model"] == "google/gemini-flash-2-0"

    def test_bare_name_dispatches_to_anthropic(self, monkeypatch):
        captured = {}
        def fake_anth(system, user, model, max_tokens):
            captured["model"] = model
            return ("# x\n", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate_via_anthropic", fake_anth)
        monkeypatch.setattr(tailor, "_generate_via_openrouter",
                            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("openrouter should not be called")))

        tailor._generate("sys", "user", model="claude-haiku-4-5",
                         max_tokens=100, profile=None)
        assert captured["model"] == "claude-haiku-4-5"
