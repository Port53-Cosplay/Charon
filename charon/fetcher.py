"""URL fetching and text extraction with security validation."""

import re
import sys
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


# Safety limits
MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_PASTE_SIZE = 500_000  # 500 KB
REQUEST_TIMEOUT = 30  # seconds
ALLOWED_SCHEMES = {"http", "https"}

# Strip these tags — they add noise, not signal
STRIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"}


class FetchError(Exception):
    """Raised when fetching or parsing fails."""


def validate_url(url: str) -> str:
    """Validate and normalize a URL. Returns the cleaned URL or raises FetchError."""
    url = url.strip()

    if not url:
        raise FetchError("Empty URL. The ferryman needs a destination.")

    # Reject null bytes
    if "\x00" in url:
        raise FetchError("Invalid URL — contains null bytes.")

    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise FetchError(
            f"Scheme '{parsed.scheme}' not allowed. Only HTTP and HTTPS — "
            "the ferryman doesn't travel to strange realms."
        )

    if not parsed.hostname:
        raise FetchError("No hostname in URL. Where exactly are we going?")

    # Block private/localhost ranges (SSRF prevention)
    hostname = parsed.hostname.lower()
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1"}
    if hostname in blocked_hosts:
        raise FetchError("Local addresses are not allowed. The underworld is elsewhere.")

    # Block private and reserved IP ranges (including cloud metadata endpoints)
    private_ip_pattern = (
        r"^("
        r"10\."                                    # 10.0.0.0/8
        r"|172\.(1[6-9]|2\d|3[01])\."             # 172.16.0.0/12
        r"|192\.168\."                             # 192.168.0.0/16
        r"|169\.254\."                             # link-local / cloud metadata
        r"|127\."                                  # loopback
        r"|0\."                                    # 0.0.0.0/8
        r")"
    )
    if re.match(private_ip_pattern, hostname):
        raise FetchError("Private IP ranges are not allowed.")

    # Block octal/hex IP representations (bypass attempts)
    if re.match(r"^(0x[0-9a-f]|0[0-7])", hostname):
        raise FetchError("Encoded IP addresses are not allowed.")

    # Strip credentials from URL if present
    if parsed.username or parsed.password:
        raise FetchError("URLs with embedded credentials are not accepted. Nice try.")

    return url


def fetch_html(url: str) -> str:
    """Fetch a URL and return raw HTML. Validated, size-capped, redirect-limited."""
    url = validate_url(url)

    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            response = client.get(
                url,
                headers={"User-Agent": "Charon/0.7 (Job Posting Analyzer)"},
            )
            response.raise_for_status()

            # Check content size
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                raise FetchError(
                    f"Response too large ({int(content_length)} bytes). "
                    "The ferryman's boat has a weight limit."
                )

            content = response.text
            if len(content) > MAX_RESPONSE_SIZE:
                raise FetchError("Response too large. The ferryman's boat has a weight limit.")

            return content

    except httpx.TimeoutException:
        raise FetchError("Request timed out. The other side didn't answer.")
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code}. The gates are closed.")
    except httpx.RequestError as e:
        raise FetchError(f"Connection failed: {type(e).__name__}. The river is impassable.")


def fetch_url(url: str) -> str:
    """Fetch a URL and extract readable text content."""
    return extract_text(fetch_html(url))


# Patterns indicating a closed/expired job posting (case-insensitive)
CLOSED_POSTING_PATTERNS = [
    r"no longer accepting applications",
    r"this job is no longer available",
    r"this position has been filled",
    r"this job has expired",
    r"this listing has expired",
    r"this posting has been closed",
    r"this role has been filled",
    r"applications are closed",
    r"job closed",
    r"position filled",
    r"no longer active",
    r"this job is closed",
    r"no longer open",
    r"this opening (?:is|has been) closed",
    r"we are no longer (?:accepting|considering) applications",
    r"this job is not currently accepting applications",
]

_CLOSED_RE = re.compile("|".join(CLOSED_POSTING_PATTERNS), re.IGNORECASE)


def extract_text(html: str) -> str:
    """Extract readable text from HTML, stripping noise."""
    soup = BeautifulSoup(html, "html.parser")

    # Check raw HTML for closed-posting signals before stripping tags
    closed_match = _CLOSED_RE.search(html)

    # Remove noisy elements
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()

    # Try to find the main content area
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=re.compile(r"job|posting|description|content", re.I))
        or soup.find("body")
    )

    if main is None:
        main = soup

    text = main.get_text(separator="\n", strip=True)

    # Also check extracted text for closed signals
    if not closed_match:
        closed_match = _CLOSED_RE.search(text)

    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    if not text.strip():
        raise FetchError("No readable text found. The posting may be behind a login wall or JavaScript-rendered.")

    # Prepend closed-posting warning so AI analysis sees it
    if closed_match:
        text = (
            "[CHARON NOTICE: This posting appears to be CLOSED/EXPIRED. "
            f"Detected signal: \"{closed_match.group()}\"]\n\n{text.strip()}"
        )

    return text.strip()


def read_paste() -> str:
    """Read job posting text from stdin."""
    if sys.stdin.isatty():
        from charon.output import print_info
        print_info("Paste the job posting text below. Press Ctrl+D (Unix) or Ctrl+Z (Windows) when done.")
        print_info("-" * 60)

    lines = []
    total_size = 0
    try:
        for line in sys.stdin:
            total_size += len(line)
            if total_size > MAX_PASTE_SIZE:
                raise FetchError(
                    f"Input exceeds {MAX_PASTE_SIZE // 1000}KB limit. "
                    "That's a novel, not a job posting."
                )
            lines.append(line)
    except KeyboardInterrupt:
        pass

    text = "".join(lines).strip()

    if not text:
        raise FetchError("No input received. The ferryman waits, but not forever.")

    # Strip ANSI escape sequences (terminal injection prevention)
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)

    return text
