"""Tests for digest generation."""

import pytest

from charon.db import add_application
from charon.digest import build_digest, preview_digest, DigestError


class TestBuildDigest:
    def test_empty_digest(self):
        subject, body, html = build_digest()
        assert subject == ""
        assert body == ""
        assert html == ""

    def test_digest_with_applications(self):
        add_application("TestCorp", "Security Engineer")
        add_application("AcmeCo", "Pentester")

        subject, body, html = build_digest()
        assert "Charon Digest" in subject
        assert "TestCorp" in body
        assert "AcmeCo" in body
        assert "Security Engineer" in body
        assert "Pentester" in body

    def test_digest_shows_status(self):
        from charon.db import update_application_status
        app_id = add_application("InterviewCo", "Red Team Lead")
        update_application_status(app_id, "interviewing")

        _, body, _ = build_digest()
        assert "INTERVIEWING" in body

    def test_digest_groups_by_status(self):
        from charon.db import update_application_status
        id1 = add_application("AckCorp", "Analyst")
        update_application_status(id1, "acknowledged")
        add_application("WaitingCorp", "Engineer")

        _, body, _ = build_digest()
        ack_pos = body.find("ACKNOWLEDGED")
        applied_pos = body.find("APPLIED")
        assert ack_pos < applied_pos

    def test_digest_html_contains_table(self):
        add_application("HtmlTestCo", "Dev")

        _, _, html = build_digest()
        assert "<table" in html
        assert "HtmlTestCo" in html

    def test_digest_includes_app_count(self):
        add_application("CountCo", "Role1")
        add_application("CountCo2", "Role2")

        _, body, _ = build_digest()
        assert "application(s)" in body


class TestPreviewDigest:
    def test_preview_returns_body(self):
        add_application("PreviewCorp", "Security Analyst")
        body = preview_digest()
        assert "PreviewCorp" in body

    def test_preview_empty(self):
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

        add_application("MailTestCo", "Tester")

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
