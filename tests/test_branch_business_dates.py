from dataclasses import replace
from datetime import date, datetime, time, timezone

import pytest

from Services.branch_business_date_service import (
    BranchTradingRules, MissingBranchConfiguration, resolve_business_date,
)


def rules():
    # Synthetic settings, not proposed or seeded real operating thresholds.
    return BranchTradingRules("Indian/Mahe", time(4), time(6), frozenset(range(6)))


@pytest.mark.parametrize("instant,expected", [
    ("2026-10-02T23:59:00+04:00", "2026-10-02"),
    ("2026-10-03T05:59:00+04:00", "2026-10-02"),
    ("2026-10-03T06:00:00+04:00", "2026-10-03"),
    ("2026-10-05T03:59:00+04:00", "2026-10-04"),
    ("2026-10-05T04:00:00+04:00", "2026-10-05"),
])
def test_distinct_weekday_weekend_cutoffs_and_exact_boundary(instant, expected):
    actual = resolve_business_date(datetime.fromisoformat(instant), rules(), date_overrides={})
    assert actual.business_date == date.fromisoformat(expected)


def test_utc_instant_uses_branch_timezone_and_saturday_can_trade():
    actual = resolve_business_date(datetime(2026, 10, 3, 2, tzinfo=timezone.utc), rules(), date_overrides={})
    assert actual.business_date == date(2026, 10, 3)
    assert actual.trading_allowed


@pytest.mark.parametrize("weekday,opened", [(3, False), (4, True)])
def test_explicit_date_overrides_normal_weekly_calendar(weekday, opened):
    day = date(2026, 10, weekday)
    actual = resolve_business_date(datetime(2026, 10, weekday, 12, tzinfo=timezone.utc), rules(),
                                   date_overrides={day: opened})
    assert actual.trading_allowed is opened
    assert actual.calendar_source == "DATE_OVERRIDE"


@pytest.mark.parametrize("field", ["timezone_name", "weekday_cutoff", "weekend_cutoff", "trading_weekdays"])
def test_missing_settings_block_instead_of_guessing(field):
    with pytest.raises(MissingBranchConfiguration):
        resolve_business_date(datetime.now(timezone.utc), replace(rules(), **{field: None}), date_overrides={})


def test_closed_calendar_still_resolves_date_without_automatically_banning_collection():
    result = resolve_business_date(datetime(2026, 10, 4, 12, tzinfo=timezone.utc), rules(), date_overrides={})
    assert not result.trading_allowed and result.business_date == date(2026, 10, 4)


def test_empty_week_is_explicitly_closed_not_unconfigured():
    result = resolve_business_date(datetime.now(timezone.utc), replace(rules(), trading_weekdays=frozenset()),
                                   date_overrides={})
    assert not result.trading_allowed


@pytest.mark.parametrize("changes", [{"timezone_name": "not/a-zone"},
    {"weekday_cutoff": time(4, 0, 1)}, {"weekend_cutoff": time(4, tzinfo=timezone.utc)},
    {"trading_weekdays": frozenset({7})}, {"trading_weekdays": frozenset({True})}])
def test_invalid_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        replace(rules(), **changes)


def test_naive_date_and_ambiguous_override_rejected():
    with pytest.raises(ValueError):
        resolve_business_date(datetime(2026, 10, 2), rules(), date_overrides={})
    with pytest.raises(ValueError):
        resolve_business_date(datetime.now(timezone.utc), rules(), date_overrides={date(2026, 10, 2): "open"})
