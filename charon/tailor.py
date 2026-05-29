"""Forge — place a static resume into a ready discovery's offerings folder.

Charon keeps two curated resumes and routes by the judge's closest_target:
GRC/audit roles get the GRC resume, everything else gets the IR/blue-team
resume. The chosen markdown is copied verbatim — no LLM, no fabrication
risk. Materials land in `<offerings_dir>/<company-slug>-<role-slug>-<id>/`.

Cover letters are still tailored per posting (see letter.py), which is why
this module retains the shared LLM helpers (`_generate`,
`verify_against_source`, `_build_audit`, `_trim_input`) and their model
routing:
  bare name -> native Anthropic SDK
  "openrouter:vendor/model" -> OpenRouter chat-completions API
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from charon.resume_match import ResumeMatchError, load_resume_text
from charon.secrets import SecretsError, read_secret


DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_OFFERINGS_DIR = "~/.charon/offerings"
TIMEOUT_SECONDS = 90

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"


class ForgeError(Exception):
    """Raised when forging fails for reasons the user should see."""


# ── slugification + folder layout ───────────────────────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    """Lowercase, strip non-alphanumerics to single hyphens, truncate."""
    if not text:
        return "unknown"
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "unknown"


def offerings_folder(
    discovery: dict[str, Any],
    *,
    base_dir: str = DEFAULT_OFFERINGS_DIR,
) -> Path:
    """Compute the path for a discovery's offerings folder.

    Format: <base>/<company-slug>-<role-slug>-<id>/
    """
    company_slug = slugify(discovery.get("company") or "unknown", max_len=24)
    role_slug = slugify(discovery.get("role") or "unknown", max_len=32)
    discovery_id = discovery.get("id", "x")
    folder_name = f"{company_slug}-{role_slug}-{discovery_id}"
    return Path(os.path.expanduser(base_dir)) / folder_name


# ── post-gen verifier ───────────────────────────────────────────────


# Capture standalone numeric tokens including percentages and thousands
# separators. Examples it matches: "12", "47%", "10,000", "2.5", "2024".
# `%` is captured because we want to flag percentage claims specifically.
_NUMBER_RE = re.compile(r"\b\d{1,6}(?:,\d{3})*(?:\.\d+)?%?")


def _normalize_for_match(text: str) -> str:
    """Lowercase + collapse whitespace for fuzzy-contains checks."""
    return re.sub(r"\s+", " ", text.lower())


def _extract_numerical_claims(text: str) -> set[str]:
    """Pull all numeric tokens out of the generated resume."""
    return {m.group(0) for m in _NUMBER_RE.finditer(text)}


def _claim_variants(claim: str) -> list[str]:
    """Build matching variants for a numeric claim.

    Handles different formattings of the same number:
      "10,000" -> ["10,000", "10000"]
      "47%"    -> ["47%", "47"]
      "30%"    -> also tries "30 percent"
    """
    base = claim.lower()
    no_comma = base.replace(",", "")
    variants = {base, no_comma}
    if "%" in base:
        bare = base.rstrip("%")
        bare_no_comma = no_comma.rstrip("%")
        variants.update({bare, bare_no_comma, f"{bare} percent", f"{bare_no_comma} percent"})
    return list(variants)


def verify_against_source(generated: str, source: str) -> list[str]:
    """Find numerical claims in `generated` that don't appear in `source`.

    Returns a list of unverified claim strings. Empty list = clean.

    Intentionally fuzzy — the goal is "loud warning on possible fabrication,"
    not "block on every formatting variation." User reviews the output
    before submitting.
    """
    if not generated or not source:
        return []

    source_norm = _normalize_for_match(source)
    source_no_commas = source_norm.replace(",", "")

    unverified: list[str] = []
    for claim in _extract_numerical_claims(generated):
        # Skip single-digit noise — these are likely list markers, not metrics.
        # Strip trailing % before checking length.
        bare = claim.rstrip("%").rstrip(".")
        if re.fullmatch(r"\d", bare):
            continue

        # Verify against the source under multiple normalizations
        if any(
            v in source_norm or v in source_no_commas
            for v in _claim_variants(claim)
        ):
            continue

        unverified.append(claim)

    return sorted(set(unverified))


# ── model routing ───────────────────────────────────────────────────


def _trim_input(text: str, cap: int = 80_000) -> str:
    """Cap absurdly large inputs."""
    if len(text) <= cap:
        return text
    return text[:cap] + "\n[truncated]"


def _generate_via_anthropic(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
) -> tuple[str, dict[str, int]]:
    try:
        import anthropic
    except ImportError as e:
        raise ForgeError("anthropic SDK not installed.") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ForgeError("Set ANTHROPIC_API_KEY environment variable.")

    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=10.0),
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.3,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.AuthenticationError:
        raise ForgeError("Invalid Anthropic API key.")
    except anthropic.RateLimitError:
        raise ForgeError("Anthropic rate limit reached.")
    except anthropic.APIStatusError as e:
        raise ForgeError(f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise ForgeError("Cannot reach Anthropic API.")

    if not response.content:
        raise ForgeError("Empty response from Anthropic.")
    text = response.content[0].text
    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
    }
    return text, usage


def _get_openrouter_key(profile: dict[str, Any] | None) -> str:
    if profile:
        vault_cfg = profile.get("vault", {}) or {}
        if vault_cfg.get("url"):
            prefix = vault_cfg.get("secret_prefix", "charon")
            try:
                data = read_secret(vault_cfg, f"{prefix}/openrouter-api")
                key = data.get("api_key") or data.get("password")
                if key:
                    return str(key)
            except SecretsError:
                pass
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise ForgeError(
            "No OpenRouter API key. Set OPENROUTER_API_KEY env var or store at "
            "Vault path <prefix>/openrouter-api with key 'api_key'."
        )
    return key


def _generate_via_openrouter(
    system_prompt: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
    profile: dict[str, Any] | None,
) -> tuple[str, dict[str, int]]:
    api_key = _get_openrouter_key(profile)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Pickle-Pixel/Charon",
        "X-Title": "Charon",
    }
    body = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(OPENROUTER_API, json=body, headers=headers)
    except httpx.TimeoutException:
        raise ForgeError(f"OpenRouter timed out for model '{model}'.")
    except httpx.RequestError as e:
        raise ForgeError(f"OpenRouter request failed: {type(e).__name__}") from e

    if response.status_code == 401:
        raise ForgeError("OpenRouter rejected the API key.")
    if response.status_code == 429:
        raise ForgeError("OpenRouter rate limit reached.")
    if response.status_code >= 400:
        raise ForgeError(f"OpenRouter HTTP {response.status_code}: {response.text[:200]}")

    try:
        data = response.json()
    except ValueError as e:
        raise ForgeError("OpenRouter returned non-JSON response.") from e

    choices = data.get("choices") or []
    if not choices:
        raise ForgeError("OpenRouter returned no choices.")
    text = choices[0].get("message", {}).get("content", "")
    usage_data = data.get("usage") or {}
    usage = {
        "input_tokens": int(usage_data.get("prompt_tokens", 0)),
        "output_tokens": int(usage_data.get("completion_tokens", 0)),
    }
    return text, usage


def _generate(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str,
    max_tokens: int,
    profile: dict[str, Any] | None,
) -> tuple[str, dict[str, int]]:
    if model.startswith("openrouter:"):
        actual = model.removeprefix("openrouter:")
        return _generate_via_openrouter(
            system_prompt, user_prompt, actual, max_tokens, profile
        )
    return _generate_via_anthropic(system_prompt, user_prompt, model, max_tokens)


# ── core forge logic ────────────────────────────────────────────────


DEFAULT_GRC_TARGETS = [
    "compliance auditor",
    "it auditor",
    "grc analyst",
    "security auditor",
]


def _forge_config(profile: dict[str, Any] | None) -> dict[str, Any]:
    cfg = (profile or {}).get("forge") or {}
    grc_targets = cfg.get("grc_targets")
    if not isinstance(grc_targets, list) or not grc_targets:
        grc_targets = DEFAULT_GRC_TARGETS
    return {
        "model": cfg.get("model", DEFAULT_MODEL),
        "max_tokens": int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS)),
        "offerings_dir": cfg.get("offerings_dir", DEFAULT_OFFERINGS_DIR),
        "resume_path": (profile or {}).get("resume_path") or "",
        # Two static resumes. GRC-type roles get grc_resume_md; everything
        # else gets default_resume_md (the IR / blue-team resume).
        "grc_resume_md": cfg.get("grc_resume_md", ""),
        "default_resume_md": cfg.get("default_resume_md", ""),
        "grc_targets": [str(t).strip().lower() for t in grc_targets],
    }


def _closest_target(discovery: dict[str, Any]) -> str:
    """Pull role_alignment.closest_target from stored judgement_detail."""
    detail_raw = discovery.get("judgement_detail")
    if not detail_raw:
        return ""
    try:
        import json
        detail = json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
    except (ValueError, TypeError):
        return ""
    if not isinstance(detail, dict):
        return ""
    ra = detail.get("role_alignment") or {}
    if not isinstance(ra, dict):
        return ""
    return str(ra.get("closest_target") or "").strip()


def _is_grc_role(discovery: dict[str, Any], grc_targets: list[str]) -> bool:
    """True when the judge's closest_target marks this as a GRC-type role."""
    ct = _closest_target(discovery).lower()
    return bool(ct) and ct in grc_targets


