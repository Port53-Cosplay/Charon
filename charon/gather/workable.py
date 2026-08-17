"""Workable adapter for `charon gather`.

Public widget API (no auth):
    https://apply.workable.com/api/v1/widget/accounts/<slug>?details=true

`details=true` inlines full descriptions. Accounts with very large job
counts can be slow with details — acceptable for the registry sizes here.
"""

from __future__ import annotations

import html
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from charon.gather import GatherError


API = "https://apply.workable.com/api/v1/widget/accounts/{slug}"
REQUEST_TIMEOUT = 60
USER_AGENT = "Charon/0.6 (Job Discovery; +https://github.com/Pickle-Pixel/Charon)"


def _strip_html(content: str) -> str:
    if not content:
        return ""
    soup = BeautifulSoup(html.unescape(content), "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _location_string(job: dict[str, Any]) -> str | None:
    parts = [job.get("city"), job.get("state"), job.get("country")]
    text = ", ".join(p for p in parts if isinstance(p, str) and p.strip())
    if job.get("telecommuting") is True or job.get("remote") is True:
        text = f"Remote{' - ' + text if text else ''}"
    return text or None


def fetch_jobs(
    slug: str,
    *,
    entry: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch open postings for one Workable-hosted employer."""
    if not slug or not slug.strip():
        raise GatherError("Workable slug cannot be empty.")
    slug = slug.strip()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)
    try:
        try:
            response = client.get(
                API.format(slug=slug), params={"details": "true"}, headers=headers
            )
        except httpx.TimeoutException:
            raise GatherError(f"Workable timed out for slug '{slug}'.")
        except httpx.RequestError as e:
            raise GatherError(
                f"Workable request failed for slug '{slug}': {type(e).__name__}"
            ) from e
        if response.status_code == 404:
            raise GatherError(
                f"Workable returned 404 for slug '{slug}'. "
                "Check companies.yaml — the slug may have changed."
            )
        if response.status_code >= 400:
            raise GatherError(
                f"Workable returned HTTP {response.status_code} for slug '{slug}'."
            )
        try:
            data = response.json()
        except ValueError as e:
            raise GatherError(f"Workable returned non-JSON for slug '{slug}'.") from e
    finally:
        if owns_client:
            client.close()

    employer_name = (entry or {}).get("name", slug)
    normalized: list[dict[str, Any]] = []
    for job in data.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        url = job.get("url") or job.get("application_url")
        title = job.get("title")
        if not url or not title:
            continue
        normalized.append(
            {
                "company": employer_name,
                "role": str(title).strip(),
                "url": str(url).strip(),
                "location": _location_string(job),
                "description": _strip_html(job.get("description") or ""),
                "posted_at": job.get("published_on") or job.get("created_at"),
            }
        )
    return normalized
