"""Tests for URL validation and text extraction."""

import pytest

from charon.fetcher import validate_url, extract_text, FetchError


# ── URL validation ───────────────────────────────────────────────────


class TestURLValidation:
    def test_valid_https_url(self):
        result = validate_url("https://example.com/jobs/123")
        assert result == "https://example.com/jobs/123"

    def test_valid_http_url(self):
        result = validate_url("http://example.com/jobs/123")
        assert result == "http://example.com/jobs/123"

    def test_strips_whitespace(self):
        result = validate_url("  https://example.com  ")
        assert result == "https://example.com"

    def test_security_rejects_file_scheme(self):
        with pytest.raises(FetchError, match="not allowed"):
            validate_url("file:///etc/passwd")

    def test_security_rejects_ftp(self):
        with pytest.raises(FetchError, match="not allowed"):
            validate_url("ftp://evil.com/payload")

    def test_security_rejects_javascript(self):
        with pytest.raises(FetchError, match="not allowed"):
            validate_url("javascript:alert(1)")

    def test_security_rejects_localhost(self):
        with pytest.raises(FetchError, match="not allowed"):
            validate_url("http://localhost/admin")

    def test_security_rejects_127(self):
        with pytest.raises(FetchError, match="not allowed"):
            validate_url("http://127.0.0.1/admin")

    def test_security_rejects_private_10(self):
        with pytest.raises(FetchError, match="Private IP"):
            validate_url("http://10.0.0.1/admin")

    def test_security_rejects_private_192(self):
        with pytest.raises(FetchError, match="Private IP"):
            validate_url("http://192.168.1.1/admin")

    def test_security_rejects_private_172(self):
        with pytest.raises(FetchError, match="Private IP"):
            validate_url("http://172.16.0.1/admin")

    def test_security_rejects_null_bytes(self):
        with pytest.raises(FetchError, match="null bytes"):
            validate_url("https://example.com\x00/evil")

    def test_security_rejects_embedded_credentials(self):
        with pytest.raises(FetchError, match="credentials"):
            validate_url("http://user:pass@example.com/")

    def test_rejects_empty(self):
        with pytest.raises(FetchError, match="Empty URL"):
            validate_url("")

    def test_rejects_no_hostname(self):
        with pytest.raises(FetchError):
            validate_url("https://")


# ── Text extraction ──────────────────────────────────────────────────


class TestTextExtraction:
    def test_extracts_body_text(self):
        html = "<html><body><p>Senior Engineer needed</p></body></html>"
        result = extract_text(html)
        assert "Senior Engineer needed" in result

    def test_strips_script_tags(self):
        html = "<html><body><script>alert('xss')</script><p>Real content</p></body></html>"
        result = extract_text(html)
        assert "alert" not in result
        assert "Real content" in result

    def test_strips_style_tags(self):
        html = "<html><body><style>.evil{}</style><p>Job posting</p></body></html>"
        result = extract_text(html)
        assert ".evil" not in result
        assert "Job posting" in result

    def test_strips_nav_footer(self):
        html = "<html><body><nav>Menu</nav><main>Job content</main><footer>Copyright</footer></body></html>"
        result = extract_text(html)
        assert "Job content" in result
        assert "Menu" not in result
        assert "Copyright" not in result

    def test_raises_on_empty_content(self):
        html = "<html><body><script>only scripts</script></body></html>"
        with pytest.raises(FetchError, match="No readable text"):
            extract_text(html)

    def test_collapses_whitespace(self):
        html = "<html><body><p>Line 1</p>\n\n\n\n\n<p>Line 2</p></body></html>"
        result = extract_text(html)
        assert "\n\n\n" not in result
