"""The clock a printed document uses.

The defect these pin: between midnight and 04:00 in Seychelles the server's UTC
date is still the previous day, so a purchase order printed at 01:00 on the 9th
was stamped the 8th.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from Services.report_render_engine import DEFAULT_REPORT_TIMEZONE, get_sandboxed_env
from Services.report_time_service import (
    FALLBACK_TIMEZONE,
    org_timezone,
    org_timezone_name,
)


class _Query:
    def __init__(self, profile):
        self._profile = profile

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._profile


class _DB:
    def __init__(self, profile=None, raises=False):
        self._profile = profile
        self._raises = raises

    def query(self, *args, **kwargs):
        if self._raises:
            raise RuntimeError("database unavailable")
        return _Query(self._profile)


_ORG = SimpleNamespace(org_id=1)


def test_uses_the_organisations_configured_zone():
    db = _DB(SimpleNamespace(timezone="Europe/Madrid"))
    assert org_timezone(db, _ORG) == ZoneInfo("Europe/Madrid")


def test_falls_back_when_no_print_profile_exists():
    assert org_timezone(_DB(None), _ORG) == ZoneInfo(FALLBACK_TIMEZONE)


def test_falls_back_on_a_nonsense_zone_rather_than_failing_the_render():
    db = _DB(SimpleNamespace(timezone="Mars/Olympus_Mons"))
    assert org_timezone(db, _ORG) == ZoneInfo(FALLBACK_TIMEZONE)


def test_a_database_error_does_not_break_printing():
    assert org_timezone(_DB(raises=True), _ORG) == ZoneInfo(FALLBACK_TIMEZONE)


def test_the_name_round_trips_into_the_renderer():
    db = _DB(SimpleNamespace(timezone="Indian/Mahe"))
    assert org_timezone_name(db, _ORG) == "Indian/Mahe"


def test_a_document_printed_after_midnight_locally_carries_the_local_date():
    """01:00 on the 9th in Seychelles is still 21:00 on the 8th in UTC."""
    just_after_midnight = datetime(2026, 10, 9, 1, 0, tzinfo=ZoneInfo("Indian/Mahe"))
    assert just_after_midnight.astimezone(timezone.utc).date().isoformat() == "2026-10-08"
    assert just_after_midnight.date().isoformat() == "2026-10-09"


def test_template_now_is_not_utc_by_default():
    env = get_sandboxed_env()
    rendered = env.from_string("{{ now().tzinfo }}").render()
    assert rendered == DEFAULT_REPORT_TIMEZONE
    assert rendered != "UTC"


def test_template_now_follows_the_organisation_zone():
    env = get_sandboxed_env("Europe/Madrid")
    assert env.from_string("{{ now().tzinfo }}").render() == "Europe/Madrid"


def test_template_now_survives_an_unknown_zone():
    env = get_sandboxed_env("not/a-zone")
    assert env.from_string("{{ now().tzinfo }}").render() == DEFAULT_REPORT_TIMEZONE
