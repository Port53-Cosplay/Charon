"""Tests for the SAP SuccessFactors adapter."""

from pathlib import Path

import httpx
import pytest

from charon.gather import GatherError, gather_employer
from charon.gather import successfactors as sf


FIXTURES = Path(__file__).parent / "fixtures"

EASTMAN_ENTRY = {
    "slug": "eastman",
    "name": "Eastman Chemical",
    "tier": "tier_1",
    "category": "enterprise_it",
    "successfactors": {"host": "jobs.eastman.com"},
}


def _paged_client() -> httpx.Client:
    """Serve fixture pages by startrow; clamp past-the-end to the last page.

    Mirrors real SuccessFactors behavior: an out-of-range startrow doesn't go
    empty, it hands back the final page again. The adapter must still terminate.
    """
    page1 = (FIXTURES / "successfactors_page1.html").read_text(encoding="utf-8")
    page2 = (FIXTURES / "successfactors_page2.html").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        startrow = int(request.url.params.get("startrow", "0"))
        body = page1 if startrow == 0 else page2  # startrow >= 25 clamps to last
        return httpx.Response(200, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestResolveHost:
    def test_reads_block(self):
        host, q, locale = sf._resolve_host(EASTMAN_ENTRY)
        assert host == "jobs.eastman.com"
        assert q == ""
        assert locale == "en_US"

    def test_strips_scheme_and_slash(self):
        host, _, _ = sf._resolve_host({"slug": "x", "successfactors": {"host": "https://jobs.x.com/"}})
        assert host == "jobs.x.com"

    def test_missing_entry_raises(self):
        with pytest.raises(GatherError, match="registry entry"):
            sf._resolve_host(None)

    def test_missing_block_raises(self):
        with pytest.raises(GatherError, match="successfactors"):
            sf._resolve_host({"slug": "x", "name": "X"})

    def test_missing_host_raises(self):
        with pytest.raises(GatherError, match="host"):
            sf._resolve_host({"slug": "x", "successfactors": {}})


class TestFetchJobs:
    def test_paginates_and_normalizes(self, monkeypatch):
        # Real page size is 25; the fixtures carry 2 + 1 rows across two pages,
        # so shrink PAGE_SIZE to 2 to make the loop actually turn the page.
        monkeypatch.setattr(sf, "PAGE_SIZE", 2)
        jobs = sf.fetch_jobs(
            "eastman", entry=EASTMAN_ENTRY, client=_paged_client(), page_delay=0
        )
        assert len(jobs) == 3
        titles = [j["role"] for j in jobs]
        assert titles == ["Security Analyst", "Process Operator", "GRC Specialist"]

        first = jobs[0]
        assert first["company"] == "Eastman Chemical"
        assert first["url"] == "https://jobs.eastman.com/job/Kingsport-Security-Analyst-TN-37660/1000000001/"
        assert first["location"] == "Kingsport, TN, US, 37660"
        assert first["posted_at"] == "Jul 22, 2026"
        assert first["description"] == ""

    def test_clamp_backstop_terminates(self, monkeypatch):
        # A results page with NO pagination label (total unknown) that returns
        # the same rows for every startrow — models SuccessFactors clamping a
        # past-the-end request to the last page. The adapter must stop once a
        # page surfaces no new URLs, not loop forever.
        no_label = """<html><body><table><tbody>
          <tr class="data-row">
            <td class="colTitle"><span class="jobTitle hidden-phone">
              <a href="/job/A/1/" class="jobTitle-link">Role A</a></span></td>
            <td class="colLocation hidden-phone"><span class="jobLocation">Kingsport, TN</span></td>
          </tr>
          <tr class="data-row">
            <td class="colTitle"><span class="jobTitle hidden-phone">
              <a href="/job/B/2/" class="jobTitle-link">Role B</a></span></td>
            <td class="colLocation hidden-phone"><span class="jobLocation">Kingsport, TN</span></td>
          </tr>
        </tbody></table></body></html>"""
        monkeypatch.setattr(sf, "PAGE_SIZE", 2)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=no_label)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        jobs = sf.fetch_jobs("eastman", entry=EASTMAN_ENTRY, client=client, page_delay=0)
        assert len(jobs) == 2
        assert len({j["url"] for j in jobs}) == 2

    def test_empty_slug_raises(self):
        with pytest.raises(GatherError, match="slug cannot be empty"):
            sf.fetch_jobs("", entry=EASTMAN_ENTRY)

    def test_http_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="down")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(GatherError, match="HTTP 503"):
            sf.fetch_jobs("eastman", entry=EASTMAN_ENTRY, client=client, page_delay=0)


class TestGatherEmployerIntegration:
    def test_registered_and_dispatches(self, monkeypatch):
        # Prove the orchestrator can load 'successfactors' from ADAPTERS and
        # route to it, without touching the network.
        canned = [
            {
                "company": "Eastman Chemical",
                "role": "Security Analyst",
                "url": "https://jobs.eastman.com/job/x/1/",
                "location": "Kingsport, TN, US",
                "description": "",
                "posted_at": "Jul 22, 2026",
            }
        ]
        monkeypatch.setattr(sf, "fetch_jobs", lambda slug, entry=None: canned)

        summary = gather_employer("successfactors", EASTMAN_ENTRY, dry_run=True)
        assert summary["error"] is None
        assert summary["fetched"] == 1
        assert summary["ats"] == "successfactors"
