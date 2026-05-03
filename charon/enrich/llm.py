"""Tier 3 enrichment: LLM-based description extraction.

Pluggable model routing:

  model: "claude-haiku-4-5"               -> native Anthropic SDK
  model: "claude-sonnet-4-20250514"        -> native Anthropic SDK
  model: "openrouter:anthropic/claude-haiku-4-5"
  model: "openrouter:google/gemini-flash-2-0"
  model: "openrouter:deepseek/deepseek-chat"

Bare names go through the `anthropic` SDK we already depend on. The
`openrouter:` prefix routes through OpenRouter's OpenAI-compatible
chat-completions API via httpx (no new SDK dependency).

The OpenRouter API key is loaded from Vault
(secret/<prefix>/openrouter-api, key `api_key`) with env var
fallback (`OPENROUTER_API_KEY`).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from charon.secrets import SecretsError, read_secret


DEFAULT_MODEL = "claude-haiku-4-5"
MAX_INPUT_CHARS = 50_000  # cap on cleaned page text we send to the LLM
MAX_OUTPUT_TOKENS = 2048
TIMEOUT_SECONDS = 60

OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "You extract the job description text from a careers page. "
    "Return only the description body — responsibilities, qualifications, "
    "about-the-role, benefits, location, salary range if present. "
    "Strip site navigation, application form copy, footer boilerplate, "
    "cookie notices, and EEO statements. Do NOT add commentary, headings, "
    "or summaries of your own. If the input clearly does not contain a job "
    "description, return the literal text NO_DESCRIPTION_FOUND."
)


class LLMError(Exception):
    """Raised when the LLM tier fails."""


def _trim_input(text: str) -> str:
    if len(text) <= MAX_INPUT_CHARS:
        return text
    return text[:MAX_INPUT_CHARS] + "\n[truncated]"


def _result_or_none(raw: str) -> str | None:
    """Return the text or None if the model signalled no description."""
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip()
    if cleaned == "NO_DESCRIPTION_FOUND" or cleaned.startswith("NO_DESCRIPTION_FOUND"):
        return None
    if len(cleaned) < 100:
        return None
    return cleaned


def _extract_via_anthropic(text: str, model: str) -> str | None:
    try:
        import anthropic
    except ImportError as e:
        raise LLMError("anthropic SDK not installed.") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError(
            "No Anthropic API key. Set ANTHROPIC_API_KEY environment variable."
        )

    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=10.0),
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _trim_input(text)}],
        )
    except anthropic.AuthenticationError:
        raise LLMError("Invalid Anthropic API key.")
    except anthropic.RateLimitError:
        raise LLMError("Anthropic rate limit reached.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise LLMError("Cannot reach Anthropic API.")

    if not response.content:
        return None
    raw = response.content[0].text
    return _result_or_none(raw)


def _get_openrouter_key(profile: dict[str, Any] | None) -> str:
    """Vault first, env var fallback."""
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
        raise LLMError(
            "No OpenRouter API key. Set OPENROUTER_API_KEY env var or store at "
            "Vault path <prefix>/openrouter-api with key 'api_key'."
        )
    return key


def _extract_via_openrouter(
    text: str,
    model: str,
    profile: dict[str, Any] | None = None,
) -> str | None:
    api_key = _get_openrouter_key(profile)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Pickle-Pixel/Charon",
        "X-Title": "Charon",
    }
    body = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _trim_input(text)},
        ],
    }

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(OPENROUTER_API, json=body, headers=headers)
    except httpx.TimeoutException:
        raise LLMError(f"OpenRouter timed out for model '{model}'.")
    except httpx.RequestError as e:
        raise LLMError(f"OpenRouter request failed: {type(e).__name__}") from e

    if response.status_code == 401:
        raise LLMError("OpenRouter rejected the API key.")
    if response.status_code == 429:
        raise LLMError("OpenRouter rate limit reached.")
    if response.status_code >= 400:
        raise LLMError(f"OpenRouter HTTP {response.status_code}: {response.text[:200]}")

    try:
        data = response.json()
    except ValueError as e:
        raise LLMError("OpenRouter returned non-JSON response.") from e

    choices = data.get("choices") or []
    if not choices:
        return None
    message = choices[0].get("message") or {}
    raw = message.get("content") or ""
    return _result_or_none(raw)


def extract_description(
    text: str,
    model: str = DEFAULT_MODEL,
    profile: dict[str, Any] | None = None,
) -> str | None:
    """Extract a job description via LLM. Returns the description or None.

    Routing:
        - bare model name -> native Anthropic SDK
        - "openrouter:vendor/model" -> OpenRouter chat-completions API
    """
    if not text or not text.strip():
        return None

    if model.startswith("openrouter:"):
        actual = model.removeprefix("openrouter:")
        return _extract_via_openrouter(text, actual, profile=profile)

    return _extract_via_anthropic(text, model)
