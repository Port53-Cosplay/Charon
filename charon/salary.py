"""Salary-intel for a specific offering.

Pulls a fair-market range FOR THIS CANDIDATE — not a generic role lookup.
The prompt is given:

  - The actual posting (role title, company, full description with any
    salary range or location hints).
  - The candidate's resume text (so "just graduated" / "no direct
    industry experience" / "decade in financial-crimes investigation"
    are weighted instead of getting a senior-IC number for an entry-level
    candidate).
  - The candidate's target_roles from profile.yaml (signals where they're
    aiming in the market, so the negotiation framing is realistic).

Web search is on. Salary data goes stale fast and the whole point of
asking is to get a current number to negotiate with. Typical cost on
Sonnet with ~5 web-search calls: ~$0.05 per query.

Output: a structured JSON range + reasoning + negotiation notes, saved
to the offering folder as ``salary_intel.md`` so it lives next to the
resume / cover letter / contacts.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


SALARY_FILENAME = "salary_intel.md"


class SalaryError(Exception):
    pass


SALARY_SYSTEM_PROMPT = """\
You are a compensation researcher helping a specific job candidate
estimate a fair salary range for a specific posting.

Your job is NOT to give a generic market range for the role. It is to:
  1. Find current (2025-2026) market data for this role and seniority.
  2. Calibrate that data against THIS CANDIDATE's actual background
     (years of experience, direct industry experience, transferable
     skills, recent graduation, certifications, etc.). A candidate
     with a decade of financial-crimes investigation and a brand-new
     cybersecurity degree gets a DIFFERENT number than a senior IC
     with five years in DFIR consulting.
  3. Return a range that is realistic for THEM to ask for and
     negotiate against — not a sticker-shock ceiling, not a floor that
     undersells transferable experience.

Use web search to ground your numbers. Prefer reputable sources:
Levels.fyi, Glassdoor, Payscale, BLS, Robert Half's annual salary
guide, role-specific posts on h1bdata, recent comp threads on
TeamBlind / Reddit. Cross-reference at least two sources.

Output JSON ONLY, matching this schema exactly:

