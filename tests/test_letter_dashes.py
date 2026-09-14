"""Cover letters come out without em or en dashes.

She never writes with them, and a model will slip them in even when told
not to. The prompt itself used to model them seven times. The finished
letter is now checked in code: a sentence-level rewrite first, a mechanical
strip if anything survives.
"""

from pathlib import Path

import pytest

from charon import letter
from charon import tailor


EM, EN = "—", "–"


class TestPrompt:
    def test_rendered_prompt_models_no_dashes(self):
        prompt = letter.build_petition_system_prompt({})
        assert EM not in prompt and EN not in prompt
        assert "Never use em dashes or en dashes" in prompt

    def test_her_voice_block_is_used_when_present(self):
        prompt = letter.build_petition_system_prompt(
            {"voice": {"description": "Warm and human, never cheery or salesy."}}
        )
        assert "Warm and human, never cheery or salesy." in prompt


class TestStrip:
    def test_em_dash_becomes_a_comma(self):
        assert letter.strip_dashes(f"five years{EM}pattern analysis") == "five years, pattern analysis"

    def test_date_range_keeps_a_hyphen(self):
        assert letter.strip_dashes(f"Citi, 2016{EN}2021") == "Citi, 2016-2021"

    def test_no_doubled_punctuation(self):
        assert letter.strip_dashes(f"the end {EM}.") == "the end."


class TestRemoveDashes:
    def test_clean_letter_is_untouched_and_makes_no_call(self, monkeypatch):
        def boom(*a, **kw):
            raise AssertionError("no model call for a clean letter")

        monkeypatch.setattr(tailor, "_generate", boom)
        text, usage, note = letter.remove_dashes(
            "Clean letter.", model="m", max_tokens=100, profile=None
        )
        assert (text, note) == ("Clean letter.", None)

    def test_rewrite_is_used_when_it_comes_back_clean(self, monkeypatch):
        monkeypatch.setattr(
            tailor, "_generate",
            lambda *a, **kw: ("Rewritten, cleanly.", {"input_tokens": 5, "output_tokens": 3}),
        )
        text, usage, note = letter.remove_dashes(
            f"Rewritten{EM}cleanly.", model="m", max_tokens=100, profile=None
        )
        assert EM not in text and text.startswith("Rewritten, cleanly.")
        assert usage["output_tokens"] == 3
        assert "rewrote" in note

    def test_mechanical_strip_when_the_rewrite_still_has_dashes(self, monkeypatch):
        monkeypatch.setattr(
            tailor, "_generate",
            lambda *a, **kw: (f"Still{EM}dashed.", {"input_tokens": 1, "output_tokens": 1}),
        )
        text, _, note = letter.remove_dashes(
            f"Still{EM}dashed.", model="m", max_tokens=100, profile=None
        )
        assert not letter.has_dashes(text)
        assert "stripped mechanically" in note


def _ready(tmp_path):
    return {
        "id": 162025,
        "company": "BeyondTrust",
        "role": "Sr SOC Analyst",
        "location": "Remote",
        "screened_status": "ready",
        "full_description": "Detection engineering and incident response. " * 30,
    }


class TestPetitionEndToEnd:
    def test_saved_letter_has_no_dashes_and_audit_says_so(self, tmp_path, monkeypatch):
        replies = iter([
            (f"I spent five years at Citi{EM}pattern analysis{EM}and detection.", {"input_tokens": 10, "output_tokens": 10}),
            ("I spent five years at Citi on pattern analysis and detection.", {"input_tokens": 4, "output_tokens": 4}),
        ])
        monkeypatch.setattr(tailor, "_generate", lambda *a, **kw: next(replies))

        profile = {"forge": {"offerings_dir": str(tmp_path)}}
        result = letter.petition_discovery(
            _ready(tmp_path), profile=profile, resume_text="Five years at Citi. Detection."
        )
        saved = Path(result["letter_path"]).read_text(encoding="utf-8")
        assert not letter.has_dashes(saved)
        assert "Punctuation cleanup" in Path(result["audit_path"]).read_text(encoding="utf-8")
        assert result["dash_cleanup"]


class TestRewriteEndpointHelper:
    def test_previous_letter_is_kept(self, tmp_path, monkeypatch):
        from charon import dashboard
        from charon.db import add_discovery, get_connection, update_discovery_judgement
        import charon.profile as profile_mod
        import charon.render as render_mod

        rid = add_discovery(
            ats="lever", slug="bt", company="BeyondTrust", role="Sr SOC Analyst",
            url="https://example.com/bt", dedupe_hash="rw-bt", location="Remote",
            description="Detection engineering. " * 60, posted_at=None,
            tier="tier_2", category="security_product_general",
        )
        update_discovery_judgement(
            rid, ghost_score=12, redflag_score=38, alignment_score=92,
            combined_score=77.7, screened_status="ready", judgement_reason="ok",
        )
        folder = tmp_path / "offerings" / "bt"
        folder.mkdir(parents=True)
        (folder / "cover_letter.md").write_text(f"Old letter{EM}with dashes.", encoding="utf-8")
        conn = get_connection()
        try:
            conn.execute("UPDATE discoveries SET offerings_path = ? WHERE id = ?", (str(folder), rid))
            conn.commit()
        finally:
            conn.close()

        resume = tmp_path / "ir.md"
        resume.write_text("DeAnna Shanks. Five years at Citi.", encoding="utf-8")
        monkeypatch.setattr(profile_mod, "load_profile", lambda: {
            "forge": {"offerings_dir": str(tmp_path / "offerings")},
            "resumes": {"ir": str(resume)},
        })
        monkeypatch.setattr(render_mod, "render_offering", lambda i: {"errors": []})
        monkeypatch.setattr(
            tailor, "_generate",
            lambda *a, **kw: ("A new letter without any dashes.", {"input_tokens": 1, "output_tokens": 1}),
        )
        # letter.py binds offerings_folder at import, so patch it there.
        monkeypatch.setattr(letter, "offerings_folder", lambda d, base_dir: folder)

        summary = dashboard._rewrite_cover_letter(rid)
        assert summary["dashes_remaining"] == 0
        assert len(summary["previous"]) == 1
        kept = folder / summary["previous"][0]
        assert kept.read_text(encoding="utf-8") == f"Old letter{EM}with dashes."
        assert (folder / "cover_letter.md").read_text(encoding="utf-8").startswith("A new letter")
