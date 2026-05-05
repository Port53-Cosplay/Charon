"""Claude API interface for all AI-powered analysis."""

import json
import os
import re
from pathlib import Path
from typing import Any

import anthropic
import httpx

from charon.output import print_error


MODEL = "claude-sonnet-4-20250514"
DEFAULT_TEMPERATURE = 0.2
MAX_TOKENS = 4096


class AIError(Exception):
    """Raised when AI analysis fails."""


def get_client() -> anthropic.Anthropic:
    """Get an Anthropic client. API key must be in ANTHROPIC_API_KEY env var."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIError(
            "No API key found. Set ANTHROPIC_API_KEY environment variable.\n"
            "  The ferryman doesn't work for free."
        )
    return anthropic.Anthropic(
        api_key=api_key,
        timeout=httpx.Timeout(300.0, connect=10.0),
    )


def query_claude(
    system_prompt: str,
    user_prompt: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """Send a query to Claude and return the text response."""
    client = get_client()

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        if not response.content:
            raise AIError("Empty response from Claude. The oracle is silent.")

        return response.content[0].text

    # KeyboardInterrupt is intentionally NOT caught — it must propagate up
    # so batch loops in screen.py / enrich/__init__.py terminate immediately
    # rather than swallowing Ctrl+C as a per-row "AI error" and continuing.
    except anthropic.AuthenticationError:
        raise AIError("Invalid API key. The ferryman rejects your coin.")
    except anthropic.RateLimitError:
        raise AIError("Rate limited. Even the dead must wait their turn. Try again shortly.")
    except anthropic.APIStatusError as e:
        raise AIError(f"API error ({e.status_code}): {e.message}. The oracle is troubled.")
    except anthropic.APIConnectionError:
        raise AIError("Cannot reach the API. The underworld has no signal.")


def query_claude_web_search(
    system_prompt: str,
    user_prompt: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    max_searches: int = 10,
) -> str:
    """Send a query to Claude with web search enabled. Returns combined text response."""
    client = get_client()

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max_searches,
            }],
        )

        if not response.content:
            raise AIError("Empty response from Claude. The oracle is silent.")

        # Extract all text blocks from the mixed response
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)

        if not text_parts:
            raise AIError("No text in response. The oracle searched but said nothing.")

        return "\n".join(text_parts)

    # KeyboardInterrupt intentionally NOT caught — must propagate. See
    # rationale on query_claude above.
    except anthropic.AuthenticationError:
        raise AIError("Invalid API key. The ferryman rejects your coin.")
    except anthropic.RateLimitError:
        raise AIError("Rate limited. Even the dead must wait their turn. Try again shortly.")
    except anthropic.APIStatusError as e:
        raise AIError(f"API error ({e.status_code}): {e.message}. The oracle is troubled.")
    except anthropic.APIConnectionError:
        raise AIError("Cannot reach the API. The underworld has no signal.")


def query_claude_web_search_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    max_searches: int = 10,
) -> dict[str, Any]:
    """Send a web-search-enabled query and parse the JSON response."""
    raw = query_claude_web_search(
        system_prompt, user_prompt, temperature, max_tokens, max_searches
    )
    return _parse_json_response(raw)


def _repair_json_strings(text: str) -> str:
    """Repair broken JSON from AI responses.

    Handles common issues:
    1. Unescaped quotes inside string values:
       "evidence": "some text" and "more text"
    2. Unquoted trailing text after a string value:
       "evidence": "some text" trailing words without closing quote
    3. Comma-separated quoted strings used as a single value:
       "evidence": "text one", "text two", "text three"
    """
    # Pre-pass: fix comma-separated quoted strings in values.
    # Pattern: a key-value line where the value contains ", " separating
    # multiple quoted segments that aren't valid JSON keys (no ":" after them).
    import re
    lines = text.split("\n")
    repaired_lines = []

    for line in lines:
        stripped = line.strip()
        # Detect lines like: "key": "val1", "val2", "val3"
        # where val2/val3 don't have ":" after them (so they're not real keys)
        kv_match = re.match(r'^("[\w\s]+")\s*:\s*"', stripped)
        if kv_match:
            # Find everything after the ": "
            colon_pos = stripped.index(":")
            after_colon = stripped[colon_pos + 1:].strip()
            # Check if it has the pattern: "...", "..." without colons
            # Count unescaped quotes
            segments = re.split(r'(?<!\\)",\s*"', after_colon)
            if len(segments) > 1:
                # Multiple quoted segments — merge them into one value
                # Strip leading/trailing quotes and rejoin with semicolons
                merged_parts = []
                for seg in segments:
                    clean = seg.strip().strip('"').rstrip(',').rstrip()
                    if clean:
                        merged_parts.append(clean)
                # Rebuild the line
                trailing = ""
                if stripped.rstrip().endswith(","):
                    trailing = ","
                merged_value = "; ".join(merged_parts)
                # Escape any remaining unescaped quotes in the merged value
                merged_value = merged_value.replace('"', '\\"')
                indent = line[:len(line) - len(line.lstrip())]
                repaired_lines.append(f'{indent}{kv_match.group(1)}: "{merged_value}"{trailing}')
                continue

        repaired_lines.append(_repair_json_line(line))

    return "\n".join(repaired_lines)


def _repair_json_line(line: str) -> str:
    """Repair a single line of JSON."""
    stripped = line.strip()

    # Skip non-string-value lines
    if not stripped or stripped in ("{", "}", "[", "]", "},", "],"):
        return line

    # Look for the pattern: "key": "value" extra stuff
    # Find the key-value structure
    import re as _re
    match = _re.match(r'^(\s*"[^"]*"\s*:\s*)"(.*)$', line)
    if not match:
        # Not a key-value line, or it's a simple value — leave alone
        return line

    prefix = match.group(1)  # e.g. '      "evidence": '
    rest = match.group(2)     # everything after the opening quote of the value

    # Find the "real" closing quote: the last quote on the line that's followed
    # by optional whitespace and then either comma, }, ], or end of line
    # If no such quote exists, the whole rest is the value (missing close quote)
    best_end = -1
    i = 0
    while i < len(rest):
        if rest[i] == '\\' and i + 1 < len(rest):
            i += 2
            continue
        if rest[i] == '"':
            after = rest[i + 1:].strip()
            if not after or after[0] in ',:]}':
                best_end = i
                # Don't break — take the LAST valid closing quote
                # Actually, take the first valid one for key-value pairs
                # but we need the one that leaves valid JSON after it
                break
        i += 1

    if best_end == -1:
        # No valid closing quote found — the AI left the string unclosed
        # Escape any internal quotes and add a closing quote
        value_text = rest.rstrip().rstrip(",")
        trailing = ""
        if rest.rstrip().endswith(","):
            trailing = ","
        escaped = value_text.replace('\\', '\\\\').replace('"', '\\"')
        return f'{prefix}"{escaped}"{trailing}'

    # We found a valid closing quote, but there might be unescaped quotes before it
    value_part = rest[:best_end]
    after_part = rest[best_end:]  # includes the closing quote

    # Escape any unescaped quotes within the value
    escaped_value = ""
    j = 0
    while j < len(value_part):
        if value_part[j] == '\\' and j + 1 < len(value_part):
            escaped_value += value_part[j:j + 2]
            j += 2
        elif value_part[j] == '"':
            escaped_value += '\\"'
            j += 1
        else:
            escaped_value += value_part[j]
            j += 1

    return f'{prefix}"{escaped_value}{after_part}'


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Extract and parse JSON from a Claude text response."""
    text = raw.strip()

    # Try to find JSON in the response — it may be wrapped in markdown or have text around it
    # First try: the whole thing is JSON
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Second try: strip markdown code fences
    if "```" in text:
        lines = text.split("\n")
        in_block = False
        json_lines = []
        for line in lines:
            if line.strip().startswith("```") and not in_block:
                in_block = True
                continue
            elif line.strip() == "```" and in_block:
                break
            elif in_block:
                json_lines.append(line)
        if json_lines:
            fenced_json = "\n".join(json_lines)
            try:
                result = json.loads(fenced_json)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass
            # Try repairing unescaped quotes inside the fenced JSON
            repaired = _repair_json_strings(fenced_json)
            try:
                result = json.loads(repaired)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    # Third try: find first { to last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Fourth try: repair broken JSON strings (unescaped quotes in values)
        repaired = _repair_json_strings(candidate)
        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # Debug: dump raw response to help diagnose parse failures
    debug_path = Path.home() / ".charon" / "last_failed_response.txt"
    try:
        debug_path.write_text(raw, encoding="utf-8")
    except OSError:
        pass

    raise AIError(
        "Failed to parse AI response as JSON.\n"
        "The oracle spoke in tongues. Try again.\n"
        f"(Raw response saved to {debug_path})"
    )


def query_claude_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> dict[str, Any]:
    """Send a query to Claude and parse the JSON response."""
    raw = query_claude(system_prompt, user_prompt, temperature, max_tokens)
    return _parse_json_response(raw)
