"""Batch hunt: run recon against a file of URLs, output scores table."""

import time
from pathlib import Path
from typing import Any

from charon.ai import AIError
from charon.fetcher import FetchError
from charon.hunt import run_hunt_recon


def _compute_recon_score(result: dict) -> float:
    """Compute overall score from recon-only results (0-100, higher is better)."""
    scores = []

    ghost = result.get("ghostbust")
    if ghost:
        scores.append(100 - ghost["ghost_score"])

    redflag = result.get("redflags")
    if redflag:
        scores.append(100 - redflag["redflag_score"])

    role_align = result.get("role_alignment")
    if role_align:
        scores.append(role_align.get("alignment_score", 50))

    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 1)


def _format_score(value, invert: bool = False) -> str:
    """Format a score for the table, or '-' if missing."""
    if value is None:
        return "-"
    return str(int(value))


def _build_results_table(entries: list[dict]) -> str:
    """Build a plain ASCII table of results, sorted by overall descending."""
    sorted_entries = sorted(entries, key=lambda e: e["overall"], reverse=True)

    # Column widths
    hdr = f"{'Overall':>7}  {'Ghost':>5}  {'RedFlag':>7}  {'RoleAln':>7}  URL"
    sep = "-" * len(hdr)
    lines = [hdr, sep]

    for e in sorted_entries:
        overall = _format_score(e["overall"])
        ghost = _format_score(e["ghost"])
        redflag = _format_score(e["redflag"])
        role = _format_score(e["role_align"])
        error = f"  ({e['error']})" if e.get("error") else ""
        lines.append(f"{overall:>7}  {ghost:>5}  {redflag:>7}  {role:>7}  {e['url']}{error}")

    return "\n".join(lines) + "\n"


def _build_top_detail(entry: dict) -> str:
    """Build plain-text detail output for a high-scoring entry."""
    lines = [f"=== {entry['url']} === Overall: {entry['overall']}", ""]
    result = entry["result"]

    ghost = result.get("ghostbust")
    if ghost:
        lines.append(f"--- Ghost Analysis (Score: {ghost['ghost_score']}) ---")
        lines.append(f"Confidence: {ghost.get('confidence', 'N/A').upper()}")
        for s in ghost.get("signals", []):
            marker = {"red": "[X]", "yellow": "[!]", "green": "[+]"}.get(s.get("severity"), "[ ]")
            lines.append(f"  {marker} {s.get('category', '')}: {s.get('finding', '')}")
        lines.append("")

    redflag = result.get("redflags")
    if redflag:
        lines.append(f"--- Red Flags (Score: {redflag['redflag_score']}) ---")
        for d in redflag.get("dealbreakers_found", []):
            lines.append(f"  [X] {d.get('flag', '')}")
            if d.get("evidence"):
                lines.append(f"      \"{d['evidence']}\"")
        for y in redflag.get("yellow_flags_found", []):
            lines.append(f"  [!] {y.get('flag', '')}")
            if y.get("evidence"):
                lines.append(f"      \"{y['evidence']}\"")
        for g in redflag.get("green_flags_found", []):
            lines.append(f"  [+] {g.get('flag', '')}")
        lines.append("")

    role_align = result.get("role_alignment")
    if role_align:
        lines.append(f"--- Role Alignment (Score: {role_align.get('alignment_score', 0)}) ---")
        closest = role_align.get("closest_target")
        if closest:
            lines.append(f"Closest target: {closest}")
        for item in role_align.get("overlap", []):
            lines.append(f"  [+] {item}")
        for item in role_align.get("gaps", []):
            lines.append(f"  [-] {item}")
        stepping = role_align.get("stepping_stone", False)
        lines.append(f"Stepping stone: {'Yes' if stepping else 'No'}")
        assessment = role_align.get("assessment", "")
        if assessment:
            lines.append(f"Assessment: {assessment}")
        lines.append("")

    return "\n".join(lines)


def run_batch(
    input_path: str,
    threshold: int,
    profile: dict[str, Any],
    on_progress: callable = None,
) -> dict[str, Any]:
    """Run recon against each URL in input_path. Returns summary dict.

    on_progress(current, total, url, status) is called for CLI display.
    """
    path = Path(input_path)
    urls = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not urls:
        return {"entries": [], "total": 0, "above_threshold": 0, "errors": 0}

    entries = []
    errors = 0

    for i, url in enumerate(urls):
        if on_progress:
            on_progress(i + 1, len(urls), url, "scanning")

        entry = {
            "url": url,
            "overall": 0.0,
            "ghost": None,
            "redflag": None,
            "role_align": None,
            "result": {},
            "error": None,
        }

        try:
            result, _ = run_hunt_recon(url, False, profile)
            entry["result"] = result

            ghost = result.get("ghostbust")
            if ghost:
                entry["ghost"] = ghost["ghost_score"]

            redflag = result.get("redflags")
            if redflag:
                entry["redflag"] = redflag["redflag_score"]

            role_align = result.get("role_alignment")
            if role_align:
                entry["role_align"] = role_align.get("alignment_score")

            entry["overall"] = _compute_recon_score(result)

        except (FetchError, AIError) as e:
            entry["error"] = str(e)[:80]
            errors += 1
        except Exception as e:
            entry["error"] = f"Unexpected: {str(e)[:60]}"
            errors += 1

        entries.append(entry)

        if on_progress:
            on_progress(i + 1, len(urls), url, "done")

        # Rate limit delay (skip after the last one)
        if i < len(urls) - 1:
            time.sleep(1.5)

    # Write results table
    stem = path.stem
    out_dir = path.parent

    results_path = out_dir / f"{stem}_results.txt"
    results_path.write_text(_build_results_table(entries), encoding="utf-8")

    # Write top results if any exceed threshold
    top = [e for e in entries if e["overall"] > threshold and not e.get("error")]
    top_path = None
    if top:
        top_sorted = sorted(top, key=lambda e: e["overall"], reverse=True)
        detail_blocks = [_build_top_detail(e) for e in top_sorted]
        top_path = out_dir / f"{stem}_results_top.txt"
        top_path.write_text("\n\n".join(detail_blocks) + "\n", encoding="utf-8")

    return {
        "entries": entries,
        "total": len(urls),
        "above_threshold": len(top),
        "errors": errors,
        "results_path": str(results_path),
        "top_path": str(top_path) if top_path else None,
    }
