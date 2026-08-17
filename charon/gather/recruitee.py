"""Recruitee adapter for `charon gather`.

Public offers API (no auth):
    https://<slug>.recruitee.com/api/offers/

Returns published offers with the full HTML description inline, so the
discoveries table gets usable text without a follow-up enrich fetch.
"""

from __future__ import annotations

import html
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from charon.gather import GatherError


API = "https://{slug}.recruitee.com/api/offers/"
REQUEST_TIMEOUT = 30
USER_AGENT = "Charon/0.6 (Job Discovery; +https://github.com/Pickle-Pixel/Charon)"


def _strip_html(content: str) -> str:
    if not content:
        return ""
    soup = BeautifulSoup(html.unescape(content), "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def fetch_jobs(
    slug: str,
    *,
    entry: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch open postings for one Recruitee-hosted employer."""
    if not slug or not slug.strip():
        raise GatherError("Recruitee slug cannot be empty.")
    slug = slug.strip()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)
    try:
        try:
            response = client.get(API.format(slug=slug), headers=headers)
        except httpx.TimeoutException:
            raise GatherError(f"Recruitee timed out for slug '{slug}'.")
        except httpx.RequestError as e:
            raise GatherError(
                f"Recruitee request failed for slug '{slug}': {type(e).__name__}"
            ) from e
        if response.status_code == 404:
            raise GatherError(
                f"Recruitee returned 404 for slug '{slug}'. "
                "Check companies.yaml — the slug may have changed."
            )
        if response.status_code >= 400:
            raise GatherError(
                f"Recruitee returned HTTP {response.status_code} for slug '{slug}'."
            )
        try:
            data = response.json()
        except ValueError as e:
            raise GatherError(f"Recruitee returned non-JSON for slug '{slug}'.") from e
    finally:
        if owns_client:
            client.close()

    employer_name = (entry or {}).get("name", slug)
    normalized: list[dict[str, Any]] = []
    for job in data.get("offers") or []:
        if not isinstance(job, dict):
            continue
        url = job.get("careers_url")
        title = job.get("title")
        if not url or not title:
            continue
        normalized.append(
            {
                "company": employer_name,
                "role": str(title).strip(),
                "url": str(url).strip(),
                "location": job.get("location") or job.get("city"),
                "description": _strip_html(job.get("description") or ""),
                "posted_at": job.get("published_at") or job.get("created_at"),
            }
        )
    return normalized
