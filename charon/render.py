"""Render an offering's resume.md and cover_letter.md to styled HTML.

Pure deterministic conversion. No LLM calls. Walks the markdown-it-py token
stream and emits HTML matching the skeleton structure in
``charon/templates/{resume,cover-letter}-skeleton.html``. The shared CSS is
inlined into a ``<style>`` block so each .html file is self-contained.

User flow: ``charon render --id N`` → open the .html files in a browser →
File → Print → "Save as PDF" → upload to the recruiter's portal.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from markdown_it import MarkdownIt
from markdown_it.token import Token


TEMPLATES_DIR = Path(__file__).parent / "templates"
CSS_FILENAME = "charon-document-style.css"


# Separators in identity lines (tagline + contact rows). The generated
# markdown sometimes mixes `|` and `·`; treat both as separators here.
IDENTITY_SEP_RE = re.compile(r"\s+[|·]\s+")

# `**Role** | Company | Date · Location` — experience entry-head split.
PIPE_SEP_RE = re.compile(r"\s+\|\s+")

# `**Title** · Subtitle · meta` — project / competition entry-head split.
DOT_SEP_RE = re.compile(r"\s+·\s+")

URL_RE = re.compile(r"^(https?://)?[\w.-]+\.[a-z]{2,}(/[\w./?=&%#+-]*)?$", re.I)
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w.-]+\.\w+$")


class RenderError(Exception):
    """Raised when rendering can't produce sensible output."""


# ── markdown parsing helpers ────────────────────────────────────────


def _parse(md_text: str) -> list[Token]:
    md = MarkdownIt("commonmark", {"html": False, "breaks": False})
    return md.parse(md_text)


def _h2_indices(tokens: list[Token]) -> list[int]:
    return [
        i for i, t in enumerate(tokens)
        if t.type == "heading_open" and t.tag == "h2"
    ]


def _split_inline_into_lines(inline_token: Token) -> list[list[Token]]:
    """Split an inline token's children by softbreak into logical lines."""
    lines: list[list[Token]] = []
    current: list[Token] = []
    for child in inline_token.children or []:
        if child.type == "softbreak":
            lines.append(current)
            current = []
        else:
            current.append(child)
    lines.append(current)
    return lines


def _inline_text(children: Iterable[Token]) -> str:
    """Plain-text from inline children. Drops formatting markers."""
    parts: list[str] = []
    for t in children:
        if t.type == "text":
            parts.append(t.content)
        elif t.type in ("strong_open", "strong_close", "em_open", "em_close",
                        "link_open", "link_close"):
            continue
        elif t.type == "softbreak":
            parts.append(" ")
        elif t.type == "code_inline":
            parts.append(t.content)
        else:
            parts.append(getattr(t, "content", "") or "")
    return "".join(parts)


def _inline_html(children: Iterable[Token]) -> str:
    """Render inline children to HTML, preserving bold/italic/links."""
    out: list[str] = []
    for t in children:
        if t.type == "text":
            out.append(_html.escape(t.content, quote=False))
        elif t.type == "strong_open":
            out.append("<strong>")
        elif t.type == "strong_close":
            out.append("</strong>")
        elif t.type == "em_open":
            out.append("<em>")
        elif t.type == "em_close":
            out.append("</em>")
        elif t.type == "softbreak":
            out.append(" ")
        elif t.type == "code_inline":
            out.append(f"<code>{_html.escape(t.content, quote=False)}</code>")
        elif t.type == "link_open":
            href = (t.attrs or {}).get("href", "") if isinstance(t.attrs, dict) else ""
            out.append(f'<a href="{_html.escape(href, quote=True)}">')
        elif t.type == "link_close":
            out.append("</a>")
        else:
            out.append(_html.escape(getattr(t, "content", "") or "", quote=False))
    return "".join(out)


def _walk_blocks(tokens: list[Token]) -> Iterable[tuple[str, list[Token]]]:
    """Yield (block_kind, block_slice) for each top-level block.

    block_kind ∈ {'paragraph', 'bullet_list', 'other'}. Uses token `level` to
    find matching closing tokens — top-level blocks have level 0.
    """
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "paragraph_open" and t.level == 0:
            j = i + 1
            while j < len(tokens) and not (
                tokens[j].type == "paragraph_close" and tokens[j].level == 0
            ):
                j += 1
            yield ("paragraph", tokens[i:j + 1])
            i = j + 1
        elif t.type == "bullet_list_open" and t.level == 0:
            j = i + 1
            while j < len(tokens) and not (
                tokens[j].type == "bullet_list_close" and tokens[j].level == 0
            ):
                j += 1
            yield ("bullet_list", tokens[i:j + 1])
            i = j + 1
        else:
            yield ("other", [t])
            i += 1


