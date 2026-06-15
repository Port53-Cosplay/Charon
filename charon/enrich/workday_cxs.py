"""Workday CXS detail enrichment.

Workday job pages are JS-rendered single-page apps — the static HTML has no
description in it, so JSON-LD, CSS scraping, and LLM-over-cleaned-text all
come up empty. The real content sits behind Workday's CXS JSON API, the same
family of endpoints `charon gather` uses for listings.

A public job URL like:

    https://<tenant>.<wd>.myworkdayjobs.com/<locale>/<site>/job/.../_R12345

maps to the detail endpoint:

    https://<tenant>.<wd>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/job/.../_R12345

which returns JSON with jobPostingInfo.jobDescription (HTML).

A filled/closed posting returns HTTP 403 "permission denied" — that's a real
state (the job is gone), distinct from a transient failure, so it's raised as
WorkdayClosed and the caller can stop retrying it.
"""

from __future__ import annotations

import html as _html
import re

import httpx
from bs4 import BeautifulSoup


_URL_RE = re.compile(
    r"^https://(?P<tenant>[^.]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com"
    r"/(?P<locale>[a-z]{2}-[A-Z]{2})/(?P<site>[^/]+)(?P<path>/.+)$"
)

REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (compatible; Charon/0.6; "
    "+https://github.com/Port53-Cosplay/Charon)"
)


class WorkdayClosed(Exception):
    """The posting is no longer open (CXS returned 403 permission denied)."""


def is_workday_url(url: str | None) -> bool:
    """True if the URL looks like a Workday-hosted job posting."""
    return bool(url) and ".myworkdayjobs.com/" in url


def _cxs_url(url: str) -> str | None:
    """Translate a public Workday job URL into its CXS detail endpoint.

    Returns None if the URL doesn't match the expected Workday shape.
    """
    m = _URL_RE.match(url or "")
    if not m:
        return None
    g = m.groupdict()
    return (
        f"https://{g['tenant']}.{g['wd']}.myworkdayjobs.com"
        f"/wday/cxs/{g['tenant']}/{g['site']}{g['path']}"
    )


def _strip_html(raw: str) -> str:
    """Reduce a jobDescription (HTML) to plain text."""
    if not raw:
        return ""
    soup = BeautifulSoup(_html.unescape(raw), "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_description(
    url: str, *, client: httpx.Client | None = None
) -> str | None:
    """Fetch the plain-text job description for a Workday job URL.

    Returns the cleaned description, or None if the URL isn't a recognizable
    Workday job URL or the response carried no description. Raises
    WorkdayClosed if the posting is filled/closed (CXS 403).
    """
    cxs = _cxs_url(url)
    if not cxs:
        return None

    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    try:
        try:
            response = client.get(cxs, headers={"Accept": "application/json"})
        except httpx.RequestError:
            return None

        if response.status_code == 403:
            raise WorkdayClosed(f"Workday posting closed or restricted: {url}")
        if response.status_code >= 400:
            return None

        try:
            data = response.json()
        except ValueError:
            return None
    finally:
        if owns_client:
            client.close()

    if not isinstance(data, dict):
        return None
    info = data.get("jobPostingInfo")
    if not isinstance(info, dict):
        return None
    description = _strip_html(info.get("jobDescription") or "")
    return description or None
