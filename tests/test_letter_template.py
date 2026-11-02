"""The blank cover letter template, and Prep on the Ready card.

She writes her own letters now. Prep attaches the résumé and builds a .docx
with the résumé's letterhead, a greeting addressed from the company contacts
search, and highlighted reminders. No LLM writes anything. A company with no
contacts on file gets searched first, on a thread, since that search outlasts
Cloudflare's request limit.
"""

import time
from datetime import date
from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt

from charon import dashboard
from charon.db import add_discovery, save_history, update_discovery_judgement
from charon.letter_template import (
    REMINDERS,
    build_letter_template,
    greeting_for,
    pick_addressee,
)


def _make_resume(path: Path) -> Path:
    """A résumé shaped like hers: letterhead, then all-caps bold sections."""
    doc = Document()
    name = doc.add_paragraph().add_run("DeAnna Shanks")
    name.bold = True
    name.font.size = Pt(28)
    doc.add_paragraph("Incident Response  |  DFIR Analyst")
    doc.add_paragraph("dshanks@example.com  ·  555-0100")
    doc.add_paragraph()
    doc.add_paragraph().add_run("PROFESSIONAL SUMMARY").bold = True
    doc.add_paragraph("Five years of financial crimes investigation.")
    doc.add_paragraph().add_run("EXPERIENCE").bold = True
    doc.add_paragraph("Citi, fraud investigator.")
    doc.save(str(path))
    return path


def _texts(path: Path) -> list[str]:
    return [p.text for p in Document(str(path)).paragraphs]


CONTACTS = {
    "contacts": [
        {"name": "Pat Practitioner", "category": "practitioner"},
        {"name": "Rae Recruiter", "category": "recruiter"},
        {"name": "Lee Leader", "title": "Head of IR", "category": "security_leadership"},
    ],
    "search_notes": "",
}


class TestAddressee:
    def test_security_leader_beats_recruiter(self):
        assert pick_addressee(CONTACTS)["name"] == "Lee Leader"

    def test_recruiter_when_no_leader(self):
        only = {"contacts": [c for c in CONTACTS["contacts"] if c["category"] != "security_leadership"]}
        assert pick_addressee(only)["name"] == "Rae Recruiter"

    def test_practitioners_alone_are_not_addressed(self):
        only = {"contacts": [CONTACTS["contacts"][0]]}
        assert pick_addressee(only) is None

    @pytest.mark.parametrize("result", [None, {}, {"contacts": None}, {"contacts": ["junk"]}])
    def test_empty_or_malformed_results(self, result):
        assert pick_addressee(result) is None

    def test_greetings(self):
        assert greeting_for("Acme", {"name": "Lee Leader"}) == "Dear Lee Leader,"
        assert greeting_for("Acme", None) == "Dear Acme Security Team,"
        assert greeting_for("", None) == "Dear Hiring Team,"
        assert greeting_for("GuidePoint Security", None) == "Dear GuidePoint Security Team,"


class TestTemplate:
    def test_keeps_letterhead_drops_resume_body(self, tmp_path):
        resume = _make_resume(tmp_path / "resume.docx")
        out = tmp_path / "cover_letter.docx"
        build_letter_template(
            {"company": "Acme", "role": "IR Consultant"}, resume, out,
            addressee={"name": "Lee Leader"}, today=date(2026, 10, 6),
        )
        texts = _texts(out)
        assert texts[:3] == [
            "DeAnna Shanks", "Incident Response  |  DFIR Analyst", "dshanks@example.com  ·  555-0100",
        ]
        assert "PROFESSIONAL SUMMARY" not in texts
        assert not any("Citi" in t for t in texts)
        assert "October 6, 2026" in texts
        assert "Re: IR Consultant, Acme" in texts
        assert "Dear Lee Leader," in texts
        assert texts[-2:] == [REMINDERS[-1], "DeAnna Shanks"]  # no closing word

    def test_reminders_are_highlighted(self, tmp_path):
        out = tmp_path / "cover_letter.docx"
        build_letter_template({"company": "Acme", "role": "x"}, _make_resume(tmp_path / "r.docx"), out)
        doc = Document(str(out))
        found = {p.text: p.runs[0].font.highlight_color for p in doc.paragraphs if p.text in REMINDERS}
        assert set(found) == set(REMINDERS)
        assert all(color == WD_COLOR_INDEX.YELLOW for color in found.values())

    def test_page_setup_survives(self, tmp_path):
        resume = _make_resume(tmp_path / "r.docx")
        out = tmp_path / "cover_letter.docx"
        build_letter_template({"company": "Acme", "role": "x"}, resume, out)
        assert Document(str(out)).sections[0].page_width == Document(str(resume)).sections[0].page_width

    def test_rejects_non_docx_resume(self, tmp_path):
        md = tmp_path / "resume.md"
        md.write_text("# DeAnna\n", encoding="utf-8")
        with pytest.raises(ValueError):
            build_letter_template({}, md, tmp_path / "out.docx")