def _paragraph_inline(paragraph_slice: list[Token]) -> Token | None:
    """The inline token inside a [paragraph_open, inline, paragraph_close] slice."""
    for t in paragraph_slice:
        if t.type == "inline":
            return t
    return None


def _is_entry_head(paragraph_slice: list[Token]) -> bool:
    """Entry-head paragraphs start with bold text (e.g. '**Role**...')."""
    inline = _paragraph_inline(paragraph_slice)
    return bool(inline and inline.content.lstrip().startswith("**"))


# ── identity header ─────────────────────────────────────────────────


@dataclass
class _Identity:
    name: str = ""
    tagline_parts: list[str] = field(default_factory=list)
    contact_rows: list[list[str]] = field(default_factory=list)


def _parse_identity(tokens: list[Token]) -> _Identity:
    """Parse the leading identity block (everything before the first H2)."""
    ident = _Identity()
    identity_lines: list[str] = []

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.type == "heading_open" and t.tag == "h1":
            ident.name = tokens[i + 1].content.strip()
            i += 3
            continue
        if t.type == "paragraph_open":
            inline = tokens[i + 1]
            for line_tokens in _split_inline_into_lines(inline):
                line_text = _inline_text(line_tokens).strip()
                if line_text:
                    identity_lines.append(line_text)
            # Skip past paragraph_close
            i += 3
            continue
        if t.type == "heading_open":
            break  # hit a section, identity done
        i += 1

    if not ident.name and identity_lines:
        # Cover-letter pattern: first plain line is the name
        ident.name = identity_lines[0]
        identity_lines = identity_lines[1:]

    if identity_lines:
        ident.tagline_parts = [
            p.strip()
            for p in IDENTITY_SEP_RE.split(identity_lines[0])
            if p.strip()
        ]
        for line in identity_lines[1:]:
            parts = [p.strip() for p in IDENTITY_SEP_RE.split(line) if p.strip()]
            if parts:
                ident.contact_rows.append(parts)

    return ident


def _make_contact_item(text: str) -> str:
    t = text.strip()
    if EMAIL_RE.match(t):
        return (
            f'<a href="mailto:{_html.escape(t, quote=True)}">'
            f'{_html.escape(t, quote=False)}</a>'
        )
    if URL_RE.match(t):
        href = t if t.startswith("http") else f"https://{t}"
        return (
            f'<a href="{_html.escape(href, quote=True)}">'
            f'{_html.escape(t, quote=False)}</a>'
        )
    return _html.escape(t, quote=False)


def _render_identity_html(ident: _Identity) -> str:
    lines = ['<header class="identity">']
    lines.append(f'  <div class="name">{_html.escape(ident.name, quote=False)}</div>')

    if ident.tagline_parts:
        sep = '<span class="sep">|</span>'
        joined = sep.join(_html.escape(p, quote=False) for p in ident.tagline_parts)
        lines.append(f'  <div class="tagline">{joined}</div>')

    if ident.contact_rows:
        lines.append('  <div class="contact">')
        for row in ident.contact_rows:
            sep = '<span class="sep">·</span>'
            row_html = sep.join(_make_contact_item(p) for p in row)
            lines.append(f'    <div class="contact-row">{row_html}</div>')
        lines.append('  </div>')

    lines.append('</header>')
    return "\n".join(lines)


# ── resume sections ─────────────────────────────────────────────────


def _title_case_section(upper: str) -> str:
    """'PROFESSIONAL SUMMARY' → 'Professional Summary'. CSS uppercases visually."""
    return " ".join(
        w if w in {"&"} else w.capitalize() for w in upper.split()
    )


def _render_summary(content: list[Token]) -> str:
    for kind, blk in _walk_blocks(content):
        if kind == "paragraph":
            inline = _paragraph_inline(blk)
            if inline:
                return f'<p class="summary">{_inline_html(inline.children or [])}</p>'
    return ""


def _split_head_line(text: str, sep_re: re.Pattern[str]) -> list[str]:
    return [p.strip() for p in sep_re.split(text) if p.strip()]