def forge_discovery(
    discovery: dict[str, Any],
    *,
    profile: dict[str, Any],
    resume_text: str | None = None,
    model_override: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Place a static resume into a ready discovery's offerings folder.

    Charon keeps two curated resumes — a GRC/audit one and an IR/blue-team
    one — and routes by the judge's closest_target: GRC-type roles get
    grc_resume_md, everything else gets default_resume_md. The chosen
    markdown is copied verbatim. No LLM call, no fabrication risk. Cover
    letters are still tailored per posting (see letter.py).

    `resume_text` and `model_override` are accepted for call-site
    compatibility but ignored — there's no tailoring to feed them into.

    Returns a result dict:
        {discovery_id, offerings_path, resume_path, audit_path,
         unverified_claims, usage, model, resume_kind, error?}
    """
    cfg = _forge_config(profile)

    if discovery.get("screened_status") != "ready":
        return {
            "discovery_id": discovery.get("id"),
            "error": (
                f"Discovery #{discovery.get('id')} is "
                f"'{discovery.get('screened_status')}', not 'ready'. "
                "Forge only runs on ready discoveries."
            ),
        }

    # Route to the static resume by role type.
    if _is_grc_role(discovery, cfg["grc_targets"]):
        md_path_str = cfg["grc_resume_md"]
        resume_kind = "GRC"
        cfg_key = "grc_resume_md"
    else:
        md_path_str = cfg["default_resume_md"]
        resume_kind = "IR"
        cfg_key = "default_resume_md"

    if not md_path_str:
        return {
            "discovery_id": discovery.get("id"),
            "error": f"No {resume_kind} resume configured. Set profile.forge.{cfg_key}.",
        }
    md_path = Path(os.path.expanduser(md_path_str))
    if not md_path.is_file():
        return {
            "discovery_id": discovery.get("id"),
            "error": f"{resume_kind} resume markdown not found on disk: {md_path}",
        }

    folder = offerings_folder(discovery, base_dir=cfg["offerings_dir"])
    resume_out = folder / "resume.md"
    if resume_out.exists() and not force:
        return {
            "discovery_id": discovery.get("id"),
            "offerings_path": str(folder),
            "resume_path": str(resume_out),
            "skipped_reason": "offerings folder already exists (use --force to overwrite)",
        }

    folder.mkdir(parents=True, exist_ok=True)
    resume_out.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")

    audit_out = folder / "forge_audit.md"
    audit_out.write_text(
        "# Forge Audit Trail\n\n"
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}\n"
        f"- **Discovery:** #{discovery.get('id')} — "
        f"{discovery.get('company')} — {discovery.get('role')}\n"
        f"- **Mode:** static {resume_kind} resume (no LLM tailoring)\n"
        f"- **Source:** `{md_path}`\n"
        f"- **closest_target:** {_closest_target(discovery)!r}\n\n"
        f"This role was routed to the {resume_kind} resume and copied "
        "verbatim. No AI calls were made; no fabrication risk.\n",
        encoding="utf-8",
    )

    return {
        "discovery_id": discovery.get("id"),
        "offerings_path": str(folder),
        "resume_path": str(resume_out),
        "audit_path": str(audit_out),
        "unverified_claims": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "model": f"static-{resume_kind.lower()} (no LLM)",
        "resume_kind": resume_kind,
    }


def _build_audit(
    *,
    title: str = "Audit Trail",
    model: str,
    usage: dict[str, int],
    unverified: list[str],
    system_prompt: str,
    user_prompt: str,
    generated: str,
    discovery: dict[str, Any],
) -> str:
    parts = [
        f"# {title}",
        "",
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Model:** `{model}`",
        f"- **Discovery:** #{discovery.get('id')} — "
        f"{discovery.get('company')} — {discovery.get('role')}",
        f"- **Posting URL:** {discovery.get('url') or '(none)'}",
        f"- **Combined score at forge time:** {discovery.get('combined_score')}",
        f"- **Tokens:** in={usage.get('input_tokens', 0)} "
        f"out={usage.get('output_tokens', 0)}",
        "",
        "## Verifier",
        "",
    ]
    if unverified:
        parts.append(
            f"⚠ **{len(unverified)} unverified numerical claim(s) in output.** "
            "Each appears in the generated resume but NOT in the source resume "
            "text. Review these manually before submitting:"
        )
        parts.append("")
        for claim in unverified:
            parts.append(f"- `{claim}`")
    else:
        parts.append("✓ All numerical claims in the output trace back to the source resume.")

    parts.extend([
        "",
        "## System Prompt",
        "",
        "```",
        system_prompt,
        "```",
        "",
        "## User Prompt",
        "",
        "```",
        user_prompt,
        "```",
        "",
        "## Raw Output",
        "",
        "```markdown",
        generated,
        "```",
    ])
    return "\n".join(parts)


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_OFFERINGS_DIR",
    "ForgeError",
    "forge_discovery",
    "offerings_folder",
    "slugify",
    "verify_against_source",
]
