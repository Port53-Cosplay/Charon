"""Tier 2 enrichment: per-ATS CSS selectors for the description region.

Each ATS embeds the job description in a known DOM location. When tier 1
(JSON-LD) misses, this tier targets that container directly.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup


# Per-ATS selector library. Listed in priority order — the first match wins.
SELECTORS: dict[str, list[str]] = {
    "greenhouse": [
        "div#content",
        "div.content-intro",
        "div[data-mapped='true']",
        "section.job-post-description",
    ],
    "lever": [
        "div.section-wrapper.page.posting-page",
        "div.posting-page",
        "div.section.page-centered[data-qa='job-description']",
        "div.posting-description",
    ],
    "ashby": [
        "div.ashby-job-posting-right-pane",
        "div._descriptionText_4yag6_201",
        "div._description_4yag6_201",
        "section.job-description",
    ],
    "workday": [
        "div[data-automation-id='jobPostingDescription']",
        "div[data-automation-id='jobDescription']",
        "div.PCPB",
        "div[data-automation-id='job-postingDescription']",
    ],
}


def _clean(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_description(html_str: str, ats: str) -> str | None:
    """Extract the description region for `ats` from HTML.

    Returns the cleaned text if a known selector matches and yields content,
    or None if no selector for this ATS matches.
    """
    if not html_str or not ats:
        return None

    selectors = SELECTORS.get(ats)
    if not selectors:
        return None

    soup = BeautifulSoup(html_str, "html.parser")

    for selector in selectors:
        try:
            node = soup.select_one(selector)
        except Exception:
            continue
        if node is None:
            continue
        text = node.get_text(separator="\n", strip=True)
        text = _clean(text)
        if len(text) >= 100:  # filter empty containers and tiny shells
            return text

    return None
