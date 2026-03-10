"""Tests for digest generation."""

import json
import pytest

from charon.db import queue_digest, get_unsent_digest, mark_digest_sent
from charon.digest import build_digest, preview_digest, DigestError


class TestBuildDigest:
    def test_empty_digest(self):
        # Mark all existing entries as sent first
        entries = get_unsent_digest()
        if entries:
            mark_digest_sent([e["id"] for e in entries])

        subject, body, ids = build_digest()
        assert subject == ""
        assert body == ""
        assert ids == []

    def test_digest_with_entries(self):
        # Mark existing, then add fresh
        entries = get_unsent_digest()
        if entries:
            mark_digest_sent([e["id"] for e in entries])

        queue_digest("ghostbust", "Ghost score: 85% - rockstar ninja posting")
        queue_digest("dossier", "Dossier: CrowdStrike - Score: 71/100")

        subject, body, ids = build_digest()
        assert "Charon Digest" in subject
        assert "Ghost score: 85%" in body
        assert "CrowdStrike" in body
        assert len(ids) >= 2

        # Clean up
        mark_digest_sent(ids)

    def test_digest_groups_by_type(self):
        entries = get_unsent_digest()
        if entries:
            mark_digest_sent([e["id"] for e in entries])

        queue_digest("ghostbust", "Ghost analysis 1")
        queue_digest("ghostbust", "Ghost analysis 2")
        queue_digest("redflags", "Red flag scan 1")

        subject, body, ids = build_digest()
        assert "Ghost Job Analysis" in body
        assert "Red Flag Scan" in body

        mark_digest_sent(ids)

    def test_digest_includes_score_from_detail(self):
        entries = get_unsent_digest()
        if entries:
            mark_digest_sent([e["id"] for e in entries])

        queue_digest("ghostbust", "Test entry", {"ghost_score": 42})

        _, body, ids = build_digest()
        assert "42" in body

        mark_digest_sent(ids)

    def test_response_entries_at_top(self):
        entries = get_unsent_digest()
        if entries:
            mark_digest_sent([e["id"] for e in entries])

        queue_digest("response", "CrowdStrike replied - INTERVIEW INVITE")
        queue_digest("ghostbust", "Some ghost analysis")

        _, body, ids = build_digest()
        # Responses should appear before activity
        response_pos = body.find("RESPONSES RECEIVED")
        activity_pos = body.find("Today's Activity")
        assert response_pos < activity_pos

        mark_digest_sent(ids)


class TestPreviewDigest:
    def test_preview_returns_body(self):
        entries = get_unsent_digest()
        if entries:
            mark_digest_sent([e["id"] for e in entries])

        queue_digest("hunt", "Hunt: TestCorp - Score: 80/100")
        body = preview_digest()
        assert "TestCorp" in body
        assert "Full Hunt" in body

        # Preview should NOT mark as sent
        body2 = preview_digest()
        assert "TestCorp" in body2

        # Clean up
        entries = get_unsent_digest()
        mark_digest_sent([e["id"] for e in entries])

    def test_preview_empty(self):
        entries = get_unsent_digest()
        if entries:
            mark_digest_sent([e["id"] for e in entries])

        body = preview_digest()
        assert body == ""


class TestSendDigest:
    def test_send_requires_enabled(self):
        from charon.digest import send_digest

        profile = {"notifications": {"enabled": False}}
        with pytest.raises(DigestError, match="disabled"):
            send_digest(profile)

    def test_send_requires_mail_config(self):
        from charon.digest import send_digest

        # Make sure there's something to send
        queue_digest("test", "Test for send validation")

        profile = {
            "notifications": {
                "enabled": True,
                "mail_server": "",
                "mail_from": "",
                "mail_to": "",
            }
        }
        with pytest.raises(DigestError, match="not configured"):
            send_digest(profile)

        # Clean up
        entries = get_unsent_digest()
        mark_digest_sent([e["id"] for e in entries])
