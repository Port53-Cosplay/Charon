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
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "successfactors": "charon.gather.successfactors",
    "smartrecruiters": "charon.gather.smartrecruiters",
    "recruitee": "charon.gather.recruitee",
    "workable": "charon.gather.workable",
}

DEFAULT_RATE_LIMIT_SECONDS = 1.0

# Employers gather in a bounded thread pool — full-registry runs drop from
# minutes to seconds. DB inserts are short WAL transactions (busy_timeout in
# db.py absorbs writer contention); adapters keep their own per-page delays.
DEFAULT_GATHER_WORKERS = 4
MAX_GATHER_WORKERS = 8


def _resolve_workers(workers: int | None) -> int:
    """Pick the pool size: explicit arg, else CHARON_GATHER_WORKERS, else default."""
    if workers is not None:
        return max(1, min(workers, MAX_GATHER_WORKERS))
    env = os.environ.get("CHARON_GATHER_WORKERS", "").strip()
    if env.isdigit() and int(env) > 0:
        return min(int(env), MAX_GATHER_WORKERS)
    return DEFAULT_GATHER_WORKERS


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
            return _merge_auto_registry(registry)

    raise GatherError(
        "No companies.yaml found. Looked in: "
        + ", ".join(str(p) for p in _registry_paths())
    )


def _merge_auto_registry(
    registry: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Merge machine-managed ~/.charon/companies-auto.yaml into the registry.

    Machine-discovered boards live in a separate file so the curated
    companies.yaml stays hand-edited. Curated entries win on (ats, slug)
    collisions. (Ported from Don's fork — d3athstr/Charon FORK_NOTES.md.)
    """
    auto_path = Path.home() / ".charon" / "companies-auto.yaml"
    if not auto_path.exists():
        return registry
    try:
        doc = yaml.safe_load(auto_path.read_text(encoding="utf-8")) or {}
        auto = doc.get("gather") or {}
    except Exception:
        return registry
    if not isinstance(auto, dict):
        return registry
    seen = {
        (ats, e.get("slug"))
        for ats, entries in registry.items()
        if isinstance(entries, list)
        for e in entries
    }
    for ats, entries in auto.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if (ats, entry.get("slug")) not in seen:
                registry.setdefault(ats, []).append(entry)
                seen.add((ats, entry.get("slug")))
    return registry


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


# ── URL auto-detection ───────────────────────────────────────────────


_LANG_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def detect_ats(url: str) -> tuple[str, dict[str, Any]] | None:
    """Recognize an ATS URL and return (ats_name, entry).

    The returned entry is the minimum shape `gather_employer` needs:
    `{slug, name}` for Greenhouse/Lever/Ashby, plus a `workday` block
    for Workday. Returns None if the URL doesn't match any known ATS.
    """
    if not url or "://" not in url:
        return None

    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]

    # Greenhouse — boards.greenhouse.io/<slug> or job-boards.greenhouse.io/<slug>
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        if parts:
            slug = parts[0]
            return "greenhouse", {"slug": slug, "name": slug}
    # Greenhouse custom subdomain — <slug>.greenhouse.io
    if host.endswith(".greenhouse.io") and host not in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        slug = host.split(".")[0]
        if slug and slug != "boards-api":
            return "greenhouse", {"slug": slug, "name": slug}

    # Lever — jobs.lever.co/<slug>
    if host == "jobs.lever.co":
        if parts:
            slug = parts[0]
            return "lever", {"slug": slug, "name": slug}

    # Ashby — jobs.ashbyhq.com/<slug> or <slug>.ashbyhq.com
    if host == "jobs.ashbyhq.com":
        if parts:
            slug = parts[0]
            return "ashby", {"slug": slug, "name": slug}
    if host.endswith(".ashbyhq.com") and host != "jobs.ashbyhq.com":
        slug = host.split(".")[0]
        if slug and slug != "api":
            return "ashby", {"slug": slug, "name": slug}

    # Workday — <tenant>.<wd>.myworkdayjobs.com/[<lang>/]<site>[/job/...]
    if host.endswith(".myworkdayjobs.com"):
        host_parts = host.split(".")
        if len(host_parts) >= 4:
            tenant, wd = host_parts[0], host_parts[1]
            site_parts = parts[1:] if parts and _LANG_RE.match(parts[0]) else parts
            if site_parts:
                site = site_parts[0]
                return "workday", {
                    "slug": tenant,
                    "name": tenant,
                    "workday": {"tenant": tenant, "wd": wd, "site": site},
                }

    return None


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
    workers: int | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Run gather across the registry.

    Parameters:
        ats: limit to one ATS (e.g. 'greenhouse')
        slug: limit to one employer (must match registry slug)
        dry_run: don't write to DB, just count what would happen
        rate_limit_seconds: sleep between employer fetches (politeness;
            sequential path only — the parallel path relies on adapters'
            own per-page delays)
        workers: employer fetches run in a thread pool of this size
            (default CHARON_GATHER_WORKERS or 4, cap 8); 1 = sequential
        on_progress: callback invoked with each employer summary
            (always on the calling thread)

    Returns a list of per-employer summaries. On the parallel path the
    list is in completion order, not registry order.
    """
    registry = load_registry()
    pairs = list_employers(registry, ats=ats)
    if slug:
        pairs = [(a, e) for a, e in pairs if e.get("slug") == slug]

    if not pairs:
        return []

    skip_companies = get_applied_companies()
    summaries: list[dict[str, Any]] = []

    # Skip ATSs whose adapter isn't implemented yet — surface clearly,
    # don't fail the whole run (and never send them to the pool).
    def _unimplemented_summary(ats_name: str, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "ats": ats_name,
            "slug": entry.get("slug", "?"),
            "name": entry.get("name", entry.get("slug", "?")),
            "fetched": 0,
            "new": 0,
            "dupes": 0,
            "skipped": 0,
            "error": f"adapter for '{ats_name}' not yet implemented",
        }

    pool_size = min(_resolve_workers(workers), len(pairs))

    if pool_size <= 1 or len(pairs) <= 1:
        for i, (ats_name, entry) in enumerate(pairs):
            if ats_name not in ADAPTERS:
                summary = _unimplemented_summary(ats_name, entry)
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

    known = []
    for ats_name, entry in pairs:
        if ats_name not in ADAPTERS:
            summary = _unimplemented_summary(ats_name, entry)
            summaries.append(summary)
            if on_progress:
                on_progress(summary)
        else:
            known.append((ats_name, entry))

    with ThreadPoolExecutor(max_workers=min(pool_size, max(1, len(known)))) as pool:
        futures = {
            pool.submit(
                gather_employer,
                ats_name,
                entry,
                dry_run=dry_run,
                skip_companies=skip_companies,
            ): (ats_name, entry)
            for ats_name, entry in known
        }
        try:
            for fut in as_completed(futures):
                ats_name, entry = futures[fut]
                try:
                    summary = fut.result()
                except Exception as e:  # noqa: BLE001 — isolate; don't kill the run
                    summary = _unimplemented_summary(ats_name, entry)
                    summary["error"] = f"{type(e).__name__}: {e}"
                summaries.append(summary)
                if on_progress:
                    on_progress(summary)
        except BaseException:
            # Ctrl-C: drop queued employers, let in-flight ones finish, propagate.
            for f in futures:
                f.cancel()
            raise

    return summaries
