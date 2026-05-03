"""Tests for tier 3: LLM router (Anthropic + OpenRouter prefix)."""

import httpx
import pytest

from charon.enrich import llm
from charon.enrich.llm import LLMError


# ── result handling ─────────────────────────────────────────────────


class TestResultOrNone:
    def test_returns_text(self):
        long_text = (
            "This is a real description that's long enough. " * 4
        ).strip()
        assert llm._result_or_none(long_text) == long_text

    def test_no_description_sentinel(self):
        assert llm._result_or_none("NO_DESCRIPTION_FOUND") is None

    def test_no_description_sentinel_with_trailing(self):
        assert llm._result_or_none("NO_DESCRIPTION_FOUND — page was login wall.") is None

    def test_empty_returns_none(self):
        assert llm._result_or_none("") is None
        assert llm._result_or_none("   ") is None

    def test_too_short_returns_none(self):
        # Below the 100-char floor — likely garbage
        assert llm._result_or_none("Yes.") is None


# ── input trimming ──────────────────────────────────────────────────


class TestTrimInput:
    def test_short_passes_through(self):
        text = "short text"
        assert llm._trim_input(text) == text

    def test_long_truncated(self):
        text = "x" * (llm.MAX_INPUT_CHARS + 1000)
        out = llm._trim_input(text)
        assert len(out) < len(text)
        assert out.endswith("[truncated]")


# ── OpenRouter routing ──────────────────────────────────────────────


class TestOpenRouterPrefix:
    def test_openrouter_prefix_dispatches_to_openrouter(self, monkeypatch):
        captured = {}

        def fake_openrouter(text, model, profile=None):
            captured["text"] = text
            captured["model"] = model
            return "Returned description from OpenRouter, plenty long for the floor check."

        monkeypatch.setattr(llm, "_extract_via_openrouter", fake_openrouter)
        result = llm.extract_description(
            "page text", model="openrouter:google/gemini-flash-2-0"
        )
        assert captured["model"] == "google/gemini-flash-2-0"
        assert "OpenRouter" in result

    def test_bare_name_dispatches_to_anthropic(self, monkeypatch):
        captured = {}

        def fake_anthropic(text, model):
            captured["model"] = model
            return "Description from native Anthropic SDK, also long enough to pass."

        monkeypatch.setattr(llm, "_extract_via_anthropic", fake_anthropic)
        result = llm.extract_description("page text", model="claude-haiku-4-5")
        assert captured["model"] == "claude-haiku-4-5"
        assert "Anthropic" in result

    def test_empty_input_returns_none(self, monkeypatch):
        # Should not even attempt to call any backend
        called = {"n": 0}
        def boom(*a, **kw):
            called["n"] += 1
            return "x"
        monkeypatch.setattr(llm, "_extract_via_anthropic", boom)
        monkeypatch.setattr(llm, "_extract_via_openrouter", boom)
        assert llm.extract_description("") is None
        assert llm.extract_description("   ") is None
        assert called["n"] == 0


# ── OpenRouter HTTP call ────────────────────────────────────────────


class TestOpenRouterHTTP:
    @staticmethod
    def _patch_client(monkeypatch, status: int, payload):
        """Patch httpx.Client used inside llm.py to return a pre-built mock."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json=payload)
        mock = httpx.Client(transport=httpx.MockTransport(handler))
        # Lambda receives **kwargs from `httpx.Client(timeout=...)` and ignores them
        monkeypatch.setattr(llm.httpx, "Client", lambda *a, **kw: mock)
        return mock

    def test_unwraps_chat_choice(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
        long_content = (
            "Description content from the model that is long enough to pass the floor. " * 3
        ).strip()
        self._patch_client(
            monkeypatch, 200,
            {"choices": [{"message": {"content": long_content}}]},
        )
        result = llm._extract_via_openrouter("page", "google/gemini-flash-2-0")
        assert "Description content" in result

    def test_401_raises(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "bad-key")
        self._patch_client(monkeypatch, 401, {"error": "unauthorized"})
        with pytest.raises(LLMError, match="rejected"):
            llm._extract_via_openrouter("page", "test/model")

    def test_429_raises(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "x")
        self._patch_client(monkeypatch, 429, {"error": "rate"})
        with pytest.raises(LLMError, match="rate limit"):
            llm._extract_via_openrouter("page", "test/model")

    def test_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(LLMError, match="No OpenRouter API key"):
            llm._extract_via_openrouter("page", "test/model", profile=None)
