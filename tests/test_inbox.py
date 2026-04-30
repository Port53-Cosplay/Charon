"""Tests for inbox monitoring (no live IMAP required)."""

import pytest

from charon.inbox import (
    InboxError,
    _build_imap_search,
    _decode_header,
    CLASSIFY_SYSTEM,
    CLASSIFICATION_TO_STATUS,
)


class TestBuildImapSearch:
    def test_with_domains(self):
        apps = [
            {"email_domain": "crowdstrike.com", "company": "CrowdStrike"},
            {"email_domain": "rapid7.com", "company": "Rapid7"},
        ]
        queries = _build_imap_search(apps, days=7)
        assert any("crowdstrike.com" in q for q in queries)
        assert any("rapid7.com" in q for q in queries)
        assert any("SINCE" in q for q in queries)

    def test_with_company_names_only(self):
        apps = [
            {"company": "Palo Alto", "email_domain": None},
        ]
        queries = _build_imap_search(apps, days=7)
        assert any("Palo Alto" in q for q in queries)

    def test_empty_applications(self):
        queries = _build_imap_search([], days=7)
        assert queries == []

    def test_no_useful_data(self):
        apps = [{"company": "", "email_domain": None}]
        queries = _build_imap_search(apps, days=7)
        # Empty company string shouldn't generate a query
        assert len(queries) == 0

    def test_custom_days(self):
        apps = [{"email_domain": "test.com", "company": "Test"}]
        queries = _build_imap_search(apps, days=14)
        assert any("SINCE" in q for q in queries)

    def test_deduplicates_domains(self):
        apps = [
            {"email_domain": "same.com", "company": "Same"},
            {"email_domain": "same.com", "company": "Same"},
        ]
        queries = _build_imap_search(apps, days=7)
        domain_queries = [q for q in queries if "same.com" in q]
        assert len(domain_queries) == 1


class TestDecodeHeader:
    def test_plain_ascii(self):
        assert _decode_header("Hello World") == "Hello World"

    def test_empty(self):
        assert _decode_header("") == ""

    def test_none(self):
        assert _decode_header(None) == ""


class TestClassifyPrompt:
    def test_system_prompt_structure(self):
        assert "is_job_response" in CLASSIFY_SYSTEM
        assert "classification" in CLASSIFY_SYSTEM
        assert "interview" in CLASSIFY_SYSTEM
        assert "rejection" in CLASSIFY_SYSTEM

    def test_system_prompt_excludes_marketing(self):
        assert "marketing" in CLASSIFY_SYSTEM.lower() or "newsletter" in CLASSIFY_SYSTEM.lower()


class TestClassificationToStatus:
    def test_interview_maps_to_interviewing(self):
        assert CLASSIFICATION_TO_STATUS["interview"] == "interviewing"

    def test_offer_maps_to_offered(self):
        assert CLASSIFICATION_TO_STATUS["offer"] == "offered"

    def test_rejection_maps_to_rejected(self):
        assert CLASSIFICATION_TO_STATUS["rejection"] == "rejected"

    def test_acknowledgment_maps_to_acknowledged(self):
        # HOWTO.md distinguishes 'acknowledged' (machine auto-receipt) from
        # 'responded' (actual human reply). Acknowledgment classifications
        # come from auto-emails like "thanks for applying" — they are
        # acknowledged, not responded.
        assert CLASSIFICATION_TO_STATUS["acknowledgment"] == "acknowledged"

    def test_other_not_mapped(self):
        assert "other" not in CLASSIFICATION_TO_STATUS

    def test_all_mapped_statuses_are_valid(self):
        from charon.db import VALID_STATUSES
        for status in CLASSIFICATION_TO_STATUS.values():
            assert status in VALID_STATUSES


class TestInboxErrors:
    def test_scan_no_accounts(self):
        from charon.inbox import scan_inbox

        profile = {"inbox": {"accounts": []}}
        with pytest.raises(InboxError, match="No inbox accounts"):
            scan_inbox(profile)

    def test_scan_missing_inbox_config(self):
        from charon.inbox import scan_inbox

        profile = {}
        with pytest.raises(InboxError, match="No inbox accounts"):
            scan_inbox(profile)
