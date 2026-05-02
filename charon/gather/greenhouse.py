"""Greenhouse adapter for `charon gather`.

Public board API: https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true

The `content=true` flag returns the full HTML-escaped job description inline,
which means the discoveries table can carry usable text without a follow-up
fetch. Phase 7 (`enrich`) will still run for ATSs that don't include full
descriptions in the listing API.
"""

from __future__ import annotations

import html
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from charon.gather import GatherError


GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "Charon/0.6 (Job Discovery; +https://github.com/Pickle-Pixel/Charon)"


def _strip_html(content: str) -> str:
    """Unescape Greenhouse HTML and reduce to plain text."""
    if not content:
        return ""
    decoded = html.unescape(content)
    soup = BeautifulSoup(decoded, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _location_string(loc: Any) -> str | None:
    """Normalize Greenhouse location field — usually `{"name": "..."}`."""
    if isinstance(loc, dict):
        name = loc.get("name")
        return name.strip() if isinstance(name, str) and name.strip() else None
    if isinstance(loc, str) and loc.strip():
        return loc.strip()
    return None


def fetch_jobs(
    slug: str,
    *,
    entry: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch open postings for one Greenhouse-hosted employer.

    Returns normalized job dicts ready for `add_discovery`. The orchestrator
    handles dedupe, applied-skip, and DB writes — this adapter only returns
    structured data.

    Raises GatherError on HTTP errors, malformed responses, or 404 (bad slug).
    """
    if not slug or not slug.strip():
        raise GatherError("Greenhouse slug cannot be empty.")

    url = GREENHOUSE_API.format(slug=slug.strip())
    params = {"content": "true"}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

    try:
        try:
            response = client.get(url, params=params, headers=headers)
        except httpx.TimeoutException:
            raise GatherError(f"Greenhouse timed out for slug '{slug}'.")
        except httpx.RequestError as e:
            raise GatherError(
                f"Greenhouse request failed for slug '{slug}': {type(e).__name__}"
            ) from e

        if response.status_code == 404:
            raise GatherError(
                f"Greenhouse returned 404 for slug '{slug}'. "
                "Check companies.yaml — the slug may have changed."
            )
        if response.status_code >= 400:
            raise GatherError(
                f"Greenhouse returned HTTP {response.status_code} for slug '{slug}'."
            )

        try:
            data = response.json()
        except ValueError as e:
            raise GatherError(
                f"Greenhouse returned non-JSON response for slug '{slug}'."
            ) from e
    finally:
        if owns_client:
            client.close()

    if not isinstance(data, dict):
        raise GatherError(f"Greenhouse response for '{slug}' is not a JSON object.")

    raw_jobs = data.get("jobs")
    if raw_jobs is None:
        return []
    if not isinstance(raw_jobs, list):
        raise GatherError(f"Greenhouse 'jobs' field for '{slug}' is not a list.")

    employer_name = (entry or {}).get("name", slug)

    normalized: list[dict[str, Any]] = []
    for job in raw_jobs:
        if not isinstance(job, dict):
            continue
        absolute_url = job.get("absolute_url")
        title = job.get("title")
        if not absolute_url or not title:
            continue
        normalized.append(
            {
                "company": employer_name,
                "role": title.strip(),
                "url": absolute_url.strip(),
                "location": _location_string(job.get("location")),
                "description": _strip_html(job.get("content", "")),
                "posted_at": job.get("updated_at") or job.get("first_published"),
            }
        )

    return normalized
