"""Letter bake-off writes every model's letter somewhere other than her real offerings."""

import json
from pathlib import Path

import pytest

from charon import bakeoff, letter_check, tailor


@pytest.fixture(autouse=True)
def _no_claim_check(monkeypatch):
    monkeypatch.setattr(
        letter_check, "guard_letter",
        lambda text, resume, **kw: (text, {"status": "clean"}, {"input_tokens": 0, "output_tokens": 0}),
    )


class TestValidate:
    def test_accepts_claude_and_openrouter_ids(self):
        assert bakeoff.validate_models(
            ["claude-sonnet-5", "openrouter:openai/gpt-5.6-sol", "claude-sonnet-5"]
        ) == ["claude-sonnet-5", "openrouter:openai/gpt-5.6-sol"]

    @pytest.mark.parametrize("bad", [[], "claude-sonnet-5", ["../../etc"], ["a b"], ["m"]])
    def test_rejects_junk(self, bad):
        with pytest.raises(bakeoff.BakeoffError):
            bakeoff.validate_models(bad)

    def test_caps_model_count(self):
        with pytest.raises(bakeoff.BakeoffError, match="at most"):
            bakeoff.validate_models([f"model-{i}" for i in range(bakeoff.MAX_MODELS + 1)])


class TestRun:
    def test_each_model_writes_its_own_letter_outside_offerings(self, tmp_path, monkeypatch):
        from charon.db import add_discovery, get_connection
        import charon.profile as profile_mod

        rid = add_discovery(
            ats="lever", slug="bt", company="BeyondTrust", role="Sr SOC Analyst",
            url="https://example.com/bt-bake", dedupe_hash="bake-bt", location="Remote",
            description="Detection engineering. " * 60, posted_at=None,
            tier="tier_2", category="security_product_general",
        )
        conn = get_connection()
        try:  # an applied row still gets a fair test
            conn.execute("UPDATE discoveries SET screened_status = 'applied' WHERE id = ?", (rid,))
            conn.commit()
        finally:
            conn.close()

        resume = tmp_path / "ir.md"
        resume.write_text("DeAnna Shanks. Five years at Citi.", encoding="utf-8")
        offerings = tmp_path / "offerings"
        monkeypatch.setattr(profile_mod, "load_profile", lambda: {
            "forge": {"offerings_dir": str(offerings)},
            "resumes": {"ir": str(resume)},
        })
        monkeypatch.setattr(bakeoff, "DEFAULT_BAKEOFF_DIR", str(tmp_path / "bakeoff"))
        monkeypatch.setattr(
            tailor, "_generate",
            lambda system, user, *, model, max_tokens, profile: (f"Letter by {model}.", {"input_tokens": 1, "output_tokens": 1}),
        )

        summary = bakeoff.run_bakeoff(rid, ["claude-sonnet-5", "openrouter:google/gemini-3.1-pro-preview"])

        assert not offerings.exists()
        by_model = {r["model"]: r for r in summary["results"]}
        for model in ("claude-sonnet-5", "openrouter:google/gemini-3.1-pro-preview"):
            path = Path(by_model[model]["letter_path"])
            assert str(tmp_path / "bakeoff") in str(path)
            assert path.read_text(encoding="utf-8").strip() == f"Letter by {model}."
        saved = json.loads((tmp_path / "bakeoff" / str(rid) / "summary.json").read_text(encoding="utf-8"))
        assert len(saved["results"]) == 2
