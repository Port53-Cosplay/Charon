"""Tier 1 enrichment: parse JSON-LD JobPosting schema from HTML.

Many ATS pages (Workday especially) embed structured data via
<script type="application/ld+json"> blocks containing a JobPosting
schema (https://schema.org/JobPosting). Parsing that gives us a
clean description with no scraping fragility.
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any

from bs4 import BeautifulSoup


# JobPosting types we recognize. Some sites use the full schema URL.
_JOB_POSTING_TYPES = {"JobPosting", "https://schema.org/JobPosting", "http://schema.org/JobPosting"}


def _iter_json_ld_blocks(soup: BeautifulSoup):
    """Yield each parsed JSON-LD block found in the HTML."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            # Some sites emit JSON with HTML entities; try decoding once
            try:
                yield json.loads(_html.unescape(raw))
            except json.JSONDecodeError:
                continue


def _walk_for_job_posting(node: Any):
    """Walk a JSON-LD structure yielding any JobPosting-typed objects."""
    if isinstance(node, dict):
        type_field = node.get("@type")
        types = type_field if isinstance(type_field, list) else [type_field]
        if any(t in _JOB_POSTING_TYPES for t in types if isinstance(t, str)):
            yield node
        # Recurse into common containers (@graph, mainEntity, etc.)
        for value in node.values():
            yield from _walk_for_job_posting(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_for_job_posting(item)


def _strip_html(html_str: str) -> str:
    """Reduce a JobPosting description (often HTML) to plain text."""
    if not html_str:
        return ""
    decoded = _html.unescape(html_str)
    soup = BeautifulSoup(decoded, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_description(html_str: str) -> str | None:
    """Extract a JobPosting description from HTML via JSON-LD.

    Returns the cleaned text if found, or None if no JobPosting schema
    is present or the description field is empty.
    """
    if not html_str or "<script" not in html_str:
        return None

    soup = BeautifulSoup(html_str, "html.parser")

    for block in _iter_json_ld_blocks(soup):
        for posting in _walk_for_job_posting(block):
            description = posting.get("description")
            if isinstance(description, str) and description.strip():
                cleaned = _strip_html(description)
                if cleaned:
                    return cleaned

    return None
