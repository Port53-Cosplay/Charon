"""Tests for detect_ats — URL pattern recognition for --add."""

import pytest

from charon.gather import detect_ats


class TestGreenhouseDetection:
    def test_boards_root(self):
        result = detect_ats("https://boards.greenhouse.io/datadog")
        assert result == ("greenhouse", {"slug": "datadog", "name": "datadog"})

    def test_boards_with_job_path(self):
        result = detect_ats("https://boards.greenhouse.io/datadog/jobs/12345")
        assert result == ("greenhouse", {"slug": "datadog", "name": "datadog"})

    def test_new_job_boards_subdomain(self):
        result = detect_ats("https://job-boards.greenhouse.io/anthropic/jobs/9001")
        assert result == ("greenhouse", {"slug": "anthropic", "name": "anthropic"})

    def test_strips_query_string(self):
        result = detect_ats("https://boards.greenhouse.io/datadog?gh_src=foo")
        assert result == ("greenhouse", {"slug": "datadog", "name": "datadog"})


class TestLeverDetection:
    def test_root_slug(self):
        result = detect_ats("https://jobs.lever.co/sysdig")
        assert result == ("lever", {"slug": "sysdig", "name": "sysdig"})

    def test_with_uuid(self):
        result = detect_ats("https://jobs.lever.co/sysdig/abc-123-def")
        assert result == ("lever", {"slug": "sysdig", "name": "sysdig"})

    def test_no_slug_returns_none(self):
        assert detect_ats("https://jobs.lever.co/") is None


class TestAshbyDetection:
    def test_root_slug(self):
        result = detect_ats("https://jobs.ashbyhq.com/vanta")
        assert result == ("ashby", {"slug": "vanta", "name": "vanta"})

    def test_with_uuid(self):
        result = detect_ats("https://jobs.ashbyhq.com/vanta/uuid-here")
        assert result == ("ashby", {"slug": "vanta", "name": "vanta"})

    def test_custom_subdomain(self):
        # Some Ashby tenants serve at <slug>.ashbyhq.com
        result = detect_ats("https://semgrep.ashbyhq.com/jobs/x")
        assert result == ("ashby", {"slug": "semgrep", "name": "semgrep"})


class TestWorkdayDetection:
    def test_basic(self):
        result = detect_ats(
            "https://schellman.wd1.myworkdayjobs.com/Careers/job/Tampa/Senior_R1"
        )
        ats, entry = result
        assert ats == "workday"
        assert entry["slug"] == "schellman"
        assert entry["workday"] == {"tenant": "schellman", "wd": "wd1", "site": "Careers"}

    def test_with_language_prefix(self):
        result = detect_ats(
            "https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/job/Remote/X"
        )
        ats, entry = result
        assert ats == "workday"
        assert entry["workday"] == {
            "tenant": "crowdstrike",
            "wd": "wd5",
            "site": "crowdstrikecareers",
        }

    def test_with_german_language(self):
        result = detect_ats(
            "https://example.wd3.myworkdayjobs.com/de-DE/Careers/job/Munich/X"
        )
        ats, entry = result
        assert entry["workday"]["site"] == "Careers"

    def test_site_only_no_job_path(self):
        result = detect_ats("https://bitsight.wd1.myworkdayjobs.com/Bitsight")
        ats, entry = result
        assert entry["workday"] == {"tenant": "bitsight", "wd": "wd1", "site": "Bitsight"}

    def test_root_no_site_returns_none(self):
        assert detect_ats("https://x.wd1.myworkdayjobs.com/") is None


class TestNonMatching:
    def test_unknown_host(self):
        assert detect_ats("https://example.com/jobs") is None

    def test_linkedin(self):
        assert detect_ats("https://www.linkedin.com/jobs/view/12345") is None

    def test_indeed(self):
        assert detect_ats("https://www.indeed.com/viewjob?jk=abc") is None

    def test_no_scheme(self):
        assert detect_ats("boards.greenhouse.io/datadog") is None

    def test_empty(self):
        assert detect_ats("") is None
