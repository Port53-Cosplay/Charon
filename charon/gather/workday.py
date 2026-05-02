"""Workday adapter for `charon gather`.

Workday is per-tenant. Each employer in companies.yaml carries a
`workday: { tenant, wd, site }` triple that resolves to:

  POST https://<tenant>.<wd>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs

The body paginates via `limit` + `offset`. The list endpoint returns
postings with title + locationsText + externalPath + postedOn (a
human-readable string like "Posted 5 Days Ago" — stored as-is). Full
job descriptions live behind a separate endpoint and are intentionally
deferred to Phase 7 (`enrich`).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from charon.gather import GatherError


WORKDAY_ENDPOINT = "https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
WORKDAY_JOB_URL = "https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{external_path}"
PAGE_SIZE = 20
PAGE_DELAY_SECONDS = 1.0
MAX_PAGES = 200  # safety cap; ~4000 postings max per employer
REQUEST_TIMEOUT = 30
USER_AGENT = "Charon/0.6 (Job Discovery; +https://github.com/Pickle-Pixel/Charon)"


def _resolve_tenant(entry: dict[str, Any] | None) -> tuple[str, str, str]:
    """Read the tenant/wd/site triple from a registry entry. Raises if missing."""
    if not entry or not isinstance(entry, dict):
        raise GatherError("Workday adapter requires a registry entry with a 'workday' block.")
    wd_cfg = entry.get("workday")
    if not isinstance(wd_cfg, dict):
        raise GatherError(
            f"Entry for slug '{entry.get('slug', '?')}' missing 'workday: {{tenant, wd, site}}' block."
        )
    tenant = wd_cfg.get("tenant")
    wd = wd_cfg.get("wd")
    site = wd_cfg.get("site")
    if not (tenant and wd and site):
        raise GatherError(
            f"Workday config for '{entry.get('slug', '?')}' must include tenant, wd, and site."
        )
    return str(tenant), str(wd), str(site)


def _build_job_url(tenant: str, wd: str, site: str, external_path: str) -> str:
    """Convert an externalPath ('/job/...') to a public job URL."""
    if not external_path.startswith("/"):
        external_path = "/" + external_path
    return WORKDAY_JOB_URL.format(tenant=tenant, wd=wd, site=site, external_path=external_path)


def _post_page(
    client: httpx.Client,
    endpoint: str,
    offset: int,
    slug: str,
) -> dict[str, Any]:
    """POST one page of results from Workday. Returns parsed JSON dict."""
    body = {
        "appliedFacets": {},
        "limit": PAGE_SIZE,
        "offset": offset,
        "searchText": "",
    }
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        response = client.post(endpoint, json=body, headers=headers)
    except httpx.TimeoutException:
        raise GatherError(f"Workday timed out for slug '{slug}' at offset {offset}.")
    except httpx.RequestError as e:
        raise GatherError(
            f"Workday request failed for slug '{slug}': {type(e).__name__}"
        ) from e

    if response.status_code == 404:
        raise GatherError(
            f"Workday returned 404 for slug '{slug}'. "
            "Verify tenant/wd/site in companies.yaml."
        )
    if response.status_code == 405:
        raise GatherError(
            f"Workday returned 405 for slug '{slug}'. "
            "This tenant may have disabled the public CXS endpoint."
        )
    if response.status_code >= 400:
        raise GatherError(
            f"Workday returned HTTP {response.status_code} for slug '{slug}'."
        )

    try:
        data = response.json()
    except ValueError as e:
        raise GatherError(
            f"Workday returned non-JSON response for slug '{slug}'."
        ) from e

    if not isinstance(data, dict):
        raise GatherError(f"Workday response for '{slug}' is not a JSON object.")
    return data


def fetch_jobs(
    slug: str,
    *,
    entry: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
    page_delay: float = PAGE_DELAY_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch all open postings for one Workday-hosted employer.

    Paginates through all pages until `total` is reached or `MAX_PAGES` is hit.
    Sleeps `page_delay` seconds between paginated calls.
    """
    if not slug or not slug.strip():
        raise GatherError("Workday slug cannot be empty.")

    tenant, wd, site = _resolve_tenant(entry)
    endpoint = WORKDAY_ENDPOINT.format(tenant=tenant, wd=wd, site=site)
    employer_name = (entry or {}).get("name", slug)

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

    normalized: list[dict[str, Any]] = []

    try:
        offset = 0
        total: int | None = None
        for page_num in range(MAX_PAGES):
            data = _post_page(client, endpoint, offset, slug)

            if total is None:
                t = data.get("total")
                total = int(t) if isinstance(t, (int, float)) else None

            postings = data.get("jobPostings")
            if postings is None:
                break
            if not isinstance(postings, list):
                raise GatherError(
                    f"Workday 'jobPostings' field for '{slug}' is not a list."
                )

            if not postings:
                break

            for post in postings:
                if not isinstance(post, dict):
                    continue
                title = post.get("title")
                external_path = post.get("externalPath")
                if not title or not external_path:
                    continue
                normalized.append(
                    {
                        "company": employer_name,
                        "role": title.strip(),
                        "url": _build_job_url(tenant, wd, site, external_path),
                        "location": post.get("locationsText") or None,
                        "description": "",  # Phase 7 enrichment fills this in
                        "posted_at": post.get("postedOn"),
                    }
                )

            offset += len(postings)
            if total is not None and offset >= total:
                break
            if len(postings) < PAGE_SIZE:
                # Workday returned a partial page — must be the last
                break
            if page_delay > 0:
                time.sleep(page_delay)
    finally:
        if owns_client:
            client.close()

    return normalized
