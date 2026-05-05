"""Tests for charon provision (forge + petition wrapper) and charon offerings.

These exercise the CLI orchestration via Click's CliRunner. AI calls are
mocked at the tailor._generate seam, so no live network and no spend.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from charon import cli as cli_module
from charon import tailor
from charon.cli import cli
from charon.db import (
    add_discovery,
    update_discovery_enrichment,
    update_discovery_judgement,
)


def _seed_ready(tmp_path, **overrides):
    """Seed an enriched + judged ready discovery for tests."""
    defaults = dict(
        ats="lever",
        slug="coalfire",
        company="Coalfire",
        role="Associate, SOC Assessment",
        url=overrides.pop("url", "https://jobs.lever.co/coalfire/abc"),
        dedupe_hash=overrides.pop("dedupe_hash", "prov-1"),
        location="Remote",
        description="",
        posted_at="Posted Today",
        tier="tier_1",
        category="audit",
    )
    defaults.update(overrides)
    new_id = add_discovery(**defaults)
    update_discovery_enrichment(new_id, "jsonld", "Job description content " * 30)
    update_discovery_judgement(
        new_id,
        ghost_score=15,
        redflag_score=20,
        alignment_score=80,
        combined_score=78.0,
        screened_status="ready",
        judgement_reason="combined 78.0 >= 60",
        judgement_detail={
            "ghostbust": {"ghost_score": 15},
            "redflags": {"redflag_score": 20, "dealbreakers_found": []},
            "role_alignment": {"alignment_score": 80, "overlap": []},
        },
    )
    return new_id


def _stub_profile(tmp_path, monkeypatch):
    """Patch load_profile to return a profile pointing resume + offerings at tmp_path."""
    resume = tmp_path / "resume.md"
    resume.write_text("# Test Candidate\n\nFive years EDR experience.", encoding="utf-8")

    profile = {
        "values": {"security_culture": 0.5, "people_treatment": 0.5},
        "dealbreakers": [],
        "yellow_flags": [],
        "green_flags": [],
        "target_roles": ["AppSec"],
        "judge": {"ready_threshold": 60, "alignment_floor": 50},
        "resume_path": str(resume),
        "forge": {
            "model": "claude-haiku-4-5",
            "max_tokens": 4096,
            "offerings_dir": str(tmp_path / "offerings"),
        },
    }
    monkeypatch.setattr(cli_module, "load_profile", lambda: profile)
    return profile


def _stub_generate(monkeypatch, body: str = "Real tailored content here, plenty long."):
    """Stub the AI generation seam used by both forge and petition."""
    def fake(system, user, *, model, max_tokens, profile):
        return (body, {"input_tokens": 50, "output_tokens": 25})
    monkeypatch.setattr(tailor, "_generate", fake)


# ── provision ───────────────────────────────────────────────────────


class TestProvisionSingle:
    def test_runs_forge_then_petition(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        _stub_generate(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["provision", "--id", str(new_id)])

        assert result.exit_code == 0, result.output
        assert "PROVISION" in result.output

        # Both files should exist
        offerings_dir = tmp_path / "offerings"
        folders = list(offerings_dir.iterdir())
        assert len(folders) == 1
        folder = folders[0]
        assert (folder / "resume.md").exists()
        assert (folder / "cover_letter.md").exists()
        assert (folder / "forge_audit.md").exists()
        assert (folder / "petition_audit.md").exists()

    def test_unknown_id_errors(self, tmp_path, monkeypatch):
        _stub_profile(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["provision", "--id", "99999"])
        assert "No discovery with id" in result.output

    def test_no_id_no_ready_errors(self, tmp_path, monkeypatch):
        _stub_profile(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["provision"])
        assert "Provide --id" in result.output


class TestProvisionBatch:
    def test_processes_only_ready_missing_materials(self, tmp_path, monkeypatch):
        a = _seed_ready(tmp_path, dedupe_hash="b-a")
        b = _seed_ready(tmp_path, dedupe_hash="b-b",
                        url="https://jobs.lever.co/coalfire/def")
        _stub_profile(tmp_path, monkeypatch)

        call_count = {"n": 0}
        def counting_gen(system, user, *, model, max_tokens, profile):
            call_count["n"] += 1
            return ("content " * 20, {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", counting_gen)

        runner = CliRunner()
        result = runner.invoke(cli, ["provision", "--ready"])

        assert result.exit_code == 0, result.output
        # forge + petition for each of 2 discoveries = 4 calls
        assert call_count["n"] == 4

    def test_skips_already_complete_without_force(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        _stub_generate(monkeypatch)

        runner = CliRunner()
        # First run should provision
        result1 = runner.invoke(cli, ["provision", "--ready"])
        assert result1.exit_code == 0

        # Second run without --force: nothing to do
        call_count = {"n": 0}
        def counting_gen(system, user, *, model, max_tokens, profile):
            call_count["n"] += 1
            return ("x " * 20, {"input_tokens": 0, "output_tokens": 0})
        monkeypatch.setattr(tailor, "_generate", counting_gen)

        result2 = runner.invoke(cli, ["provision", "--ready"])
        assert "Nothing to provision" in result2.output
        assert call_count["n"] == 0


# ── offerings ───────────────────────────────────────────────────────


class TestOfferingsList:
    def test_empty_when_nothing_provisioned(self, tmp_path, monkeypatch):
        _seed_ready(tmp_path)  # ready but no offerings yet
        _stub_profile(tmp_path, monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["offerings", "--list"])
        assert "No offerings yet" in result.output

    def test_lists_after_provision(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        _stub_generate(monkeypatch)

        runner = CliRunner()
        runner.invoke(cli, ["provision", "--id", str(new_id)])

        result = runner.invoke(cli, ["offerings", "--list"])
        assert result.exit_code == 0
        assert "Coalfire" in result.output
        assert "FP" in result.output  # both forged + petitioned

    def test_list_is_default(self, tmp_path, monkeypatch):
        _stub_profile(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["offerings"])
        # No args = show list (or empty)
        assert "OFFERINGS" in result.output or "No offerings" in result.output


class TestOfferingsId:
    def test_show_files_for_id(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        _stub_generate(monkeypatch)

        runner = CliRunner()
        runner.invoke(cli, ["provision", "--id", str(new_id)])

        result = runner.invoke(cli, ["offerings", "--id", str(new_id)])
        assert result.exit_code == 0
        assert "resume.md" in result.output
        assert "cover_letter.md" in result.output
        assert "forge_audit.md" in result.output
        assert "petition_audit.md" in result.output

    def test_warns_when_no_offerings_yet(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)  # ready but unprovisioned
        _stub_profile(tmp_path, monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["offerings", "--id", str(new_id)])
        assert "No offerings" in result.output

    def test_unknown_id(self, tmp_path, monkeypatch):
        _stub_profile(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["offerings", "--id", "99999"])
        assert "No discovery" in result.output
