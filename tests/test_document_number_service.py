"""Formatting and resets for document numbers.

The defect these pin: numbering used to count existing rows, so deleting a
document handed its number to the next one. The allocator is exercised against
the database elsewhere; these cover the pure logic, where an off-by-one in a
reset would silently reissue numbers for a whole period.
"""
from datetime import date
from types import SimpleNamespace

from Services.document_number_service import (
    RESET_POLICIES,
    _needs_reset,
    _period_start,
    format_number,
)


def series(**kwargs):
    base = dict(id=1, prefix="PO-", suffix="", padding=4, next_number=1,
                reset_policy="never", date_token=None, last_reset_on=None)
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── formatting ────────────────────────────────────────────────────────────────

def test_pads_the_counter_to_the_configured_width():
    assert format_number(series(), 7) == "PO-0007"


def test_padding_of_zero_leaves_the_number_as_it_is():
    assert format_number(series(padding=0), 26157) == "PO-26157"


def test_a_number_wider_than_its_padding_is_not_truncated():
    assert format_number(series(padding=3), 26157) == "PO-26157"


def test_reproduces_the_noblecon_format():
    got = format_number(series(prefix="NCE-PO#", padding=5), 26157)
    assert got == "NCE-PO#26157"


def test_reproduces_the_sahajanand_format_including_its_separator():
    """SAHAJ#260109-1: the separator rides in the date token, not its own field."""
    got = format_number(
        series(prefix="SAHAJ#", date_token="%y%m%d-", padding=1, reset_policy="daily"),
        1,
        today=date(2026, 1, 9),
    )
    assert got == "SAHAJ#260109-1"


def test_a_postfix_lands_after_the_counter():
    assert format_number(series(suffix="/SEY"), 12) == "PO-0012/SEY"


def test_an_unusable_date_token_is_dropped_rather_than_failing():
    """A bad token must not stop a document being created."""
    got = format_number(series(date_token="%Q"), 5)
    assert got == "PO-0005"


# ── resets ────────────────────────────────────────────────────────────────────

def test_never_resetting_series_has_no_period():
    assert _period_start("never", date(2026, 10, 12)) is None


def test_daily_period_starts_today():
    assert _period_start("daily", date(2026, 10, 12)) == date(2026, 10, 12)


def test_monthly_period_starts_on_the_first():
    assert _period_start("monthly", date(2026, 10, 12)) == date(2026, 10, 1)


def test_yearly_period_starts_in_january():
    assert _period_start("yearly", date(2026, 10, 12)) == date(2026, 1, 1)


def test_a_never_resetting_series_is_never_due():
    assert _needs_reset(series(reset_policy="never"), date(2027, 1, 1)) is False


def test_a_series_never_reset_is_due_once_a_policy_is_set():
    assert _needs_reset(series(reset_policy="yearly"), date(2026, 10, 12)) is True


def test_a_series_already_reset_this_period_is_not_due_again():
    row = series(reset_policy="yearly", last_reset_on=date(2026, 1, 1))
    assert _needs_reset(row, date(2026, 10, 12)) is False


def test_a_series_last_reset_in_the_previous_year_is_due():
    row = series(reset_policy="yearly", last_reset_on=date(2025, 1, 1))
    assert _needs_reset(row, date(2026, 10, 12)) is True


def test_a_daily_series_reset_yesterday_is_due_today():
    row = series(reset_policy="daily", last_reset_on=date(2026, 10, 11))
    assert _needs_reset(row, date(2026, 10, 12)) is True


def test_a_daily_series_reset_today_is_not_due_again():
    row = series(reset_policy="daily", last_reset_on=date(2026, 10, 12))
    assert _needs_reset(row, date(2026, 10, 12)) is False


def test_monthly_crosses_the_month_not_thirty_days():
    row = series(reset_policy="monthly", last_reset_on=date(2026, 9, 30))
    assert _needs_reset(row, date(2026, 10, 1)) is True


def test_every_offered_policy_is_understood():
    """A policy the UI offers but _period_start ignores would silently never reset."""
    for policy in RESET_POLICIES:
        if policy == "never":
            continue
        assert _period_start(policy, date(2026, 10, 12)) is not None
