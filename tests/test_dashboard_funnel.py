"""Tests for the Pulse funnel stages in /api/stats."""

from charon import dashboard
from charon.db import add_application, update_application_status


def _funnel():
    return {s["key"]: s for s in dashboard._stats(include_charts=True)["funnel"]}


class TestFunnelStranded:
    def test_stranded_sits_between_applied_and_engaged(self):
        keys = [s["key"] for s in dashboard._stats(include_charts=True)["funnel"]]
        assert keys.index("applied") < keys.index("stranded") < keys.index("engaged")

    def test_stranded_and_engaged_are_shares_of_applied(self):
        for status in ("ghosted", "ghosted", "rejected", "applied"):
            app_id = add_application(company="Acme", role="Analyst")
            update_application_status(app_id, status)
        f = _funnel()
        assert f["applied"]["count"] == 4
        assert f["stranded"]["count"] == 2
        assert f["engaged"]["count"] == 1
        assert f["stranded"]["of"] == "applied"
        assert f["engaged"]["of"] == "applied"
        assert "of" not in f["offered"]