def _render_experience(content: list[Token]) -> str:
    return _render_entries(content, sep_re=PIPE_SEP_RE, head_kind="experience")


def _render_projects(content: list[Token]) -> str:
    return _render_entries(content, sep_re=DOT_SEP_RE, head_kind="project")


def _render_competitions(content: list[Token]) -> str:
    return _render_entries(content, sep_re=DOT_SEP_RE, head_kind="competition")


def _render_entries(
    content: list[Token],
    *,
    sep_re: re.Pattern[str],
    head_kind: str,
) -> str:
    """Group blocks under entry-head paragraphs and render each as a .entry div."""
    blocks = list(_walk_blocks(content))

    entries: list[list[tuple[str, list[Token]]]] = []
    current: list[tuple[str, list[Token]]] = []

    for kind, blk in blocks:
        if kind == "paragraph" and _is_entry_head(blk):
            if current:
                entries.append(current)
            current = [(kind, blk)]
        else:
            if current:
                current.append((kind, blk))
            # If no entry-head yet, ignore stray blocks (forge prompt prepends nothing)
    if current:
        entries.append(current)

    return "\n  ".join(_render_one_entry(e, sep_re, head_kind) for e in entries)


def _render_one_entry(
    blocks: list[tuple[str, list[Token]]],
    sep_re: re.Pattern[str],
    head_kind: str,
) -> str:
    head_kind_blk = blocks[0][1]
    head_text = _inline_text(_paragraph_inline(head_kind_blk).children or [])
    parts = _split_head_line(head_text, sep_re)

    # Distribute parts into title / .at / meta based on count
    title = parts[0] if parts else ""
    title_at = ""
    meta = ""
    if head_kind == "experience":
        # `Role | Company | Date · Location`
        if len(parts) == 2:
            meta = parts[1]
        elif len(parts) >= 3:
            title_at = "| " + " | ".join(parts[1:-1])
            meta = parts[-1]
    else:
        # `Title · Subtitle [· meta]`
        if len(parts) == 2:
            title_at = "· " + parts[1]
        elif len(parts) >= 3:
            title_at = "· " + " · ".join(parts[1:-1])
            meta = parts[-1]

    # Build entry-head
    head_html_parts = ['<div class="entry-head">']
    if title_at:
        head_html_parts.append(
            f'    <div class="entry-title">{_html.escape(title, quote=False)} '
            f'<span class="at">{_html.escape(title_at, quote=False)}</span></div>'
        )
    else:
        head_html_parts.append(
            f'    <div class="entry-title">{_html.escape(title, quote=False)}</div>'
        )
    if meta:
        meta_class, meta_html = _meta_slot_html(meta, head_kind)
        head_html_parts.append(
            f'    <div class="entry-meta{meta_class}">{meta_html}</div>'
        )
    head_html_parts.append('  </div>')

    # Walk remaining blocks: first paragraph → entry-lead, rest → bullets
    lead_html = ""
    bullet_items: list[str] = []
    real_list_html = ""

    body_blocks = blocks[1:]
    for kind, blk in body_blocks:
        if kind == "paragraph":
            inline = _paragraph_inline(blk)
            if inline is None:
                continue
            para_html = _inline_html(inline.children or [])
            if not lead_html:
                lead_html = para_html
            else:
                bullet_items.append(para_html)
        elif kind == "bullet_list":
            # If forge ever produces real bullet lists, honor them as <ul><li>
            real_list_html = _render_bullet_list_tokens(blk)

    # Compose body
    body_parts = []
    if lead_html:
        body_parts.append(f'  <p class="entry-lead">{lead_html}</p>')
    if bullet_items:
        items = "\n".join(f"    <li>{b}</li>" for b in bullet_items)
        body_parts.append(f"  <ul>\n{items}\n  </ul>")
    if real_list_html:
        body_parts.append(real_list_html)

    inner = "\n".join(head_html_parts + body_parts)
    return f'<div class="entry">\n  {inner}\n  </div>'


def _meta_slot_html(meta_text: str, head_kind: str) -> tuple[str, str]:
    """Decide the meta slot's CSS class and inner HTML."""
    meta_text = meta_text.strip()
    if head_kind == "experience":
        # Plain date · location text
        return ("", _html.escape(meta_text, quote=False))
    if URL_RE.match(meta_text):
        href = meta_text if meta_text.startswith("http") else f"https://{meta_text}"
        return (
            " project-url",
            f'<a href="{_html.escape(href, quote=True)}">'
            f'{_html.escape(meta_text, quote=False)}</a>',
        )
    return (" project-tag", _html.escape(meta_text, quote=False))


