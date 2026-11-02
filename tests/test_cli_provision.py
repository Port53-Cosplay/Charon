"""Tests for charon provision (the letter template) and charon offerings.

Provision does what Prep does on the portal: a blank cover_letter.docx with
the résumé's letterhead, addressed from the company contacts search. The
search is the only paid step, so it's stubbed and the confirm is exercised.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from charon import cli as cli_module
from charon import prep
from charon.cli import cli
from docx import Document

from charon.db import (
    add_discovery,
    save_history,
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
    """Patch load_profile to a profile with a .docx résumé and offerings under tmp_path."""
    resume = tmp_path / "resume.docx"
    doc = Document()
    doc.add_paragraph("Test Candidate")
    doc.add_paragraph("test@example.com")
    doc.add_paragraph().add_run("PROFESSIONAL SUMMARY").bold = True
    doc.add_paragraph("Five years EDR experience.")
    doc.save(str(resume))

    profile = {
        "target_roles": ["AppSec"],
        "resumes": {"ir": str(resume)},
        "forge": {"offerings_dir": str(tmp_path / "offerings")},
    }
    monkeypatch.setattr(cli_module, "load_profile", lambda: profile)
    return profile


LEADER = {"contacts": [{"name": "Lee Leader", "category": "security_leadership"}]}


def _with_contacts(company="Coalfire"):
    save_history("contacts", "company", company, 1.0, LEADER, company=company)


def _stub_search(monkeypatch):
    """Stub the paid contacts search; returns the list of companies searched."""
    searched = []

    def fake(company, profile):
        searched.append(company)
        return save_history("contacts", "company", company, 1.0, LEADER, company=company)

    monkeypatch.setattr(prep, "search_contacts", fake)
    return searched


def _letter(tmp_path):
    folders = list((tmp_path / "offerings").iterdir())
    assert len(folders) == 1
    return folders[0] / "cover_letter.docx"


# ── provision ───────────────────────────────────────────────────────


class TestProvisionSingle:
    def test_makes_letter_template_and_nothing_else(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        _with_contacts()

        result = CliRunner().invoke(cli, ["provision", "--id", str(new_id)])

        assert result.exit_code == 0, result.output
        letter = _letter(tmp_path)
        assert sorted(p.name for p in letter.parent.iterdir()) == ["cover_letter.docx"]
        texts = [p.text for p in Document(str(letter)).paragraphs]
        assert "Dear Lee Leader," in texts
        assert texts[-1] == "Test Candidate"

    def test_asks_before_paid_search_and_aborts_on_no(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        searched = _stub_search(monkeypatch)

        result = CliRunner().invoke(cli, ["provision", "--id", str(new_id)], input="n\n")

        assert "No contacts on file" in result.output
        assert searched == []
        assert not (tmp_path / "offerings").exists()

    def test_searches_on_yes_then_addresses_letter(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        searched = _stub_search(monkeypatch)

        result = CliRunner().invoke(cli, ["provision", "--id", str(new_id)], input="y\n")

        assert result.exit_code == 0, result.output
        assert searched == ["Coalfire"]
        assert "Dear Lee Leader," in [p.text for p in Document(str(_letter(tmp_path))).paragraphs]

    def test_force_keeps_the_old_letter(self, tmp_path, monkeypatch):
        new_id = _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        _with_contacts()
        runner = CliRunner()
        runner.invoke(cli, ["provision", "--id", str(new_id)])
        _letter(tmp_path).write_bytes(b"her draft")

        runner.invoke(cli, ["provision", "--id", str(new_id)])
        assert _letter(tmp_path).read_bytes() == b"her draft"

        runner.invoke(cli, ["provision", "--id", str(new_id), "--force"])
        kept = list(_letter(tmp_path).parent.glob("cover_letter.previous-*.docx"))
        assert len(kept) == 1 and kept[0].read_bytes() == b"her draft"
        assert _letter(tmp_path).read_bytes() != b"her draft"

    def test_unknown_id_errors(self, tmp_path, monkeypatch):
        _stub_profile(tmp_path, monkeypatch)
        result = CliRunner().invoke(cli, ["provision", "--id", "99999"])
        assert "No discovery with id" in result.output

    def test_no_id_no_ready_errors(self, tmp_path, monkeypatch):
        _stub_profile(tmp_path, monkeypatch)
        result = CliRunner().invoke(cli, ["provision"])
        assert "Provide --id" in result.output


class TestProvisionBatch:
    def test_one_search_per_company(self, tmp_path, monkeypatch):
        _seed_ready(tmp_path, dedupe_hash="b-a")
        _seed_ready(tmp_path, dedupe_hash="b-b", url="https://jobs.lever.co/coalfire/def")
        _stub_profile(tmp_path, monkeypatch)
        searched = _stub_search(monkeypatch)

        result = CliRunner().invoke(cli, ["provision", "--ready", "--yes"])

        assert result.exit_code == 0, result.output
        assert searched == ["Coalfire"]
        assert len(list((tmp_path / "offerings").glob("*/cover_letter.docx"))) == 2

    def test_skips_already_done_without_force(self, tmp_path, monkeypatch):
        _seed_ready(tmp_path)
        _stub_profile(tmp_path, monkeypatch)
        _with_contacts()
        runner = CliRunner()
        assert runner.invoke(cli, ["provision", "--ready"]).exit_code == 0

        result = runner.invoke(cli, ["provision", "--ready"])
        assert "Nothing to prep" in result.output


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
        _with_contacts()

        runner = CliRunner()
        runner.invoke(cli, ["provision", "--id", str(new_id)])

        result = runner.invoke(cli, ["offerings", "--list"])
        assert result.exit_code == 0
        assert "Coalfire" in result.output
        assert "-P" in result.output  # letter made, no résumé forged

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
        _with_contacts()

        runner = CliRunner()
        runner.invoke(cli, ["provision", "--id", str(new_id)])

        result = runner.invoke(cli, ["offerings", "--id", str(new_id)])
        assert result.exit_code == 0
        assert "cover_letter.docx" in result.output

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
