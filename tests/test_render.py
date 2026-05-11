"""Tests for charon.render — deterministic markdown → HTML conversion."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from charon.render import (
    _load_css,
    render_cover_letter_html,
    render_resume_html,
)


RESUME_MD = """# DeAnna Shanks

Cybersecurity Analyst  |  Digital Forensics & Incident Response

dshanks@duck.com  ·  423-534-3535  |  Johnson City, TN
linkedin.com/in/deanna-shanks  ·  github.com/test

## PROFESSIONAL SUMMARY

A one-paragraph summary of who this person is.

## EXPERIENCE

**Senior Credit & Fraud Analyst**  |  Citi Group  |  Oct 2016 – Dec 2021  •  Remote

Lead paragraph orienting the reader.

First accomplishment bullet.

Second accomplishment bullet.

## SECURITY RESEARCH & PROJECTS

**PuppetString**  ·  Red Team Toolkit  ·  github.com/Port53-Cosplay/PuppetString

A project description paragraph.

**Charon**  ·  Job Search CLI (in daily use)

Another project description.

## CERTIFICATIONS

In progress: ISACA CISA

CompTIA PenTest+  ·  CompTIA CySA+  ·  ISC2 SSCP

## TECHNICAL SKILLS

Incident Response  ·  Digital Forensics  ·  Threat Hunting

## EDUCATION

B.S. Cybersecurity  |  Graduated March 2026
Western Governors University  ·  NSA/DHS CAE-IA Designated Institution

Honors: NSA Validated PoS
"""


LETTER_MD = """DeAnna Shanks

Opening paragraph that hooks the reader.

Second paragraph about relevant experience.

