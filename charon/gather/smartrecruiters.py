"""SmartRecruiters adapter for `charon gather`.

Public postings API (no auth):
    https://api.smartrecruiters.com/v1/companies/<slug>/postings?limit=100&offset=N

The listing API carries title/location/date but not the description —
full text comes later via `enrich` (the public job page has JSON-LD).
"""

from __future__ import annotations

from typing import Any

import httpx

from charon.gather import GatherError


API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
JOB_URL = "https://jobs.smartrecruiters.com/{slug}/{posting_id}"
PAGE_SIZE = 100
MAX_PAGES = 20
REQUEST_TIMEOUT = 30
USER_AGENT = "Charon/0.6 (Job Discovery; +https://github.com/Pickle-Pixel/Charon)"


def _location_string(loc: Any) -> str | None:
    if not isinstance(loc, dict):
        return None
    parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    text = ", ".join(p for p in parts if isinstance(p, str) and p.strip())
    if loc.get("remote") is True:
        text = f"Remote{' - ' + text if text else ''}"
    return text or None


def fetch_jobs(
    slug: str,
    *,
    entry: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch open postings for one SmartRecruiters-hosted employer."""
    if not slug or not slug.strip():
        raise GatherError("SmartRecruiters slug cannot be empty.")
    slug = slug.strip()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

    employer_name = (entry or {}).get("name", slug)
    normalized: list[dict[str, Any]] = []
    try:
        for page in range(MAX_PAGES):
            try:
                response = client.get(
                    API.format(slug=slug),
                    params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
                    headers=headers,
                )
            except httpx.TimeoutException:
                raise GatherError(f"SmartRecruiters timed out for slug '{slug}'.")
            except httpx.RequestError as e:
                raise GatherError(
                    f"SmartRecruiters request failed for slug '{slug}': {type(e).__name__}"
                ) from e
            if response.status_code == 404:
                raise GatherError(
                    f"SmartRecruiters returned 404 for slug '{slug}'. "
                    "Check companies.yaml — the slug may have changed."
                )
            if response.status_code >= 400:
                raise GatherError(
                    f"SmartRecruiters returned HTTP {response.status_code} for slug '{slug}'."
                )
            try:
                data = response.json()
            except ValueError as e:
                raise GatherError(
                    f"SmartRecruiters returned non-JSON for slug '{slug}'."
                ) from e

            postings = data.get("content") or []
            for job in postings:
                if not isinstance(job, dict):
                    continue
                posting_id = job.get("id")
                title = job.get("name")
                if not posting_id or not title:
                    continue
                normalized.append(
                    {
                        "company": employer_name,
                        "role": str(title).strip(),
                        "url": JOB_URL.format(slug=slug, posting_id=posting_id),
                        "location": _location_string(job.get("location")),
                        "description": None,
                        "posted_at": job.get("releasedDate"),
                    }
                )
            total = data.get("totalFound", 0)
            if (page + 1) * PAGE_SIZE >= int(total or 0) or not postings:
                break
    finally:
        if owns_client:
            client.close()

    return normalized