def _render_bullet_list_tokens(list_slice: list[Token]) -> str:
    """Render a bullet_list token slice to <ul><li>...</li></ul>."""
    items: list[str] = []
    i = 0
    while i < len(list_slice):
        if list_slice[i].type == "list_item_open":
            j = i + 1
            while j < len(list_slice) and list_slice[j].type != "list_item_close":
                j += 1
            # Collect inline content from paragraphs inside the item
            item_html_parts: list[str] = []
            for sub_kind, sub_blk in _walk_blocks(list_slice[i + 1:j]):
                if sub_kind == "paragraph":
                    inline = _paragraph_inline(sub_blk)
                    if inline:
                        item_html_parts.append(_inline_html(inline.children or []))
            items.append("    <li>" + " ".join(item_html_parts) + "</li>")
            i = j + 1
        else:
            i += 1
    if not items:
        return ""
    return "  <ul>\n" + "\n".join(items) + "\n  </ul>"


def _render_compact_block(content: list[Token]) -> str:
    """Compact-block sections: certifications, technical skills.

    Each paragraph becomes a `<div class="row">`. Lines starting with
    'In progress:' get a `<span class="label">In Progress</span>` prefix.
    Items separated by ` · ` are joined with `<span class="dot">·</span>`.
    """
    rows: list[str] = []
    for kind, blk in _walk_blocks(content):
        if kind != "paragraph":
            continue
        inline = _paragraph_inline(blk)
        if not inline:
            continue
        text = _inline_text(inline.children or []).strip()
        if not text:
            continue

        m = re.match(r"^([^:]+):\s+(.+)$", text)
        if m and m.group(1).strip().lower() in {"in progress", "active"}:
            label = m.group(1).strip().title()
            rest = m.group(2).strip()
            rows.append(
                f'    <div class="row"><span class="label">{_html.escape(label, quote=False)}'
                f'</span>{_html.escape(rest, quote=False)}</div>'
            )
            continue

        parts = [p.strip() for p in DOT_SEP_RE.split(text) if p.strip()]
        if len(parts) > 1:
            row_html = '<span class="dot">·</span>'.join(
                _html.escape(p, quote=False) for p in parts
            )
            rows.append(f'    <div class="row">{row_html}</div>')
        else:
            rows.append(f'    <div class="row">{_html.escape(parts[0], quote=False)}</div>')

    if not rows:
        return ""
    return '<div class="compact-block">\n' + "\n".join(rows) + "\n  </div>"


def _render_education(content: list[Token]) -> str:
    """Education block.

    Markdown shape:
        Degree | Graduated Month Year
        School · accreditation · accreditation

        Honors: ...

    The first paragraph has a softbreak between the two lines. Subsequent
    paragraphs (e.g. 'Honors:') become additional .accred divs.
    """
    degree = ""
    grad = ""
    school = ""
    accred_lines: list[str] = []

    blocks = list(_walk_blocks(content))
    if blocks:
        kind, first_blk = blocks[0]
        if kind == "paragraph":
            inline = _paragraph_inline(first_blk)
            if inline:
                lines = [_inline_text(L) for L in _split_inline_into_lines(inline)]
                lines = [L.strip() for L in lines if L.strip()]
                if lines:
                    first_parts = _split_head_line(lines[0], PIPE_SEP_RE)
                    if len(first_parts) >= 2:
                        degree = first_parts[0]
                        grad = " ".join(first_parts[1:])
                    else:
                        degree = lines[0]
                if len(lines) >= 2:
                    school_parts = _split_head_line(lines[1], DOT_SEP_RE)
                    if school_parts:
                        school = school_parts[0]
                        if len(school_parts) > 1:
                            accred_lines.append(" · ".join(school_parts[1:]))

    for kind, blk in blocks[1:]:
        if kind != "paragraph":
            continue
        inline = _paragraph_inline(blk)
        if inline:
            text = _inline_text(inline.children or []).strip()
            if text:
                accred_lines.append(text)

    out = ['<div class="edu-block entry">']
    out.append('    <div class="entry-head">')
    out.append('      <div>')
    if degree:
        out.append(f'        <div class="degree">{_html.escape(degree, quote=False)}</div>')
    if school:
        out.append(f'        <div class="school">{_html.escape(school, quote=False)}</div>')
    for line in accred_lines:
        out.append(f'        <div class="accred">{_html.escape(line, quote=False)}</div>')
    out.append('      </div>')
    if grad:
        out.append(f'      <div class="grad">{_html.escape(grad, quote=False)}</div>')
    out.append('    </div>')
    out.append('  </div>')
    return "\n".join(out)


