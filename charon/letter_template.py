"""Blank cover letter template — a .docx she writes in herself.

No LLM call. The letterhead is lifted straight from whichever résumé the
posting routed to (name, tagline, contact line, links, rule), so the letter
and résumé match. Below it: date, a Re: line, a greeting addressed from the
company contacts search, a few highlighted reminders to write over, and her
name. No closing word: "Best regards" read as mechanical to her.
"""

from __future__ import annotations

import copy
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.shared import RGBColor

LETTER_FILENAME = "cover_letter.docx"

# Who the greeting goes to, in order. Practitioners and "other" are useful
# people to know, not people to address a letter to.
ADDRESSEE_ORDER = ("security_leadership", "recruiter")

# Highlighted so a missed one is hard to send by accident.
REMINDERS = (
    "[Why this team, this role]",
    "[One story that shows it]",
    "[What you'd want to talk about]",
)

BODY_FONT = "Calibri"
BODY_SIZE = Pt(11)
BODY_COLOR = RGBColor(0x4A, 0x4A, 0x4A)


def pick_addressee(contacts_result: dict[str, Any] | None) -> dict[str, Any] | None:
    """The first security leader, else the first recruiter, else None."""
    contacts = (contacts_result or {}).get("contacts") or []
    for category in ADDRESSEE_ORDER:
        for c in contacts:
            if isinstance(c, dict) and c.get("category") == category and c.get("name"):
                return c
    return None


def greeting_for(company: str | None, addressee: dict[str, Any] | None) -> str:
    if addressee and addressee.get("name"):
        return f"Dear {addressee['name'].strip()},"
    company = (company or "").strip()
    if not company:
        return "Dear Hiring Team,"
    if company.casefold().endswith("security"):
        return f"Dear {company} Team,"
    return f"Dear {company} Security Team,"


def _is_section_heading(paragraph: Any) -> bool:
    """An all-caps bold line like PROFESSIONAL SUMMARY — where the résumé body starts."""
    text = paragraph.text.strip()
    if len(text) < 4 or not any(ch.isalpha() for ch in text) or text != text.upper():
        return False
    return any(r.bold for r in paragraph.runs if r.text.strip())


def _strip_to_letterhead(doc: Any) -> str:
    """Drop everything after the letterhead. Returns the candidate's name."""
    body = doc.element.body
    paragraphs = doc.paragraphs
    cut = next((i for i, p in enumerate(paragraphs) if _is_section_heading(p)), None)
    if cut is None:
        # Not shaped like her résumés; keep only the first line as a header.
        cut = 1 if paragraphs else 0
    name = next((p.text.strip() for p in paragraphs[:cut] if p.text.strip()), "")
    keep = {p._p for p in paragraphs[:cut]}
    for child in list(body):
        if child.tag == qn("w:sectPr") or child in keep:
            continue
        body.remove(child)
    return name


def _add_line(doc: Any, text: str = "", *, after: float = 10, highlight: bool = False) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    if text:
        run = p.add_run(text)
        run.font.name = BODY_FONT
        run.font.size = BODY_SIZE
        run.font.color.rgb = BODY_COLOR
        # python-docx only sets ascii/hAnsi; the résumé's docDefaults are
        # Times New Roman, so pin the rest too.
        rfonts = run._r.get_or_add_rPr().get_or_add_rFonts()
        for attr in ("w:eastAsia", "w:cs"):
            rfonts.set(qn(attr), BODY_FONT)
        if highlight:
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def build_letter_template(
    discovery: dict[str, Any],
    resume_path: Path,
    out_path: Path,
    *,
    addressee: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Write the template to out_path. The résumé must be a .docx."""
    if resume_path.suffix.lower() != ".docx":
        raise ValueError(f"Letterhead comes from a .docx résumé; got {resume_path.name}")
    shutil.copyfile(resume_path, out_path)
    doc = Document(str(out_path))
    name = _strip_to_letterhead(doc)

    today = today or date.today()
    role = (discovery.get("role") or "").strip()
    company = (discovery.get("company") or "").strip()

    _add_line(doc, f"{today:%B} {today.day}, {today.year}", after=14)
    if role:
        _add_line(doc, f"Re: {role}" + (f", {company}" if company else ""), after=14)
    _add_line(doc, greeting_for(company, addressee))
    for reminder in REMINDERS:
        _add_line(doc, reminder, highlight=True)
    if name:
        _add_line(doc, name, after=0)

    doc.save(str(out_path))
    return {
        "letter_path": str(out_path),
        "greeting": greeting_for(company, addressee),
        "addressee": copy.deepcopy(addressee) if addressee else None,
    }


__all__ = [
    "LETTER_FILENAME",
    "REMINDERS",
    "build_letter_template",
    "greeting_for",
    "pick_addressee",
]
