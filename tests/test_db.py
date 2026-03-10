"""Tests for database operations."""

import pytest

from charon.db import (
    save_history,
    get_history,
    clear_history,
    add_watch,
    remove_watch,
    get_watchlist,
    queue_digest,
    get_unsent_digest,
    mark_digest_sent,
)


class TestHistory:
    def test_save_and_retrieve(self):
        save_history("ghostbust", "url", "https://example.com/job", 42.0, {"test": True})
        entries = get_history(limit=1)
        assert len(entries) >= 1
        latest = entries[0]
        assert latest["command"] == "ghostbust"
        assert latest["score"] == 42.0

    def test_clear_history(self):
        save_history("test", "url", "https://example.com", 0.0, {})
        count = clear_history()
        assert count >= 1
        assert len(get_history()) == 0

    def test_security_sql_injection_in_command(self):
        """SQL injection attempt in command field should be stored as literal text."""
        malicious = "'; DROP TABLE history;--"
        save_history(malicious, "url", "https://example.com", 0.0, {})
        entries = get_history(limit=1)
        assert entries[0]["command"] == malicious

    def test_security_sql_injection_in_input(self):
        """SQL injection in input_value should be harmless."""
        malicious = "https://example.com' OR '1'='1"
        save_history("ghostbust", "url", malicious, 0.0, {})
        entries = get_history(limit=1)
        assert entries[0]["input_value"] == malicious


class TestWatchlist:
    def test_add_and_list(self):
        add_watch("TestCorp_unique_12345")
        watchlist = get_watchlist()
        companies = [w["company"] for w in watchlist]
        assert "TestCorp_unique_12345" in companies

    def test_remove(self):
        add_watch("RemoveMe_unique_99999")
        assert remove_watch("RemoveMe_unique_99999") is True
        assert remove_watch("RemoveMe_unique_99999") is False  # already removed

    def test_duplicate_add_ignored(self):
        add_watch("DupeCorp_unique_77777")
        add_watch("DupeCorp_unique_77777")  # should not raise
        count = sum(1 for w in get_watchlist() if w["company"] == "DupeCorp_unique_77777")
        assert count == 1


class TestDigest:
    def test_queue_and_retrieve(self):
        queue_digest("ghostbust", "Analyzed example.com job posting", {"score": 42})
        entries = get_unsent_digest()
        assert len(entries) >= 1
        assert entries[-1]["entry_type"] == "ghostbust"

    def test_mark_sent(self):
        queue_digest("test", "Test entry for mark_sent")
        entries = get_unsent_digest()
        test_entries = [e for e in entries if e["summary"] == "Test entry for mark_sent"]
        assert len(test_entries) >= 1
        mark_digest_sent([test_entries[0]["id"]])
        remaining = get_unsent_digest()
        remaining_summaries = [e["summary"] for e in remaining]
        assert "Test entry for mark_sent" not in remaining_summaries