{
  "currency": "USD",
  "low": 95000,
  "mid": 115000,
  "high": 135000,
  "confidence": "low" | "medium" | "high",
  "rationale": "1-3 sentence summary of the market data + how this
                candidate's background shifts the range vs. a generic
                applicant for the role.",
  "experience_adjustment": "1-2 sentences naming what specifically
                            in this candidate's background pushed the
                            number up or down (e.g. 'a decade of
                            fraud-investigation experience pushes the
                            ask above true entry-level despite the
                            recent degree').",
  "negotiation": "1-3 sentences on how to use the range — what to
                  ask for first, where to be willing to flex, what
                  signal a posted range gives.",
  "posted_range": "string or null — the salary range stated in the
                   posting itself, if any. Quote it verbatim.",
  "sources": ["short label of each source consulted"]
}

Numbers are annual base salary in the currency named, US Dollars
unless the posting specifies otherwise. Do NOT include equity, RSUs,
bonuses, or sign-on in the low/mid/high — call those out separately
in `rationale` or `negotiation` if relevant. Do NOT pad with
hedging — give specific numbers.
"""


def _summarize_resume(resume_text: str, max_chars: int = 3500) -> str:
    """Truncate the resume to a reasonable size for the prompt while
    keeping the most signal-dense parts. The first ~3500 chars usually
    cover summary + recent experience, which is what the salary model
    needs to calibrate seniority.
    """
    if not resume_text:
        return ""
    text = resume_text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[truncated — older history omitted]"


def _format_markdown(
    discovery_id: int,
    company: str,
    role: str,
    result: dict[str, Any],
) -> str:
    currency = result.get("currency") or "USD"
    sym = "$" if currency == "USD" else f"{currency} "

    def fmt_money(v: Any) -> str:
        try:
            return f"{sym}{int(v):,}"
        except (TypeError, ValueError):
            return "—"

    low = fmt_money(result.get("low"))
    mid = fmt_money(result.get("mid"))
    high = fmt_money(result.get("high"))
    confidence = (result.get("confidence") or "").strip() or "—"

    today = datetime.now().strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# Salary Intel: {company}",
        "",
        f"## {role}",
        "",
        f"**Suggested range:** {low} — {high} {currency}",
        f"**Target ask:** {mid}",
        f"**Confidence:** {confidence.title()}",
    ]

    posted = result.get("posted_range")
    if posted:
        lines.extend(["", f"_Posting states:_ {posted}"])

    rationale = (result.get("rationale") or "").strip()
    if rationale:
        lines.extend(["", "## How the number was built", "", rationale])

    exp = (result.get("experience_adjustment") or "").strip()
    if exp:
        lines.extend(["", "## How your background factored in", "", exp])

    negotiation = (result.get("negotiation") or "").strip()
    if negotiation:
        lines.extend(["", "## Negotiation guidance", "", negotiation])

    sources = result.get("sources") or []
    if isinstance(sources, list) and sources:
        lines.extend(["", "## Sources consulted", ""])
        for s in sources:
            lines.append(f"- {s}")

    lines.extend(["", "---", f"Generated {today} · Discovery #{discovery_id}"])
    return "\n".join(lines) + "\n"


def suggest_salary_for_discovery(discovery_id: int) -> dict[str, Any]:
    """Run the web-search salary lookup for a discovery and persist
    the result to its offerings folder.

    Returns a summary dict with the file path and the structured fields
    (low/mid/high/confidence). Raises SalaryError on prerequisite
    failures (missing discovery, missing offerings folder).
    """
    from charon.ai import AIError, query_claude_web_search_json
    from charon.db import get_discovery
    from charon.profile import load_profile
    from charon.tailor import load_resume_text

    discovery = get_discovery(discovery_id)
    if discovery is None:
        raise SalaryError(f"No discovery with id {discovery_id}.")

    folder_str = discovery.get("offerings_path")
    if not folder_str:
        raise SalaryError(
            f"No offerings folder for #{discovery_id}. "
            f"Run `charon provision --id {discovery_id}` first."
        )
    folder = Path(folder_str)
    if not folder.exists():
        raise SalaryError(f"Offerings folder missing on disk: {folder}")

    try:
        profile = load_profile()
    except Exception as e:  # noqa: BLE001
        raise SalaryError(f"Profile error: {e}") from e

    resume_text = ""
    resume_path = (profile or {}).get("resume_path", "")
    if resume_path:
        try:
            resume_text = load_resume_text(resume_path) or ""
        except Exception:  # noqa: BLE001 — best-effort
            resume_text = ""
    resume_block = _summarize_resume(resume_text)

    target_roles = profile.get("target_roles") if isinstance(profile, dict) else None
    if not isinstance(target_roles, list):
        target_roles = []

    company = (discovery.get("company") or "").strip()
    role = (discovery.get("role") or "").strip()
    location = (discovery.get("location") or "").strip()
    description = (
        discovery.get("full_description")
        or discovery.get("description")
        or ""
    ).strip()

    target_block = ", ".join(target_roles) if target_roles else "(none in profile)"

    user_prompt = (
        f"## Posting\n\n"
        f"Role: {role}\n"
        f"Company: {company}\n"
        f"Location: {location or '(not specified)'}\n\n"
        f"Description:\n{description}\n\n"
        f"## Candidate background\n\n"
        f"Target role areas: {target_block}\n\n"
        f"Resume (excerpt):\n{resume_block}\n\n"
        f"## Ask\n\n"
        f"Give me a fair-market base-salary range for THIS candidate applying "
        f"to THIS posting. Calibrate against the candidate's actual experience "
        f"and any salary cues in the posting. Return ONLY the JSON described "
        f"in the system prompt."
    )

    try:
        result = query_claude_web_search_json(
            SALARY_SYSTEM_PROMPT,
            user_prompt,
            max_tokens=2048,
            max_searches=5,
        )
    except AIError as e:
        raise SalaryError(f"AI call failed: {e}") from e

    # Light validation — bad shape becomes a SalaryError so the caller
    # can surface it cleanly rather than crashing on `int(None)`.
    for key in ("low", "mid", "high"):
        val = result.get(key)
        try:
            int(val)
        except (TypeError, ValueError):
            raise SalaryError(
                f"AI returned an unusable range (missing/non-numeric '{key}'): {result!r}"
            )

    md_text = _format_markdown(discovery_id, company, role, result)
    out_path = folder / SALARY_FILENAME
    out_path.write_text(md_text, encoding="utf-8")

    return {
        "id": discovery_id,
        "company": company,
        "role": role,
        "path": str(out_path),
        "currency": result.get("currency") or "USD",
        "low": int(result.get("low")),
        "mid": int(result.get("mid")),
        "high": int(result.get("high")),
        "confidence": result.get("confidence"),
        "posted_range": result.get("posted_range"),
    }


__all__ = ["SalaryError", "SALARY_FILENAME", "suggest_salary_for_discovery"]
