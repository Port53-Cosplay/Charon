"""Gather — discover open job postings via public ATS APIs.

This package implements Phase 6 of the Charon v2 plan (see ROADMAP.md ADR-006).
Each ATS has its own adapter module. The orchestrator here loads the curated
employer registry from `config/companies.yaml`, dispatches to the right adapter
per employer, and writes new postings to the `discoveries` table.

Souls at the riverbank.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

import yaml

from charon.db import (
    add_discovery,
    discovery_exists,
    get_applied_companies,
)


class GatherError(Exception):
    """Raised when gathering fails for reasons the user should see."""


# Adapter registry — adapters are loaded lazily so a missing module
# doesn't crash the package import.
ADAPTERS: dict[str, str] = {
    "greenhouse": "charon.gather.greenhouse",
    "lever": "charon.gather.lever",
    "ashby": "charon.gather.ashby",
    "workday": "charon.gather.workday",
}

DEFAULT_RATE_LIMIT_SECONDS = 1.0


# ── registry ─────────────────────────────────────────────────────────


def _registry_paths() -> list[Path]:
    """Candidate locations for companies.yaml, in lookup order."""
    override = os.environ.get("CHARON_REGISTRY")
    if override:
        return [Path(override).expanduser()]

    candidates = [
        Path.home() / ".charon" / "companies.yaml",
        Path(__file__).resolve().parent.parent.parent / "config" / "companies.yaml",
    ]
    return candidates


def load_registry() -> dict[str, list[dict[str, Any]]]:
    """Load the employer registry from companies.yaml.

    Returns a dict mapping ATS name -> list of employer entries. Each entry
    has at minimum `slug` and `name`; tier/category/notes/workday are optional.
    Commented-out sections in the YAML are not present in the parsed output.
    """
    for path in _registry_paths():
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f)
            if not isinstance(doc, dict):
                raise GatherError(f"Registry at {path} is not a YAML mapping.")
            registry = doc.get("gather")
            if not isinstance(registry, dict):
                raise GatherError(
                    f"Registry at {path} missing top-level 'gather:' key."
                )
            return registry

    raise GatherError(
        "No companies.yaml found. Looked in: "
        + ", ".join(str(p) for p in _registry_paths())
    )


def list_employers(
    registry: dict[str, list[dict[str, Any]]],
    ats: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Flatten registry into (ats, entry) pairs, optionally filtered."""
    pairs: list[tuple[str, dict[str, Any]]] = []
    for ats_name, entries in registry.items():
        if ats and ats_name != ats:
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("slug"):
                pairs.append((ats_name, entry))
    return pairs


# ── dedupe ───────────────────────────────────────────────────────────


def normalize_url(url: str) -> str:
    """Normalize a URL for dedupe — strip query/fragment, lowercase host, trim slashes."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def make_dedupe_hash(ats: str, url: str) -> str:
    """SHA-256 hash of (ats, normalized url). Stable across runs."""
    payload = f"{ats}|{normalize_url(url)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── orchestration ────────────────────────────────────────────────────


def _load_adapter(ats: str):
    """Lazily import the adapter module for a given ATS."""
    module_path = ADAPTERS.get(ats)
    if not module_path:
        raise GatherError(
            f"No adapter for ATS '{ats}'. Available: {', '.join(sorted(ADAPTERS))}"
        )
    try:
        return importlib.import_module(module_path)
    except ImportError as e:
        raise GatherError(f"Adapter '{ats}' failed to import: {e}") from e


def gather_employer(
    ats: str,
    entry: dict[str, Any],
    *,
    dry_run: bool = False,
    skip_companies: Iterable[str] = (),
) -> dict[str, Any]:
    """Gather jobs for a single employer.

    Returns a summary dict:
        {ats, slug, name, fetched, new, dupes, skipped, error}

    `fetched` = jobs returned by the ATS adapter
    `new` = jobs written to the discoveries table
    `dupes` = jobs already present (matched by dedupe hash)
    `skipped` = jobs whose company appears in skip_companies (lowercased compare)
    `error` = error message string, if the adapter raised
    """
    slug = entry["slug"]
    name = entry.get("name", slug)
    tier = entry.get("tier")
    category = entry.get("category")
    skip_set = {c.lower() for c in skip_companies}

    summary: dict[str, Any] = {
        "ats": ats,
        "slug": slug,
        "name": name,
        "fetched": 0,
        "new": 0,
        "dupes": 0,
        "skipped": 0,
        "error": None,
    }

    if name.lower() in skip_set:
        summary["skipped"] = -1  # whole employer skipped
        return summary

    try:
        adapter = _load_adapter(ats)
        jobs = adapter.fetch_jobs(slug, entry=entry)
    except GatherError as e:
        summary["error"] = str(e)
        return summary
    except Exception as e:  # adapter-specific errors bubbled up
        summary["error"] = f"{type(e).__name__}: {e}"
        return summary

    summary["fetched"] = len(jobs)

    for job in jobs:
        company = job.get("company") or name
        if company.lower() in skip_set:
            summary["skipped"] += 1
            continue

        url = job.get("url")
        if not url:
            continue

        dedupe_hash = make_dedupe_hash(ats, url)

        if dry_run:
            if discovery_exists(dedupe_hash):
                summary["dupes"] += 1
            else:
                summary["new"] += 1
            continue

        new_id = add_discovery(
            ats=ats,
            slug=slug,
            company=company,
            role=job.get("role", ""),
            url=url,
            dedupe_hash=dedupe_hash,
            location=job.get("location"),
            description=job.get("description"),
            posted_at=job.get("posted_at"),
            tier=tier,
            category=category,
        )
        if new_id is not None:
            summary["new"] += 1
        else:
            summary["dupes"] += 1

    return summary


def gather_registry(
    *,
    ats: str | None = None,
    slug: str | None = None,
    dry_run: bool = False,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Run gather across the registry.

    Parameters:
        ats: limit to one ATS (e.g. 'greenhouse')
        slug: limit to one employer (must match registry slug)
        dry_run: don't write to DB, just count what would happen
        rate_limit_seconds: sleep between employer fetches (politeness)
        on_progress: callback invoked with each employer summary

    Returns a list of per-employer summaries.
    """
    registry = load_registry()
    pairs = list_employers(registry, ats=ats)
    if slug:
        pairs = [(a, e) for a, e in pairs if e.get("slug") == slug]

    if not pairs:
        return []

    skip_companies = get_applied_companies()
    summaries: list[dict[str, Any]] = []

    for i, (ats_name, entry) in enumerate(pairs):
        # Skip ATSs whose adapter isn't implemented yet — surface clearly,
        # don't fail the whole run.
        if ats_name not in ADAPTERS:
            summary = {
                "ats": ats_name,
                "slug": entry.get("slug", "?"),
                "name": entry.get("name", entry.get("slug", "?")),
                "fetched": 0,
                "new": 0,
                "dupes": 0,
                "skipped": 0,
                "error": f"adapter for '{ats_name}' not yet implemented",
            }
        else:
            summary = gather_employer(
                ats_name,
                entry,
                dry_run=dry_run,
                skip_companies=skip_companies,
            )
        summaries.append(summary)
        if on_progress:
            on_progress(summary)
        if i < len(pairs) - 1 and rate_limit_seconds > 0:
            time.sleep(rate_limit_seconds)

    return summaries
