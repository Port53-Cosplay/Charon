"""Lever adapter for `charon gather`.

Public postings API: https://api.lever.co/v0/postings/<slug>?mode=json

Lever returns a flat JSON array (not an object). Each posting carries both
HTML and plain-text description fields; we use `descriptionPlain` and
`additionalPlain` so downstream stages don't need to strip tags. Posted
timestamps are epoch milliseconds — converted to ISO-8601 UTC for
consistency with Greenhouse.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from charon.gather import GatherError


LEVER_API = "https://api.lever.co/v0/postings/{slug}"
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "Charon/0.6 (Job Discovery; +https://github.com/Pickle-Pixel/Charon)"


def _epoch_ms_to_iso(value: Any) -> str | None:
    """Convert Lever's epoch-millisecond timestamp to ISO-8601 UTC."""
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _location_from_categories(categories: Any) -> str | None:
    """Pull a location string from Lever's `categories` object."""
    if not isinstance(categories, dict):
        return None
    loc = categories.get("location")
    if isinstance(loc, str) and loc.strip():
        return loc.strip()
    # Lever sometimes uses `allLocations: ["Remote", ...]`
    all_locs = categories.get("allLocations")
    if isinstance(all_locs, list) and all_locs:
        joined = ", ".join(str(x).strip() for x in all_locs if isinstance(x, str) and x.strip())
        return joined or None
    return None


def _description(post: dict[str, Any]) -> str:
    """Prefer plain-text fields, fall back to nothing rather than HTML."""
    parts: list[str] = []
    main = post.get("descriptionPlain")
    if isinstance(main, str) and main.strip():
        parts.append(main.strip())
    additional = post.get("additionalPlain")
    if isinstance(additional, str) and additional.strip():
        parts.append(additional.strip())
    # Lever's `lists` field carries bullet groups (responsibilities, qualifications)
    lists = post.get("lists")
    if isinstance(lists, list):
        for item in lists:
            if not isinstance(item, dict):
                continue
            heading = item.get("text")
            content = item.get("content")
            if isinstance(heading, str) and heading.strip():
                parts.append(heading.strip())
            if isinstance(content, str) and content.strip():
                # Strip simple HTML tags from list content
                import re as _re
                cleaned = _re.sub(r"<[^>]+>", " ", content)
                cleaned = _re.sub(r"\s+", " ", cleaned).strip()
                if cleaned:
                    parts.append(cleaned)
    return "\n\n".join(parts)


def fetch_jobs(
    slug: str,
    *,
    entry: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch open postings for one Lever-hosted employer.

    Returns normalized job dicts ready for `add_discovery`. Raises GatherError
    on HTTP errors, malformed responses, or 404 (bad slug).
    """
    if not slug or not slug.strip():
        raise GatherError("Lever slug cannot be empty.")

    url = LEVER_API.format(slug=slug.strip())
    params = {"mode": "json"}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

    try:
        try:
            response = client.get(url, params=params, headers=headers)
        except httpx.TimeoutException:
            raise GatherError(f"Lever timed out for slug '{slug}'.")
        except httpx.RequestError as e:
            raise GatherError(
                f"Lever request failed for slug '{slug}': {type(e).__name__}"
            ) from e

        if response.status_code == 404:
            raise GatherError(
                f"Lever returned 404 for slug '{slug}'. "
                "Check companies.yaml — the slug may have changed."
            )
        if response.status_code >= 400:
            raise GatherError(
                f"Lever returned HTTP {response.status_code} for slug '{slug}'."
            )

        try:
            data = response.json()
        except ValueError as e:
            raise GatherError(
                f"Lever returned non-JSON response for slug '{slug}'."
            ) from e
    finally:
        if owns_client:
            client.close()

    if not isinstance(data, list):
        raise GatherError(f"Lever response for '{slug}' is not a JSON list.")

    employer_name = (entry or {}).get("name", slug)

    normalized: list[dict[str, Any]] = []
    for post in data:
        if not isinstance(post, dict):
            continue
        hosted_url = post.get("hostedUrl") or post.get("applyUrl")
        title = post.get("text")
        if not hosted_url or not title:
            continue
        normalized.append(
            {
                "company": employer_name,
                "role": title.strip(),
                "url": hosted_url.strip(),
                "location": _location_from_categories(post.get("categories")),
                "description": _description(post),
                "posted_at": _epoch_ms_to_iso(post.get("createdAt")),
            }
        )

    return normalized
