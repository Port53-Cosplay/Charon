"""Ashby adapter for `charon gather`.

Public board API: https://api.ashbyhq.com/posting-api/job-board/<slug>

Ashby returns a JSON object with a `jobs` array. Each posting carries a
plain-text description (`descriptionPlain`) so we don't need to strip HTML.
`publishedAt` is already ISO-8601, so no timestamp conversion is needed.
"""

from __future__ import annotations

from typing import Any

import httpx

from charon.gather import GatherError


ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "Charon/0.6 (Job Discovery; +https://github.com/Pickle-Pixel/Charon)"


def _location_string(post: dict[str, Any]) -> str | None:
    """Pull a location string. Ashby uses `location` (string) and sometimes
    `secondaryLocations` (list of {locationName: ...})."""
    primary = post.get("location")
    if isinstance(primary, str) and primary.strip():
        return primary.strip()

    secondary = post.get("secondaryLocations")
    if isinstance(secondary, list):
        names: list[str] = []
        for loc in secondary:
            if isinstance(loc, dict):
                name = loc.get("locationName") or loc.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
            elif isinstance(loc, str) and loc.strip():
                names.append(loc.strip())
        if names:
            return ", ".join(names)

    if post.get("isRemote") is True:
        return "Remote"
    return None


def _description(post: dict[str, Any]) -> str:
    """Prefer plain-text; fall back to stripping HTML if only HTML provided."""
    plain = post.get("descriptionPlain")
    if isinstance(plain, str) and plain.strip():
        return plain.strip()

    html_text = post.get("descriptionHtml")
    if isinstance(html_text, str) and html_text.strip():
        # Lazy import — only needed in the fallback path
        from bs4 import BeautifulSoup
        return BeautifulSoup(html_text, "html.parser").get_text(separator="\n", strip=True)

    return ""


def fetch_jobs(
    slug: str,
    *,
    entry: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch open postings for one Ashby-hosted employer.

    Returns normalized job dicts ready for `add_discovery`. Raises GatherError
    on HTTP errors, malformed responses, or 404 (bad slug).
    """
    if not slug or not slug.strip():
        raise GatherError("Ashby slug cannot be empty.")

    url = ASHBY_API.format(slug=slug.strip())
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

    try:
        try:
            response = client.get(url, headers=headers)
        except httpx.TimeoutException:
            raise GatherError(f"Ashby timed out for slug '{slug}'.")
        except httpx.RequestError as e:
            raise GatherError(
                f"Ashby request failed for slug '{slug}': {type(e).__name__}"
            ) from e

        if response.status_code == 404:
            raise GatherError(
                f"Ashby returned 404 for slug '{slug}'. "
                "Check companies.yaml — the slug may have changed."
            )
        if response.status_code >= 400:
            raise GatherError(
                f"Ashby returned HTTP {response.status_code} for slug '{slug}'."
            )

        try:
            data = response.json()
        except ValueError as e:
            raise GatherError(
                f"Ashby returned non-JSON response for slug '{slug}'."
            ) from e
    finally:
        if owns_client:
            client.close()

    if not isinstance(data, dict):
        raise GatherError(f"Ashby response for '{slug}' is not a JSON object.")

    raw_jobs = data.get("jobs")
    if raw_jobs is None:
        return []
    if not isinstance(raw_jobs, list):
        raise GatherError(f"Ashby 'jobs' field for '{slug}' is not a list.")

    employer_name = (entry or {}).get("name", slug)

    normalized: list[dict[str, Any]] = []
    for post in raw_jobs:
        if not isinstance(post, dict):
            continue
        job_url = post.get("jobUrl") or post.get("applyUrl")
        title = post.get("title")
        if not job_url or not title:
            continue
        normalized.append(
            {
                "company": employer_name,
                "role": title.strip(),
                "url": job_url.strip(),
                "location": _location_string(post),
                "description": _description(post),
                "posted_at": post.get("publishedAt") or post.get("updatedAt"),
            }
        )

    return normalized