def _render_generic_section(content: list[Token]) -> str:
    """Fallback for unrecognized sections: dump as <p>s."""
    parts: list[str] = []
    for kind, blk in _walk_blocks(content):
        if kind == "paragraph":
            inline = _paragraph_inline(blk)
            if inline:
                parts.append(f'<p>{_inline_html(inline.children or [])}</p>')
    return "\n  ".join(parts)


_SECTION_DISPATCH: dict[str, callable] = {
    "PROFESSIONAL SUMMARY": _render_summary,
    "EXPERIENCE": _render_experience,
    "SECURITY RESEARCH & PROJECTS": _render_projects,
    "PROJECTS": _render_projects,
    "CERTIFICATIONS": _render_compact_block,
    "TECHNICAL SKILLS": _render_compact_block,
    "SKILLS": _render_compact_block,
    "EDUCATION": _render_education,
    "COMPETITIONS & ACTIVITIES": _render_competitions,
    "COMPETITIONS": _render_competitions,
    "ACTIVITIES": _render_competitions,
}


def _render_section(section_tokens: list[Token]) -> str:
    """Render one h2-bounded section. `section_tokens[0]` is heading_open."""
    if not section_tokens or section_tokens[0].type != "heading_open":
        return ""
    name_upper = section_tokens[1].content.strip()
    name_title = _title_case_section(name_upper)
    content_tokens = section_tokens[3:]
    renderer = _SECTION_DISPATCH.get(name_upper.upper(), _render_generic_section)
    body = renderer(content_tokens)
    return (
        '<section>\n'
        f'  <h2 class="section">{_html.escape(name_title, quote=False)}</h2>\n'
        f'  {body}\n'
        '</section>'
    )


# ── document wrappers ───────────────────────────────────────────────


def _document_html(body_class: str, inner_html: str, css: str, title: str) -> str:
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '  <meta charset="UTF-8">\n'
        f'  <title>{_html.escape(title, quote=False)}</title>\n'
        '  <style>\n'
        f'{css}\n'
        '  </style>\n'
        '</head>\n'
        f'<body class="document {body_class}">\n'
        '  <div class="page">\n'
        f'{inner_html}\n'
        '  </div>\n'
        '</body>\n'
        '</html>\n'
    )


def render_resume_html(md_text: str, css: str) -> str:
    tokens = _parse(md_text)
    h2s = _h2_indices(tokens)
    identity_tokens = tokens[:h2s[0]] if h2s else tokens
    ident = _parse_identity(identity_tokens)
    identity_html = _render_identity_html(ident)

    section_html_parts: list[str] = []
    for idx, start in enumerate(h2s):
        end = h2s[idx + 1] if idx + 1 < len(h2s) else len(tokens)
        section_html_parts.append(_render_section(tokens[start:end]))

    inner = identity_html + "\n" + "\n".join(section_html_parts)
    name = ident.name or "Resume"
    return _document_html("resume", inner, css, title=f"Resume — {name}")


