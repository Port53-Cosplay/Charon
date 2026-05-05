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
    def test_writes_resume_and_audit_files(self, tmp_path, monkeypatch):
        # Mock the AI generation
        def fake_generate(system, user, *, model, max_tokens, profile):
            return ("# DeAnna Shanks\n\n5 years of experience.\n", {"input_tokens": 100, "output_tokens": 50})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        profile = dict(PROFILE)
        profile["forge"] = {
            "model": "claude-haiku-4-5",
            "max_tokens": 4096,
            "offerings_dir": str(tmp_path),
        }

        result = forge_discovery(
            _ready_discovery(),
            profile=profile,
            resume_text="DeAnna Shanks. 5 years of experience.",
        )

        assert result.get("error") is None
        folder = Path(result["offerings_path"])
        assert folder.exists()
        assert (folder / "resume.md").exists()
        assert (folder / "prompt_used.md").exists()
        assert (folder / "resume.md").read_text(encoding="utf-8").startswith("# DeAnna Shanks")
        assert result["unverified_claims"] == []
        assert result["usage"]["input_tokens"] == 100

    def test_verifier_warns_on_fabrication(self, tmp_path, monkeypatch):
        # AI claims 99% — not in source resume
        def fake_generate(system, user, *, model, max_tokens, profile):
            return ("# DeAnna\n\nReduced incidents by 99%.", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        profile = dict(PROFILE)
        profile["forge"] = {
            "model": "claude-haiku-4-5",
            "max_tokens": 4096,
            "offerings_dir": str(tmp_path),
        }

        result = forge_discovery(
            _ready_discovery(),
            profile=profile,
            resume_text="DeAnna Shanks. Worked in DFIR.",
        )

        # Unverified claim is surfaced
        assert "99%" in result["unverified_claims"]
        # File is still written — verifier warns, doesn't block
        assert Path(result["offerings_path"]).exists()
        # Audit file mentions the unverified claim
        audit = (Path(result["offerings_path"]) / "prompt_used.md").read_text(encoding="utf-8")
        assert "99%" in audit
        assert "unverified" in audit.lower()

    def test_skips_when_folder_exists_without_force(self, tmp_path, monkeypatch):
        called = {"n": 0}
        def fake_generate(system, user, *, model, max_tokens, profile):
            called["n"] += 1
            return ("# X\n\n", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        profile = dict(PROFILE)
        profile["forge"] = {
            "model": "claude-haiku-4-5",
            "max_tokens": 4096,
            "offerings_dir": str(tmp_path),
        }

        d = _ready_discovery()
        # First run creates folder
        forge_discovery(d, profile=profile, resume_text="resume content")
        # Second run without --force should skip
        result = forge_discovery(d, profile=profile, resume_text="resume content")

        assert "already exists" in (result.get("skipped_reason") or "")
        # Generator should have been called only once
        assert called["n"] == 1

    def test_force_overwrites(self, tmp_path, monkeypatch):
        call_count = {"n": 0}
        def fake_generate(system, user, *, model, max_tokens, profile):
            call_count["n"] += 1
            return (f"# Run {call_count['n']}\n\n", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        profile = dict(PROFILE)
        profile["forge"] = {
            "model": "claude-haiku-4-5",
            "max_tokens": 4096,
            "offerings_dir": str(tmp_path),
        }

        d = _ready_discovery()
        forge_discovery(d, profile=profile, resume_text="x")
        forge_discovery(d, profile=profile, resume_text="x", force=True)

        assert call_count["n"] == 2
        folder = offerings_folder(d, base_dir=str(tmp_path))
        # Last write wins
        assert "Run 2" in (folder / "resume.md").read_text(encoding="utf-8")

    def test_rejects_unready_discovery(self, tmp_path, monkeypatch):
        def boom(*a, **kw):
            raise AssertionError("AI should not be called for non-ready discoveries")
        monkeypatch.setattr(tailor, "_generate", boom)

        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}

        d = _ready_discovery(screened_status="rejected")
        result = forge_discovery(d, profile=profile, resume_text="x")
        assert "not 'ready'" in (result.get("error") or "")

    def test_rejects_no_description(self, tmp_path, monkeypatch):
        def boom(*a, **kw):
            raise AssertionError("AI should not be called when there's no description")
        monkeypatch.setattr(tailor, "_generate", boom)

        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}

        d = _ready_discovery(full_description="", description="")
        result = forge_discovery(d, profile=profile, resume_text="x")
        assert "no usable description" in (result.get("error") or "")

    def test_judgement_hints_included_in_prompt(self, tmp_path, monkeypatch):
        captured = {}
        def fake_generate(system, user, *, model, max_tokens, profile):
            captured["user"] = user
            return ("# x\n", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        import json
        d = _ready_discovery()
        d["judgement_detail"] = json.dumps({
            "resume_match": {
                "overlap": ["EDR experience", "Splunk hands-on"],
                "gaps": ["No GRC framework knowledge"],
            },
            "role_alignment": {"overlap": ["DFIR"]},
        })

        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}
        forge_discovery(d, profile=profile, resume_text="x")

        assert "EXPERIENCE TO EMPHASIZE" in captured["user"]
        assert "EDR experience" in captured["user"]
        assert "Splunk" in captured["user"]


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