Final paragraph with availability close.
"""


@pytest.fixture
def css() -> str:
    return _load_css()


# ── document scaffolding ───────────────────────────────────────────


class TestDocumentScaffold:
    def test_resume_has_doctype_and_body_class(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert html.startswith("<!DOCTYPE html>")
        assert '<body class="document resume">' in html
        assert '<div class="page">' in html

    def test_cover_letter_has_doctype_and_body_class(self, css):
        html = render_cover_letter_html(LETTER_MD, css)
        assert html.startswith("<!DOCTYPE html>")
        assert '<body class="document cover-letter">' in html

    def test_css_is_inlined_not_linked(self, css):
        for html in [
            render_resume_html(RESUME_MD, css),
            render_cover_letter_html(LETTER_MD, css),
        ]:
            assert 'rel="stylesheet"' not in html
            # CSS variables from the stylesheet should appear inline
            assert "--accent:" in html
            assert "<style>" in html

    def test_title_includes_name(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert "<title>Resume — DeAnna Shanks</title>" in html


# ── identity header ────────────────────────────────────────────────


class TestIdentity:
    def test_name_pulled_from_h1(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<div class="name">DeAnna Shanks</div>' in html

    def test_tagline_uses_pipe_separator(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<span class="sep">|</span>' in html
        assert "Cybersecurity Analyst" in html
        assert "Digital Forensics &amp; Incident Response" in html  # ampersand escaped

    def test_email_wrapped_in_mailto_anchor(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<a href="mailto:dshanks@duck.com">dshanks@duck.com</a>' in html

    def test_url_wrapped_in_https_anchor(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<a href="https://linkedin.com/in/deanna-shanks">' in html
        assert '<a href="https://github.com/test">' in html

    def test_contact_row_separator_is_middot(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<span class="sep">·</span>' in html

    def test_cover_letter_uses_resume_fallback_for_identity(self, css):
        html = render_cover_letter_html(LETTER_MD, css, fallback_identity_md=RESUME_MD)
        # The letter_md has only the name; tagline/contact should come from resume
        assert "Cybersecurity Analyst" in html
        assert "dshanks@duck.com" in html

    def test_cover_letter_without_fallback_renders_name_only(self, css):
        html = render_cover_letter_html(LETTER_MD, css, fallback_identity_md=None)
        assert '<div class="name">DeAnna Shanks</div>' in html
        # No tagline since the cover letter md doesn't include one.
        # Slice to the rendered body — the inlined CSS file contains example
        # HTML strings in its documentation comments.
        body = html.split("</style>", 1)[1]
        assert '<div class="tagline">' not in body


# ── resume sections ────────────────────────────────────────────────


class TestSections:
    def test_section_names_are_title_cased(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<h2 class="section">Professional Summary</h2>' in html
        assert '<h2 class="section">Experience</h2>' in html
        assert '<h2 class="section">Security Research &amp; Projects</h2>' in html

    def test_summary_renders_as_summary_p(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<p class="summary">A one-paragraph summary' in html


class TestExperience:
    def test_entry_head_splits_on_pipe(self, css):
        html = render_resume_html(RESUME_MD, css)
        # Role | Company → Role in title, "| Company" in .at
        assert '<div class="entry-title">Senior Credit &amp; Fraud Analyst <span class="at">| Citi Group</span></div>' in html

    def test_date_location_become_entry_meta(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<div class="entry-meta">Oct 2016 – Dec 2021  •  Remote</div>' in html

    def test_first_paragraph_is_lead_rest_become_bullets(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<p class="entry-lead">Lead paragraph orienting the reader.</p>' in html
        assert "<li>First accomplishment bullet.</li>" in html
        assert "<li>Second accomplishment bullet.</li>" in html


class TestProjects:
    def test_project_with_url_gets_project_url_class(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert 'class="entry-meta project-url"' in html
        assert '<a href="https://github.com/Port53-Cosplay/PuppetString">' in html

    def test_project_with_subtitle_only_has_at_span_no_meta(self, css):
        html = render_resume_html(RESUME_MD, css)
        # Charon line: Title · Subtitle, no URL meta
        assert '<div class="entry-title">Charon <span class="at">· Job Search CLI (in daily use)</span></div>' in html


class TestCompactBlocks:
    def test_in_progress_gets_label_span(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<span class="label">In Progress</span>ISACA CISA' in html

    def test_dotted_list_uses_dot_spans(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert 'CompTIA PenTest+<span class="dot">·</span>CompTIA CySA+' in html

    def test_skills_section_renders_compact_block(self, css):
        html = render_resume_html(RESUME_MD, css)
        # Find the Technical Skills section and confirm compact-block follows
        assert '<h2 class="section">Technical Skills</h2>' in html
        assert 'Incident Response<span class="dot">·</span>Digital Forensics' in html


class TestEducation:
    def test_education_block_structure(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert '<div class="edu-block entry">' in html
        assert '<div class="degree">B.S. Cybersecurity</div>' in html
        assert '<div class="school">Western Governors University</div>' in html
        assert '<div class="grad">Graduated March 2026</div>' in html

    def test_honors_renders_as_extra_accred_line(self, css):
        html = render_resume_html(RESUME_MD, css)
        # Both the school's accreditation and the Honors line should be accred divs
        assert html.count('<div class="accred">') == 2
        assert "NSA/DHS CAE-IA Designated Institution" in html
        assert "Honors: NSA Validated PoS" in html


# ── cover letter ───────────────────────────────────────────────────


class TestCoverLetter:
    def test_body_paragraphs_wrapped(self, css):
        html = render_cover_letter_html(LETTER_MD, css, fallback_identity_md=RESUME_MD)
        assert "<p>Opening paragraph that hooks the reader.</p>" in html
        assert "<p>Final paragraph with availability close.</p>" in html

    def test_meta_row_present(self, css):
        html = render_cover_letter_html(LETTER_MD, css, fallback_identity_md=RESUME_MD)
        assert '<div class="meta-row">' in html
        assert '<div class="label">Cover Letter</div>' in html
        # Today's date is rendered — format check, not specific date
        assert re.search(r'<div class="date">[A-Z][a-z]+ \d{1,2}, \d{4}</div>', html)

    def test_closing_includes_signature_from_name(self, css):
        html = render_cover_letter_html(LETTER_MD, css, fallback_identity_md=RESUME_MD)
        assert '<div class="signoff">Best regards,</div>' in html
        assert '<div class="signature">DeAnna Shanks</div>' in html

    def test_body_excludes_name_paragraph(self, css):
        html = render_cover_letter_html(LETTER_MD, css, fallback_identity_md=RESUME_MD)
        # The body div should not contain a paragraph that is just the name
        body_match = re.search(r'<div class="body">(.*?)</div>', html, re.DOTALL)
        assert body_match
        assert "<p>DeAnna Shanks</p>" not in body_match.group(1)


# ── escaping & resilience ──────────────────────────────────────────


class TestEscaping:
    def test_ampersand_in_section_name_escapes(self, css):
        html = render_resume_html(RESUME_MD, css)
        assert "Security Research &amp; Projects" in html
        assert "Security Research & Projects" not in html.replace("&amp;", "")  # actually escaped, not raw

    def test_em_dash_passes_through(self, css):
        md = "# Name\n\n## EXPERIENCE\n\n**Role** | Co | 2020 – 2024\n\nDid stuff."
        html = render_resume_html(md, css)
        assert "2020 – 2024" in html  # em-dash preserved


class TestResilience:
    def test_missing_sections_dont_crash(self, css):
        md = "# Name\n\n## PROFESSIONAL SUMMARY\n\nJust a summary."
        html = render_resume_html(md, css)
        assert '<p class="summary">Just a summary.</p>' in html
        assert "<title>Resume — Name</title>" in html

    def test_cover_letter_without_h1_still_extracts_name(self, css):
        md = "Plain Name\n\nFirst paragraph."
        html = render_cover_letter_html(md, css)
        assert '<div class="name">Plain Name</div>' in html
