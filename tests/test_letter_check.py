"""Claim check: a cover letter can't say things about her the résumé doesn't.

Regression source: the BeyondTrust letter (discovery 162025) invented
"thousands of transactions" and "earned my degree while working full-time"
and had three "X, not Y" lines. The numeric verifier caught none of it.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from charon import letter, letter_check, tailor
from charon.tailor import ForgeError


RESUME = "DeAnna Shanks. Fraud Investigator, Citi, Oct 2016 - Dec 2021. B.S. Cybersecurity, WGU."
FABRICATED = "At Citi I reviewed thousands of transactions a day. I earned my degree while working full-time."
CLEANED = "At Citi I investigated fraud for five years. I have a B.S. in Cybersecurity from WGU."
NO_USAGE = {"input_tokens": 1, "output_tokens": 1}


def _check_json(unsupported=(), style=(), supported=()):
    claims = [{"quote": q, "supported": False, "evidence": ""} for q in unsupported]
    claims += [{"quote": q, "supported": True, "evidence": "résumé"} for q in supported]
    return json.dumps({
        "claims": claims,
        "style": [{"quote": q, "pattern": p} for q, p in style],
    })


class ScriptedModels:
    """Checker calls get the next check reply; anything else is a rewrite."""

    def __init__(self, checks, rewrites=()):
        self.checks = list(checks)
        self.rewrites = list(rewrites)
        self.calls = []

    def __call__(self, system, user, *, model, max_tokens, profile):
        is_check = system == letter_check.CHECK_SYSTEM
        self.calls.append(("check" if is_check else "rewrite", model, user))
        if is_check:
            reply = self.checks.pop(0)
        else:
            reply = self.rewrites.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, NO_USAGE


def _guard(monkeypatch, models, text=FABRICATED, profile=None, writer="claude-haiku-4-5"):
    monkeypatch.setattr(tailor, "_generate", models)
    return letter_check.guard_letter(
        text, RESUME, writer_model=writer, max_tokens=4096, profile=profile
    )


class TestGuard:
    def test_clean_letter_is_checked_once_and_untouched(self, monkeypatch):
        models = ScriptedModels([_check_json(supported=["I investigated fraud at Citi"])])
        text, report, _ = _guard(monkeypatch, models, text=CLEANED)
        assert text == CLEANED
        assert report["status"] == "clean"
        assert report["rounds"] == 0
        assert report["claims_checked"] == 1
        assert [c[0] for c in models.calls] == ["check"]

    def test_invented_claims_are_rewritten_out(self, monkeypatch):
        models = ScriptedModels(
            checks=[
                _check_json(
                    unsupported=["thousands of transactions a day", "while working full-time"],
                    style=[("fraud, not paperwork", "contrast")],
                ),
                _check_json(supported=["investigated fraud for five years"]),
            ],
            rewrites=[CLEANED],
        )
        text, report, usage = _guard(monkeypatch, models)
        assert text.strip() == CLEANED
        assert report["status"] == "clean"
        assert report["rounds"] == 1
        assert {f["quote"] for f in report["fixed"]} == {
            "thousands of transactions a day", "while working full-time", "fraud, not paperwork",
        }
        # The rewrite is told exactly what to fix.
        rewrite_prompt = models.calls[1][2]
        assert 'UNSUPPORTED CLAIM: "while working full-time"' in rewrite_prompt
        assert 'CONTRAST: "fraud, not paperwork"' in rewrite_prompt
        assert usage["input_tokens"] == 3

    def test_problems_that_survive_are_kept_for_her_to_see(self, monkeypatch):
        stubborn = _check_json(unsupported=["thousands of transactions a day"])
        models = ScriptedModels(
            checks=[stubborn] * (letter_check.MAX_ROUNDS + 1),
            rewrites=[FABRICATED] * letter_check.MAX_ROUNDS,
        )
        text, report, _ = _guard(monkeypatch, models)
        assert report["status"] == "flagged"
        assert report["rounds"] == letter_check.MAX_ROUNDS
        assert report["unsupported"][0]["quote"] == "thousands of transactions a day"
        assert text  # never dropped
        assert letter_check.flag_count(report) == 1

    def test_checker_failure_means_unchecked_not_clean(self, monkeypatch):
        models = ScriptedModels(checks=["I think the letter looks great!"])
        text, report, _ = _guard(monkeypatch, models)
        assert report["status"] == "unchecked"
        assert "JSON" in report["error"]
        assert text == FABRICATED
        assert letter_check.flag_count(report) == -1

    def test_api_error_during_check_means_unchecked(self, monkeypatch):
        models = ScriptedModels(checks=[ForgeError("Anthropic rate limit reached.")])
        _, report, _ = _guard(monkeypatch, models)
        assert report["status"] == "unchecked"

    def test_one_checker_for_every_writer(self, monkeypatch):
        models = ScriptedModels(
            checks=[_check_json(unsupported=["x"]), _check_json()],
            rewrites=[CLEANED],
        )
        _guard(monkeypatch, models, writer="openrouter:vendor/some-model")
        assert [(kind, model) for kind, model, _ in models.calls] == [
            ("check", "claude-sonnet-5"),
            ("rewrite", "openrouter:vendor/some-model"),
            ("check", "claude-sonnet-5"),
        ]

    def test_checker_model_comes_from_profile(self, monkeypatch):
        models = ScriptedModels(checks=[_check_json()])
        _, report, _ = _guard(monkeypatch, models, profile={"forge": {"checker_model": "claude-opus-5"}})
        assert models.calls[0][1] == "claude-opus-5"
        assert report["checker_model"] == "claude-opus-5"


class TestPrompts:
    def test_checker_is_told_about_the_beyondtrust_failure_modes(self):
        p = letter_check.CHECK_SYSTEM
        assert "while working full-time" in p
        assert "thousands of" in p
        assert '"X, not Y"' in p
        assert "TWO or more" in p

    def test_prompts_model_no_dashes(self):
        for p in (letter_check.CHECK_SYSTEM, letter_check.REWRITE_SYSTEM):
            assert "—" not in p and "–" not in p


class TestPetitionWritesTheCheck:
    def test_report_saved_next_to_letter_and_in_audit(self, tmp_path, monkeypatch):
        models = ScriptedModels(
            checks=[_check_json(unsupported=["thousands of transactions a day"]), _check_json()],
            rewrites=[CLEANED],
        )

        def fake_generate(system, user, *, model, max_tokens, profile):
            if system in (letter_check.CHECK_SYSTEM,) or system.startswith("You revise a cover letter"):
                return models(system, user, model=model, max_tokens=max_tokens, profile=profile)
            return FABRICATED, NO_USAGE

        monkeypatch.setattr(tailor, "_generate", fake_generate)
        d = {
            "id": 162025, "company": "BeyondTrust", "role": "Sr SOC Analyst",
            "location": "Remote", "screened_status": "ready",
            "full_description": "Detection engineering and incident response. " * 30,
        }
        result = letter.petition_discovery(
            d, profile={"forge": {"offerings_dir": str(tmp_path)}}, resume_text=RESUME
        )
        folder = Path(result["offerings_path"])
        assert (folder / "cover_letter.md").read_text(encoding="utf-8").strip() == CLEANED
        saved = letter_check.read_report(folder)
        assert saved["status"] == "clean"
        assert saved["fixed"][0]["quote"] == "thousands of transactions a day"
        audit = (folder / "petition_audit.md").read_text(encoding="utf-8")
        assert "## Claim check" in audit
        assert "thousands of transactions a day" in audit
        assert result["letter_check"]["status"] == "clean"


class TestReadyCardFlags:
    def test_flags_from_saved_report(self, tmp_path):
        from charon.dashboard import _letter_flags

        assert _letter_flags(str(tmp_path)) == {"letter_flags": None, "letter_flag_items": []}
        letter_check.write_report(tmp_path, {
            "status": "flagged",
            "unsupported": [{"quote": "thousands of transactions"}],
            "style": [{"quote": "fraud, not paperwork", "pattern": "contrast"}],
        })
        out = _letter_flags(str(tmp_path))
        assert out["letter_flags"] == 2
        assert 'Not on résumé: "thousands of transactions"' in out["letter_flag_items"]

    def test_clean_report_shows_no_warning(self, tmp_path):
        from charon.dashboard import _letter_flags

        letter_check.write_report(tmp_path, {"status": "clean", "unsupported": [], "style": []})
        assert _letter_flags(str(tmp_path)) == {"letter_flags": 0, "letter_flag_items": []}


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.params = None

    def create(self, **params):
        self.params = params
        return self.response


def _fake_anthropic(monkeypatch, response):
    import anthropic

    messages = _FakeMessages(response)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=messages))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return messages


def _response(blocks, stop_reason="end_turn"):
    return SimpleNamespace(
        content=blocks, stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class TestNewerClaudeModels:
    def test_sonnet_5_gets_no_temperature_and_room_to_think(self, monkeypatch):
        messages = _fake_anthropic(monkeypatch, _response([
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="The letter."),
        ]))
        text, _ = tailor._generate_via_anthropic("sys", "user", "claude-sonnet-5", 4096)
        assert text == "The letter."
        assert "temperature" not in messages.params
        assert messages.params["max_tokens"] >= tailor.THINKING_MIN_MAX_TOKENS

    def test_haiku_keeps_temperature_and_its_token_cap(self, monkeypatch):
        messages = _fake_anthropic(monkeypatch, _response([SimpleNamespace(type="text", text="ok")]))
        tailor._generate_via_anthropic("sys", "user", "claude-haiku-4-5", 4096)
        assert messages.params["temperature"] == 0.3
        assert messages.params["max_tokens"] == 4096

    def test_truncated_letter_is_an_error(self, monkeypatch):
        _fake_anthropic(monkeypatch, _response(
            [SimpleNamespace(type="text", text="I spent five years at")], stop_reason="max_tokens"
        ))
        with pytest.raises(ForgeError, match="ran out of tokens"):
            tailor._generate_via_anthropic("sys", "user", "claude-opus-5", 4096)

    def test_refusal_is_an_error(self, monkeypatch):
        _fake_anthropic(monkeypatch, _response([], stop_reason="refusal"))
        with pytest.raises(ForgeError, match="declined"):
            tailor._generate_via_anthropic("sys", "user", "claude-opus-5", 4096)

    @pytest.mark.parametrize("model,expected", [
        ("claude-sonnet-5", True),
        ("claude-opus-5", True),
        ("anthropic/claude-sonnet-5", True),
        ("claude-haiku-4-5", False),
        ("openai/some-gpt", False),
    ])
    def test_thinking_model_detection(self, model, expected):
        assert tailor._is_thinking_model(model) is expected
