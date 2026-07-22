"""SAP SuccessFactors adapter for `charon gather`.

SuccessFactors career sites (the "Career Site Builder" search page) have no
public JSON API. The search results are server-rendered HTML at:

  https://<host>/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow=<n>

Results come 25 per page in a `<table>` of `<tr class="data-row">` rows, each
carrying a title link (`a.jobTitle-link` -> `/job/<slug>/<id>/`), a location
cell (`td.colLocation span.jobLocation`), and a posted date (`td.colDate
span.jobDate`). We paginate by `startrow` until the total count is reached.

Termination is tricky: SuccessFactors CLAMPS an out-of-range `startrow` to the
last page and returns rows anyway (it never goes empty), so we can't stop on an
empty page. Instead we read the total from the pagination label ("... of 101")
and also stop early if a page yields no URLs we haven't already seen.

Each employer in companies.yaml carries a `successfactors: { host }` block.
Full descriptions live on the per-job pages and are deferred to `enrich`
(Eastman's job pages expose schema.org JobPosting JSON-LD, so the JSON-LD tier
handles them).
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from charon.gather import GatherError


SEARCH_URL = "https://{host}/search/"
PAGE_SIZE = 25
PAGE_DELAY_SECONDS = 1.0
MAX_PAGES = 200  # safety cap; ~5000 postings max per employer
REQUEST_TIMEOUT = 30
USER_AGENT = "Charon/0.6 (Job Discovery; +https://github.com/Pickle-Pixel/Charon)"

_TOTAL_RE = re.compile(r"of\s+([\d,]+)", re.IGNORECASE)


def _resolve_host(entry: dict[str, Any] | None) -> tuple[str, str, str]:
    """Read the host (and optional q/locale) from a registry entry."""
    if not entry or not isinstance(entry, dict):
        raise GatherError(
            "SuccessFactors adapter requires a registry entry with a 'successfactors' block."
        )
    cfg = entry.get("successfactors")
    if not isinstance(cfg, dict):
        raise GatherError(
            f"Entry for slug '{entry.get('slug', '?')}' missing "
            "'successfactors: {{host}}' block."
        )
    host = cfg.get("host")
    if not host:
        raise GatherError(
            f"SuccessFactors config for '{entry.get('slug', '?')}' must include a host."
        )
    host = str(host).strip().rstrip("/")
    # Tolerate a full URL in the host field.
    host = re.sub(r"^https?://", "", host)
    query = str(cfg.get("q", "")).strip()
    locale = str(cfg.get("locale", "en_US")).strip()
    return host, query, locale


def _parse_total(soup: BeautifulSoup) -> int | None:
    """Read the total posting count from the pagination label ('... of 101')."""
    label = soup.select_one("span.paginationLabel")
    if label is not None:
        match = _TOTAL_RE.search(label.get_text(" ", strip=True))
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def _clean_ws(text: str) -> str:
    """Collapse the runs of whitespace SuccessFactors leaves in its cells."""
    return re.sub(r"\s+", " ", text).strip()


def _parse_rows(
    soup: BeautifulSoup,
    host: str,
    employer_name: str,
) -> list[dict[str, Any]]:
    """Extract normalized job dicts from one search-results page."""
    base = f"https://{host}/"
    rows: list[dict[str, Any]] = []

    for row in soup.select("tr.data-row"):
        # The title appears twice (desktop `hidden-phone` + mobile `visible-phone`
        # copies); take the first link so we don't double-count.
        link = row.select_one("a.jobTitle-link")
        if link is None:
            continue
        href = link.get("href")
        title = link.get_text(strip=True)
        if not href or not title:
            continue

        loc_el = row.select_one("td.colLocation span.jobLocation") or row.select_one(
            "span.jobLocation"
        )
        date_el = row.select_one("td.colDate span.jobDate") or row.select_one(
            "span.jobDate"
        )

        rows.append(
            {
                "company": employer_name,
                "role": title.strip(),
                "url": urljoin(base, href.strip()),
                "location": _clean_ws(loc_el.get_text(" ", strip=True)) if loc_el else None,
                "description": "",  # enrich fills this in
                "posted_at": _clean_ws(date_el.get_text(" ", strip=True)) if date_el else None,
            }
        )

    return rows


def _fetch_page(
    client: httpx.Client,
    host: str,
    query: str,
    locale: str,
    startrow: int,
    slug: str,
) -> str:
    """GET one search-results page. Returns raw HTML."""
    params = {
        "q": query,
        "sortColumn": "referencedate",
        "sortDirection": "desc",
        "startrow": startrow,
    }
    if locale:
        params["locale"] = locale
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}

    try:
        response = client.get(
            SEARCH_URL.format(host=host), params=params, headers=headers
        )
    except httpx.TimeoutException:
        raise GatherError(
            f"SuccessFactors timed out for slug '{slug}' at startrow {startrow}."
        )
    except httpx.RequestError as e:
        raise GatherError(
            f"SuccessFactors request failed for slug '{slug}': {type(e).__name__}"
        ) from e

    if response.status_code == 404:
        raise GatherError(
            f"SuccessFactors returned 404 for slug '{slug}'. "
            "Verify the host in companies.yaml."
        )
    if response.status_code >= 400:
        raise GatherError(
            f"SuccessFactors returned HTTP {response.status_code} for slug '{slug}'."
        )
    return response.text


def fetch_jobs(
    slug: str,
    *,
    entry: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
    page_delay: float = PAGE_DELAY_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch all open postings for one SuccessFactors-hosted employer.

    Paginates by `startrow` until the reported total is reached or a page adds
    no new URLs (guards against SuccessFactors clamping past-the-end requests to
    the last page). Sleeps `page_delay` seconds between pages.
    """
    if not slug or not slug.strip():
        raise GatherError("SuccessFactors slug cannot be empty.")

    host, query, locale = _resolve_host(entry)
    employer_name = (entry or {}).get("name", slug)

    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

    normalized: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    try:
        total: int | None = None
        for page_num in range(MAX_PAGES):
            startrow = page_num * PAGE_SIZE
            html_str = _fetch_page(client, host, query, locale, startrow, slug)
            soup = BeautifulSoup(html_str, "html.parser")

            if total is None:
                total = _parse_total(soup)

            page_rows = _parse_rows(soup, host, employer_name)
            if not page_rows:
                break

            new_this_page = 0
            for job in page_rows:
                if job["url"] in seen_urls:
                    continue
                seen_urls.add(job["url"])
                normalized.append(job)
                new_this_page += 1

            # Clamping backstop: a page that surfaced nothing new means we've
            # run past the end and SuccessFactors handed back the last page again.
            if new_this_page == 0:
                break

            next_start = startrow + PAGE_SIZE
            if total is not None and next_start >= total:
                break
            if page_delay > 0:
                time.sleep(page_delay)
    finally:
        if owns_client:
            client.close()

    return normalized
