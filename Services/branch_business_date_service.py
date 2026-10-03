"""T03 calculation contract; no calendar defaults or operational activation.

Future settings adapters load scoped/versioned rules and explicit date overrides.
A business date starts at that calendar date's configured local cutoff. Saturday
and Sunday use the weekend cutoff. Trading eligibility is separate from date
attribution; collection must apply its own permission/payment eligibility rules.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MissingBranchConfiguration(ValueError):
    pass


@dataclass(frozen=True)
class BranchTradingRules:
    timezone_name: str | None = None
    weekday_cutoff: time | None = None
    weekend_cutoff: time | None = None
    trading_weekdays: frozenset[int] | None = None  # Monday=0, Sunday=6

    def __post_init__(self):
        if self.timezone_name is not None:
            if not isinstance(self.timezone_name, str) or not self.timezone_name:
                raise ValueError("An explicit IANA timezone is required")
            try:
                ZoneInfo(self.timezone_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("Unknown branch timezone") from exc
        for cutoff in (self.weekday_cutoff, self.weekend_cutoff):
            if cutoff is not None and (type(cutoff) is not time or cutoff.tzinfo is not None
                                       or cutoff.second != 0 or cutoff.microsecond != 0):
                raise ValueError("Cutoffs must be local times with minute precision")
        if self.trading_weekdays is not None:
            if not isinstance(self.trading_weekdays, frozenset) or any(
                    type(day) is not int or not 0 <= day <= 6 for day in self.trading_weekdays):
                raise ValueError("Trading weekdays must be an immutable set of 0..6")


@dataclass(frozen=True)
class BranchBusinessDate:
    business_date: date
    trading_allowed: bool
    calendar_source: str


def resolve_business_date(instant: datetime, rules: BranchTradingRules, *,
                          date_overrides: Mapping[date, bool]) -> BranchBusinessDate:
    """Pure read-only calculation; never infer permissions from the calendar.

    Dates in overrides refer to BUSINESS dates. Explicit open overrides permit
    selected holidays; explicit closed overrides replace a normal trading day.
    An empty weekday set means intentionally closed, not missing configuration.
    Callers must pass a trusted instant, not a till's freely editable date.
    """
    if not isinstance(instant, datetime) or instant.utcoffset() is None:
        raise ValueError("A timezone-aware trusted instant is required")
    if not isinstance(rules, BranchTradingRules):
        raise ValueError("Explicit branch rules are required")
    if any(value is None for value in (rules.timezone_name, rules.weekday_cutoff,
                                       rules.weekend_cutoff, rules.trading_weekdays)):
        raise MissingBranchConfiguration("Branch timezone, both cutoffs and trading days must be configured")
    if any(type(day) is not date or type(is_open) is not bool for day, is_open in date_overrides.items()):
        raise ValueError("Calendar overrides require exact dates and explicit open/closed values")
    local = instant.astimezone(ZoneInfo(rules.timezone_name))
    cutoff = rules.weekend_cutoff if local.weekday() >= 5 else rules.weekday_cutoff
    business_day = local.date()
    if local.time() < cutoff:
        business_day -= timedelta(days=1)
    if business_day in date_overrides:
        return BranchBusinessDate(business_day, date_overrides[business_day], "DATE_OVERRIDE")
    return BranchBusinessDate(business_day, business_day.weekday() in rules.trading_weekdays, "WEEKLY")
