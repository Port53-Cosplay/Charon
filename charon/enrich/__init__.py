"""Enrichment cascade for the discoveries table.

Phase 7 of the Charon v2 plan. Three-tier extraction in priority order:

  Tier 1 — JSON-LD JobPosting schema       (free, generic)
  Tier 2 — Per-ATS CSS selector library    (free, ATS-specific)
  Tier 3 — LLM extraction                  (paid, fallback)

Each discovery is enriched at most once unless `force=True`. The result
goes into `discoveries.full_description` with `enrichment_tier` set to
one of: skipped | jsonld | ats_css | ai_fallback | failed.

`skipped` means the source already had a long-enough description in
`description` (most Greenhouse/Lever/Ashby discoveries fall here, since
those adapters populate description at gather time).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from charon.db import (
    get_discoveries,
    get_discovery,
    get_unenriched_discoveries,
    update_discovery_enrichment,
)
from charon.enrich import ats_css, jsonld, llm
from charon.enrich.llm import LLMError
from charon.fetcher import FetchError, extract_text, fetch_html


SKIP_THRESHOLD_DEFAULT = 500  # chars of source description that qualify as "good enough"
DEFAULT_RATE_LIMIT_SECONDS = 1.0


class EnrichError(Exception):
    """Raised for enrichment failures the user should see."""


def _enrich_config(profile: dict[str, Any] | None) -> dict[str, Any]:
    cfg = (profile or {}).get("enrich") or {}
    return {
        "model": cfg.get("model", llm.DEFAULT_MODEL),
        "skip_threshold": int(cfg.get("skip_threshold", SKIP_THRESHOLD_DEFAULT)),
        "rate_limit_seconds": float(cfg.get("rate_limit_seconds", DEFAULT_RATE_LIMIT_SECONDS)),
    }


def enrich_discovery(
    discovery: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Enrich one discovery. Returns a result dict:
        {tier, full_description, source_url, error?}

    Does NOT write to the DB — caller is responsible. (Keeps the function
    pure-ish so it's easy to test.)
    """
    cfg = _enrich_config(profile)

    existing_desc = (discovery.get("description") or "").strip()
    if not force and len(existing_desc) >= cfg["skip_threshold"]:
        return {
            "tier": "skipped",
            "full_description": existing_desc,
            "source_url": discovery.get("url"),
        }

    url = discovery.get("url")
    if not url:
        return {"tier": "failed", "full_description": None, "error": "discovery has no URL"}

    try:
        html_str = fetch_html(url)
    except FetchError as e:
        return {"tier": "failed", "full_description": None, "error": str(e), "source_url": url}

    # Tier 1 — JSON-LD
    desc = jsonld.extract_description(html_str)
    if desc:
        return {"tier": "jsonld", "full_description": desc, "source_url": url}

    # Tier 2 — per-ATS CSS
    ats = discovery.get("ats")
    if ats:
        desc = ats_css.extract_description(html_str, ats)
        if desc:
            return {"tier": "ats_css", "full_description": desc, "source_url": url}

    # Tier 3 — LLM fallback. Send cleaned text, not raw HTML, to save tokens.
    try:
        cleaned_text = extract_text(html_str)
    except FetchError:
        cleaned_text = html_str  # fall back to raw HTML if extract_text rejected it

    try:
        desc = llm.extract_description(
            cleaned_text, model=cfg["model"], profile=profile
        )
    except LLMError as e:
        return {"tier": "failed", "full_description": None, "error": f"LLM: {e}", "source_url": url}

    if desc:
        return {"tier": "ai_fallback", "full_description": desc, "source_url": url}

    return {
        "tier": "failed",
        "full_description": None,
        "error": "no description recovered by any tier",
        "source_url": url,
    }


def enrich_one_id(
    discovery_id: int,
    *,
    profile: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Enrich a single discovery by ID, write to DB. Returns the result dict."""
    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise EnrichError(f"No discovery with id {discovery_id}.")
    if discovery.get("enrichment_tier") and not force:
        return {
            "tier": discovery["enrichment_tier"],
            "full_description": discovery.get("full_description"),
            "source_url": discovery.get("url"),
            "skipped_reason": "already enriched (use --force to re-run)",
        }

    result = enrich_discovery(discovery, profile=profile, force=force)
    update_discovery_enrichment(discovery_id, result["tier"], result.get("full_description"))
    result["discovery_id"] = discovery_id
    result["company"] = discovery.get("company")
    result["role"] = discovery.get("role")
    return result


def enrich_batch(
    *,
    ats: str | None = None,
    force: bool = False,
    limit: int | None = None,
    profile: dict[str, Any] | None = None,
    rate_limit_seconds: float | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Enrich many discoveries in sequence. Returns per-discovery result dicts.

    Default: only enriches discoveries where enrichment_tier IS NULL.
    With force=True, re-enriches everything matching the filter.
    """
    cfg = _enrich_config(profile)
    delay = rate_limit_seconds if rate_limit_seconds is not None else cfg["rate_limit_seconds"]

    if force:
        targets = get_discoveries(ats=ats, limit=limit)
    else:
        targets = get_unenriched_discoveries(ats=ats, limit=limit)

    results: list[dict[str, Any]] = []
    for i, discovery in enumerate(targets):
        result = enrich_discovery(discovery, profile=profile, force=force)
        try:
            update_discovery_enrichment(
                discovery["id"], result["tier"], result.get("full_description")
            )
        except Exception as e:
            result["error"] = result.get("error") or f"DB write failed: {e}"
        result["discovery_id"] = discovery["id"]
        result["company"] = discovery.get("company")
        result["role"] = discovery.get("role")
        results.append(result)
        if on_progress:
            on_progress(result)
        if i < len(targets) - 1 and delay > 0 and result["tier"] != "skipped":
            time.sleep(delay)

    return results


__all__ = [
    "EnrichError",
    "enrich_discovery",
    "enrich_one_id",
    "enrich_batch",
    "ats_css",
    "jsonld",
    "llm",
]
