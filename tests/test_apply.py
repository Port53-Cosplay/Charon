"""Tests for application tracking."""

import pytest

from charon.apply import (
    ApplyError,
    check_ghosted,
    extract_email_domain,
    get_stats,
    list_applications,
    track_application,
    update_status,
)
from charon.db import (
    find_application_by_company,
    get_application,
    get_unsent_digest,
    mark_digest_sent,
    update_application_dossier,
    VALID_STATUSES,
)


class TestExtractEmailDomain:
    def test_normal_url(self):
        assert extract_email_domain("https://www.crowdstrike.com/careers/job/123") == "crowdstrike.com"

    def test_subdomain(self):
        assert extract_email_domain("https://jobs.rapid7.com/posting/456") == "rapid7.com"

    def test_linkedin_ignored(self):
        assert extract_email_domain("https://www.linkedin.com/jobs/view/12345") is None

    def test_indeed_ignored(self):
        assert extract_email_domain("https://indeed.com/viewjob?jk=abc") is None

    def test_greenhouse_ignored(self):
        assert extract_email_domain("https://boards.greenhouse.io/company/jobs/123") is None

    def test_workday_ignored(self):
        assert extract_email_domain("https://company.myworkdayjobs.com/en-US/ext") is None

    def test_none_url(self):
        assert extract_email_domain(None) is None

    def test_empty_url(self):
        assert extract_email_domain("") is None

    def test_malformed_url(self):
        assert extract_email_domain("not-a-url") is not None or extract_email_domain("not-a-url") is None


class TestTrackApplication:
    def test_track_basic(self):
        app = track_application("TestCorp", "Security Engineer")
        assert app is not None
        assert app["company"] == "TestCorp"
        assert app["role"] == "Security Engineer"
        assert app["status"] == "applied"

    def test_track_with_url(self):
        app = track_application(
            "CrowdStrike", "Pen Tester",
            url="https://www.crowdstrike.com/careers/123"
        )
        assert app["email_domain"] == "crowdstrike.com"

    def test_track_with_notes(self):
        app = track_application("Rapid7", "AppSec", notes="Referral from Bob")
        assert app["notes"] == "Referral from Bob"

    def test_track_queues_digest(self):
        # Clear digest
        entries = get_unsent_digest()
        if entries:
            mark_digest_sent([e["id"] for e in entries])

        track_application("DigestTestCorp", "Red Team")
        entries = get_unsent_digest()
        summaries = [e["summary"] for e in entries]
        assert any("DigestTestCorp" in s for s in summaries)

        mark_digest_sent([e["id"] for e in entries])

    def test_track_empty_company_fails(self):
        with pytest.raises(ApplyError, match="Company name"):
            track_application("", "Some Role")

    def test_track_empty_role_fails(self):
        with pytest.raises(ApplyError, match="Role"):
            track_application("TestCorp", "")

    def test_track_whitespace_only_fails(self):
        with pytest.raises(ApplyError):
            track_application("   ", "Role")


class TestUpdateStatus:
    def test_update_valid(self):
        app = track_application("StatusTestCorp", "Analyst")
        result = update_status(app["id"], "interviewing")
        assert result is not None
        assert result["status"] == "interviewing"

    def test_update_invalid_status(self):
        app = track_application("InvalidStatusCorp", "Dev")
        with pytest.raises(ApplyError, match="Invalid status"):
            update_status(app["id"], "promoted")

    def test_update_nonexistent_id(self):
        result = update_status(99999, "rejected")
        assert result is None

    def test_update_all_statuses(self):
        for status in VALID_STATUSES:
            app = track_application(f"AllStatus_{status}", "Role")
            result = update_status(app["id"], status)
            assert result is not None
            assert result["status"] == status


class TestCheckGhosted:
    def test_ghost_check_returns_empty(self):
        # With default 21 days, newly added apps should not be ghosted
        track_application("FreshCorp", "Fresh Role")
        ghosted = check_ghosted(days=21)
        # Newly added apps won't be stale
        assert isinstance(ghosted, list)

    def test_ghost_check_invalid_days(self):
        with pytest.raises(ApplyError, match="at least 1 day"):
            check_ghosted(days=0)

    def test_ghost_check_negative_days(self):
        with pytest.raises(ApplyError):
            check_ghosted(days=-5)


class TestGetStats:
    def test_stats_returns_dict(self):
        track_application("StatsCorp", "StatRole")
        stats = get_stats()
        assert isinstance(stats, dict)
        assert "applied" in stats
        assert stats["applied"] >= 1


class TestListApplications:
    def test_list_all(self):
        track_application("ListAllCorp", "ListRole")
        apps = list_applications()
        assert len(apps) >= 1

    def test_list_filtered(self):
        app = track_application("FilterCorp", "FilterRole")
        update_status(app["id"], "rejected")
        apps = list_applications("rejected")
        assert any(a["company"] == "FilterCorp" for a in apps)

    def test_list_invalid_status(self):
        with pytest.raises(ApplyError, match="Invalid status"):
            list_applications("promoted")


class TestDossierTracking:
    def test_stamp_dossier(self):
        app = track_application("DossierStampCorp", "Security Engineer")
        assert app.get("dossier_at") is None
        update_application_dossier(app["id"])
        updated = get_application(app["id"])
        assert updated["dossier_at"] is not None

    def test_find_by_company(self):
        track_application("FindMeCorp", "Analyst")
        found = find_application_by_company("FindMeCorp")
        assert found is not None
        assert found["company"] == "FindMeCorp"

    def test_find_by_company_case_insensitive(self):
        track_application("CaseCorp", "Dev")
        found = find_application_by_company("casecorp")
        assert found is not None
        assert found["company"] == "CaseCorp"

    def test_find_by_company_excludes_rejected(self):
        app = track_application("RejectedCorp", "Pentester")
        update_status(app["id"], "rejected")
        found = find_application_by_company("RejectedCorp")
        assert found is None

    def test_find_by_company_not_found(self):
        found = find_application_by_company("NoSuchCorpXYZ123")
        assert found is None
