"""Tests for charon/letter.py — petition (cover letter generation)."""

import json
from pathlib import Path

import pytest

from charon import letter as letter_module
from charon import tailor
from charon.letter import petition_discovery


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


class TestPetitionBasics:
    def test_writes_letter_and_audit_files(self, tmp_path, monkeypatch):
        def fake_generate(system, user, *, model, max_tokens, profile):
            return (
                "DeAnna Shanks\n\nThis is a real cover letter that mentions Coalfire and SOC.",
                {"input_tokens": 80, "output_tokens": 40},
            )
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        profile = dict(PROFILE)
        profile["forge"] = {
            "model": "claude-haiku-4-5",
            "max_tokens": 4096,
            "offerings_dir": str(tmp_path),
        }

        result = petition_discovery(
            _ready_discovery(),
            profile=profile,
            resume_text="DeAnna Shanks. SOC analyst. 5 years experience.",
        )

        assert result.get("error") is None
        folder = Path(result["offerings_path"])
        assert folder.exists()
        assert (folder / "cover_letter.md").exists()
        assert (folder / "petition_audit.md").exists()
        # Letter content should be saved
        text = (folder / "cover_letter.md").read_text(encoding="utf-8")
        assert "Coalfire" in text
        # Audit should mention petition specifically
        audit = (folder / "petition_audit.md").read_text(encoding="utf-8")
        assert "Petition" in audit

    def test_skips_when_letter_exists(self, tmp_path, monkeypatch):
        called = {"n": 0}
        def fake_generate(system, user, *, model, max_tokens, profile):
            called["n"] += 1
            return ("Letter content here, plenty long.", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}

        d = _ready_discovery()
        petition_discovery(d, profile=profile, resume_text="x")
        result = petition_discovery(d, profile=profile, resume_text="x")

        assert "already exists" in (result.get("skipped_reason") or "")
        assert called["n"] == 1

    def test_force_overwrites_letter_only(self, tmp_path, monkeypatch):
        # Verify --force overwrites cover_letter.md but doesn't touch resume.md if it's there
        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}

        d = _ready_discovery()
        from charon.tailor import offerings_folder
        folder = offerings_folder(d, base_dir=str(tmp_path))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "resume.md").write_text("# Existing resume", encoding="utf-8")

        call_count = {"n": 0}
        def fake_generate(system, user, *, model, max_tokens, profile):
            call_count["n"] += 1
            return (f"Letter run {call_count['n']}.", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        petition_discovery(d, profile=profile, resume_text="x")
        petition_discovery(d, profile=profile, resume_text="x", force=True)

        # Letter overwritten
        assert "Letter run 2" in (folder / "cover_letter.md").read_text(encoding="utf-8")
        # Resume untouched
        assert "Existing resume" in (folder / "resume.md").read_text(encoding="utf-8")

    def test_rejects_unready_discovery(self, tmp_path, monkeypatch):
        def boom(*a, **kw):
            raise AssertionError("AI should not be called for non-ready discoveries")
        monkeypatch.setattr(tailor, "_generate", boom)

        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}

        d = _ready_discovery(screened_status="rejected")
        result = petition_discovery(d, profile=profile, resume_text="x")
        assert "not 'ready'" in (result.get("error") or "")


class TestJudgementHints:
    def test_overlap_and_gaps_flow_into_prompt(self, tmp_path, monkeypatch):
        captured = {}
        def fake_generate(system, user, *, model, max_tokens, profile):
            captured["user"] = user
            return ("# letter\n\nbody here long enough to be real text.", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        d = _ready_discovery()
        d["judgement_detail"] = json.dumps({
            "resume_match": {
                "overlap": ["Citi fraud detection experience", "SOC tooling background"],
                "gaps": ["No SOC 2 framework knowledge", "No FedRAMP experience"],
            },
            "role_alignment": {"overlap": ["security analysis", "audit thinking"]},
            "redflags": {
                "green_flags_found": [
                    {"flag": "remote-friendly", "evidence": "fully remote position"},
                ],
            },
        })

        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}
        petition_discovery(d, profile=profile, resume_text="x")

        # All three signal types must appear in the user prompt
        assert "STRENGTHS TO LEAD WITH" in captured["user"]
        assert "Citi fraud detection" in captured["user"]
        assert "GAPS" in captured["user"]
        assert "No SOC 2" in captured["user"]
        assert "GREEN FLAGS" in captured["user"]
        assert "remote-friendly" in captured["user"]

    def test_handles_missing_judgement_detail(self, tmp_path, monkeypatch):
        captured = {}
        def fake_generate(system, user, *, model, max_tokens, profile):
            captured["user"] = user
            return ("letter content", {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        d = _ready_discovery()  # no judgement_detail
        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}
        petition_discovery(d, profile=profile, resume_text="x")

        # Should still build a valid prompt without judgement hints section
        assert "STRENGTHS TO LEAD WITH" not in captured["user"]


class TestVoicePromptContent:
    """Verify the system prompt actually contains the voice guidance.
    If someone accidentally regresses the prompt, this catches it."""

    def test_bans_corporate_phrases(self):
        from charon.letter import PETITION_SYSTEM_PROMPT
        assert "passionate about" in PETITION_SYSTEM_PROMPT
        assert "I am writing" in PETITION_SYSTEM_PROMPT
        assert "Looking forward to hearing" in PETITION_SYSTEM_PROMPT

    def test_voice_traits_present(self):
        from charon.letter import PETITION_SYSTEM_PROMPT
        # Must have guidance on conversational, specific, varied length
        assert "Conversational" in PETITION_SYSTEM_PROMPT
        assert "Specific over abstract" in PETITION_SYSTEM_PROMPT
        assert "Vary sentence length" in PETITION_SYSTEM_PROMPT
        # Honesty about gaps
        assert "Honest about gaps" in PETITION_SYSTEM_PROMPT

    def test_geographic_fabrication_explicitly_banned(self):
        """Regression: an early Coalfire petition fabricated 'I'm in the UK'.
        The numerical verifier doesn't catch geographic claims, so the rule
        must live in the prompt. Pin it here so it can't be silently dropped."""
        from charon.letter import PETITION_SYSTEM_PROMPT
        assert "city, state, or country" in PETITION_SYSTEM_PROMPT
        assert "Do NOT invent a relocation" in PETITION_SYSTEM_PROMPT


class TestVerifierIntegration:
    def test_unverified_claim_in_letter_is_flagged(self, tmp_path, monkeypatch):
        # AI fabricates "47% improvement" — not in resume
        def fake_generate(system, user, *, model, max_tokens, profile):
            return (
                "Coalfire team -- I drove a 47% improvement in detection quality at my last role.",
                {"input_tokens": 0, "output_tokens": 0},
            )
        monkeypatch.setattr(tailor, "_generate", fake_generate)

        profile = dict(PROFILE)
        profile["forge"] = {"offerings_dir": str(tmp_path)}

        result = petition_discovery(
            _ready_discovery(),
            profile=profile,
            resume_text="DeAnna Shanks. Worked in DFIR.",
        )

        assert "47%" in result["unverified_claims"]
        # Letter still written; verifier warns, doesn't block
        assert Path(result["offerings_path"]).exists()