def render_cover_letter_html(
    md_text: str,
    css: str,
    *,
    fallback_identity_md: str | None = None,
) -> str:
    tokens = _parse(md_text)
    h2s = _h2_indices(tokens)

    if h2s:
        identity_tokens = tokens[:h2s[0]]
        body_tokens = tokens[h2s[0]:]
    else:
        # No headings — the cover letter is plain paragraphs.
        # First paragraph is treated as the identity (name + possible tagline/contact via softbreaks);
        # remaining paragraphs are the body.
        blocks = list(_walk_blocks(tokens))
        if blocks:
            first_kind, first_blk = blocks[0]
            if first_kind == "paragraph":
                identity_tokens = first_blk
                # body starts after the first paragraph block in the original tokens
                first_close = next(
                    (i for i, t in enumerate(tokens)
                     if t.type == "paragraph_close" and t.level == 0),
                    None,
                )
                body_tokens = tokens[first_close + 1:] if first_close is not None else []
            else:
                identity_tokens = []
                body_tokens = tokens
        else:
            identity_tokens = []
            body_tokens = []

    ident = _parse_identity(identity_tokens)

    # Fall back to resume.md's identity if the cover letter is missing tagline/contact
    if fallback_identity_md and (not ident.tagline_parts or not ident.contact_rows):
        fallback_tokens = _parse(fallback_identity_md)
        fb_h2s = _h2_indices(fallback_tokens)
        fb_identity_tokens = fallback_tokens[:fb_h2s[0]] if fb_h2s else fallback_tokens
        fb_ident = _parse_identity(fb_identity_tokens)
        if not ident.name:
            ident.name = fb_ident.name
        if not ident.tagline_parts:
            ident.tagline_parts = fb_ident.tagline_parts
        if not ident.contact_rows:
            ident.contact_rows = fb_ident.contact_rows

    identity_html = _render_identity_html(ident)

    today = date.today().strftime("%B %d, %Y").replace(" 0", " ")
    meta_html = (
        '<div class="meta-row">\n'
        '  <div class="label">Cover Letter</div>\n'
        f'  <div class="date">{today}</div>\n'
        '</div>'
    )

    body_html_parts: list[str] = []
    for kind, blk in _walk_blocks(body_tokens):
        if kind == "paragraph":
            inline = _paragraph_inline(blk)
            if inline:
                body_html_parts.append(
                    f'  <p>{_inline_html(inline.children or [])}</p>'
                )
    body_html = '<div class="body">\n' + "\n".join(body_html_parts) + "\n</div>"

    name = ident.name or ""
    closing_html = (
        '<div class="closing">\n'
        '  <div class="signoff">Best regards,</div>\n'
        f'  <div class="signature">{_html.escape(name, quote=False)}</div>\n'
        '</div>'
    )

    inner = (
        identity_html + "\n"
        + meta_html + "\n"
        + body_html + "\n"
        + closing_html
    )
    return _document_html(
        "cover-letter", inner, css, title=f"Cover Letter — {name}" if name else "Cover Letter"
    )


# ── high-level entry point ──────────────────────────────────────────


def _load_css() -> str:
    css_path = TEMPLATES_DIR / CSS_FILENAME
    if not css_path.exists():
        raise RenderError(
            f"Stylesheet not found: {css_path}. "
            "charon/templates/ must contain charon-document-style.css."
        )
    return css_path.read_text(encoding="utf-8")


def render_offering(discovery_id: int) -> dict[str, str | None]:
    """Render resume.html and cover_letter.html for a discovery's offering.

    Returns a dict with keys 'resume_path', 'cover_letter_path', 'errors'.
    Either path may be None if the corresponding .md is missing.
    """
    from charon.db import get_discovery

    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise RenderError(f"No discovery with id {discovery_id}.")
    folder_str = discovery.get("offerings_path")
    if not folder_str:
        raise RenderError(
            f"No offerings folder recorded for #{discovery_id}. "
            f"Run 'charon provision --id {discovery_id}' first."
        )
    folder = Path(folder_str)
    if not folder.exists():
        raise RenderError(
            f"Offerings folder is recorded but missing on disk: {folder}\n"
            "Re-run 'charon provision' to regenerate."
        )

    css = _load_css()
    result: dict[str, str | None] = {
        "resume_path": None,
        "cover_letter_path": None,
        "folder": str(folder),
        "errors": [],
    }

    resume_md_path = folder / "resume.md"
    letter_md_path = folder / "cover_letter.md"

    resume_md_text: str | None = None
    if resume_md_path.exists():
        resume_md_text = resume_md_path.read_text(encoding="utf-8")
        try:
            html_out = render_resume_html(resume_md_text, css)
            out_path = folder / "resume.html"
            out_path.write_text(html_out, encoding="utf-8")
            result["resume_path"] = str(out_path)
        except Exception as e:  # noqa: BLE001 — report rather than crash
            result["errors"].append(f"resume.md → resume.html failed: {e}")

    if letter_md_path.exists():
        letter_md_text = letter_md_path.read_text(encoding="utf-8")
        try:
            html_out = render_cover_letter_html(
                letter_md_text, css, fallback_identity_md=resume_md_text
            )
            out_path = folder / "cover_letter.html"
            out_path.write_text(html_out, encoding="utf-8")
            result["cover_letter_path"] = str(out_path)
        except Exception as e:  # noqa: BLE001
            result["errors"].append(f"cover_letter.md → cover_letter.html failed: {e}")

    return result


__all__ = [
    "RenderError",
    "render_offering",
    "render_resume_html",
    "render_cover_letter_html",
]
