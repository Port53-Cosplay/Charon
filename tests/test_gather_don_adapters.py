"""Tests for the SmartRecruiters / Recruitee / Workable adapters (ported from Don's fork)."""

import pytest

from charon.gather import ADAPTERS, GatherError, _load_adapter
from charon.gather import recruitee, smartrecruiters, workable


class StubResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class StubClient:
    """Duck-typed httpx.Client — records calls, replays canned responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_adapters_registered_and_loadable():
    for ats in ("smartrecruiters", "recruitee", "workable"):
        assert ats in ADAPTERS
        assert hasattr(_load_adapter(ats), "fetch_jobs")


def test_smartrecruiters_normalizes_and_builds_urls():
    client = StubClient([StubResponse({
        "totalFound": 2,
        "content": [
            {"id": "744000abc", "name": "SOC Analyst",
             "location": {"city": "Austin", "region": "TX", "country": "US", "remote": True},
             "releasedDate": "2026-08-01T00:00:00Z"},
            {"id": "744000def", "name": "GRC Lead", "location": {}},
        ],
    })])
    jobs = smartrecruiters.fetch_jobs("acme", entry={"name": "Acme"}, client=client)
    assert len(jobs) == 2
    assert jobs[0]["url"] == "https://jobs.smartrecruiters.com/acme/744000abc"
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["location"] == "Remote - Austin, TX, US"
    assert jobs[0]["description"] is None      # descriptions come via enrich (JSON-LD)
    assert jobs[1]["location"] is None


def test_smartrecruiters_404_raises():
    client = StubClient([StubResponse({}, status_code=404)])
    with pytest.raises(GatherError, match="404"):
        smartrecruiters.fetch_jobs("gone", client=client)


def test_recruitee_inlines_stripped_descriptions():
    client = StubClient([StubResponse({
        "offers": [
            {"title": "Security Engineer", "careers_url": "https://acme.recruitee.com/o/sec-eng",
             "location": "Remote", "description": "<p>Defend &amp; detect</p><p>the fleet</p>",
             "published_at": "2026-08-02"},
            {"title": "No URL — dropped"},
        ],
    })])
    jobs = recruitee.fetch_jobs("acme", entry={"name": "Acme"}, client=client)
    assert len(jobs) == 1
    assert jobs[0]["description"] == "Defend & detect\nthe fleet"
    assert jobs[0]["posted_at"] == "2026-08-02"


def test_workable_inlines_descriptions_and_remote_location():
    client = StubClient([StubResponse({
        "jobs": [
            {"title": "IT Auditor", "url": "https://apply.workable.com/acme/j/1",
             "city": "Boston", "state": "MA", "country": "US", "telecommuting": True,
             "description": "<div>Audit  the   things</div>", "published_on": "2026-08-03"},
        ],
    })])
    jobs = workable.fetch_jobs("acme", entry={"name": "Acme"}, client=client)
    assert len(jobs) == 1
    assert jobs[0]["location"] == "Remote - Boston, MA, US"
    assert jobs[0]["description"] == "Audit the things"
    assert (client.calls[0][1].get("params") or {}).get("details") == "true"


def test_empty_slug_raises():
    for mod in (smartrecruiters, recruitee, workable):
        with pytest.raises(GatherError, match="slug"):
            mod.fetch_jobs("  ", client=StubClient([]))
