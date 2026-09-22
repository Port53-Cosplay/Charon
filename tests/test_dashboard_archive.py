"""Tests for when a finished application drops out of the Applied view.

The rule differs by status on purpose: rejected and offered are events the
company caused, stranded is the absence of one.
"""

from datetime import datetime, timedelta, timezone

import pytest

from charon.dashboard import ARCHIVE_DAYS, _applications
from charon.db import add_application, get_connection


def _make_app(company, status, applied_days_ago, updated_days_ago):
    app_id = add_application(company=company, role="Analyst")
    now = datetime.now(timezone.utc)
    applied = (now - timedelta(days=applied_days_ago)).isoformat()
    updated = (now - timedelta(days=updated_days_ago)).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE applications SET status = ?, applied_at = ?, updated_at = ? WHERE id = ?",
            (status, applied, updated, app_id),
        )
        conn.commit()
    finally:
        conn.close()
    return app_id


def _visible_ids():
    apps, _ = _applications()
    return {a["id"] for a in apps}


class TestStrandedArchiving:
    def test_long_silent_application_archives_on_the_day_it_strands(self):
        """The sweep flipping a months-old row to stranded must not restart
        the clock — the silence began when she applied."""
        app_id = _make_app("Vanta", "ghosted", applied_days_ago=99, updated_days_ago=0)

        assert app_id not in _visible_ids()

    def test_recently_stranded_stays_visible(self):
        app_id = _make_app("Recent Co", "ghosted", applied_days_ago=25, updated_days_ago=0)

        assert app_id in _visible_ids()

    def test_stranded_archives_once_applied_at_passes_the_window(self):
        just_under = _make_app("Under", "ghosted",
                               applied_days_ago=ARCHIVE_DAYS - 1, updated_days_ago=0)
        just_over = _make_app("Over", "ghosted",
                              applied_days_ago=ARCHIVE_DAYS, updated_days_ago=0)

        visible = _visible_ids()
        assert just_under in visible
        assert just_over not in visible

    def test_archived_rows_are_counted_not_dropped(self):
        _make_app("Vanta", "ghosted", applied_days_ago=99, updated_days_ago=0)
        _, hidden = _applications()
        assert hidden == 1

    def test_include_archived_shows_them_again(self):
        app_id = _make_app("Vanta", "ghosted", applied_days_ago=99, updated_days_ago=0)
        apps, _ = _applications(include_archived=True)
        assert app_id in {a["id"] for a in apps}


class TestOtherTerminalStatuses:
    @pytest.mark.parametrize("status", ["rejected", "offered"])
    def test_still_measured_from_the_event(self, status):
        """A rejection recorded yesterday stays visible even if the
        application itself is ancient."""
        app_id = _make_app("Schellman", status,
                           applied_days_ago=200, updated_days_ago=1)

        assert app_id in _visible_ids()

    @pytest.mark.parametrize("status", ["rejected", "offered"])
    def test_archives_once_the_event_is_old(self, status):
        app_id = _make_app("Schellman", status,
                           applied_days_ago=200, updated_days_ago=ARCHIVE_DAYS + 1)

        assert app_id not in _visible_ids()

    def test_active_application_never_archives(self):
        app_id = _make_app("Still Waiting", "applied",
                           applied_days_ago=400, updated_days_ago=400)

        assert app_id in _visible_ids()

    def test_interviewing_never_archives(self):
        app_id = _make_app("In Process", "interviewing",
                           applied_days_ago=400, updated_days_ago=400)

        assert app_id in _visible_ids()