# ── Prep on the dashboard ──────────────────────────────────────────────


@pytest.fixture
def prep_env(tmp_path, monkeypatch):
    resume = _make_resume(tmp_path / "source_resume.docx")
    profile = {
        "resumes": {"ir": str(resume)},
        "forge": {"offerings_dir": str(tmp_path / "offerings")},
    }
    monkeypatch.setattr("charon.profile.load_profile", lambda: profile)
    return tmp_path


def _folder_for(rid, base):
    from charon.db import get_discovery
    from charon.tailor import offerings_folder

    return offerings_folder(get_discovery(rid), base_dir=str(base))


def _seed_ready(company="Acme Security", dedupe_hash="prep-1"):
    rid = add_discovery(
        ats="lever", slug="acme", company=company, role="IR Consultant",
        url=f"https://example.com/{dedupe_hash}", dedupe_hash=dedupe_hash,
        location="Remote", description="x" * 900,
    )
    update_discovery_judgement(
        rid, ghost_score=10, redflag_score=10, alignment_score=80,
        combined_score=75.0, screened_status="ready", judgement_reason="ok",
    )
    return rid


def _wait_for_prep(rid, timeout=10):
    deadline = time.monotonic() + timeout
    while dashboard._prep_job_running(rid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return dashboard._prep_job_snapshot(rid)


class TestPrep:
    def test_known_contacts_prep_inline(self, prep_env):
        rid = _seed_ready()
        save_history("contacts", "company", "Acme Security", 3.0, CONTACTS, company="Acme Security")
        started = dashboard._start_prep(rid)
        assert started["pending"] is False
        summary = started["summary"]
        assert summary["errors"] == []
        assert summary["greeting"] == "Dear Lee Leader,"
        folder = Path(summary["offerings_path"])
        assert sorted(p.name for p in folder.iterdir()) == ["cover_letter.docx"]  # no résumé copy

    def test_no_contacts_searches_first(self, prep_env, monkeypatch):
        calls = []

        def fake_research(kind, company, role):
            calls.append((kind, company))
            time.sleep(0.2)
            return save_history("contacts", "company", company, 3.0, CONTACTS, company=company)

        monkeypatch.setattr(dashboard, "_run_research", fake_research)
        rid = _seed_ready(dedupe_hash="prep-2")
        started = dashboard._start_prep(rid)
        assert started["pending"] is True
        job = _wait_for_prep(rid)
        assert calls == [("contacts", "Acme Security")]
        assert job["error"] is None
        assert job["summary"]["greeting"] == "Dear Lee Leader,"

    def test_failed_search_still_gets_a_letter(self, prep_env, monkeypatch):
        def boom(kind, company, role):
            raise RuntimeError("search fell over")

        monkeypatch.setattr(dashboard, "_run_research", boom)
        rid = _seed_ready(dedupe_hash="prep-3")
        assert dashboard._start_prep(rid)["pending"] is True
        job = _wait_for_prep(rid)
        assert job["summary"]["greeting"] == "Dear Acme Security Team,"
        assert job["summary"]["errors"][0].startswith("contacts:")

    def test_existing_letter_is_never_overwritten(self, prep_env):
        rid = _seed_ready(dedupe_hash="prep-4")
        save_history("contacts", "company", "Acme Security", 0.0, {"contacts": []}, company="Acme Security")
        folder = _folder_for(rid, prep_env / "offerings")
        folder.mkdir(parents=True)
        (folder / "cover_letter.docx").write_bytes(b"her draft")
        dashboard._start_prep(rid)
        assert (folder / "cover_letter.docx").read_bytes() == b"her draft"

    def test_ready_payload_offers_the_docx(self, prep_env):
        rid = _seed_ready(dedupe_hash="prep-5")
        save_history("contacts", "company", "Acme Security", 3.0, CONTACTS, company="Acme Security")
        dashboard._start_prep(rid)
        card = next(d for d in dashboard._ready_discoveries() if d["id"] == rid)
        assert card["letter_file"] == "cover_letter.docx"
        assert card["prep_building"] is False

    def test_docx_letter_is_downloadable(self):
        assert "cover_letter.docx" in dashboard._OFFERING_ALLOWED_FILES
