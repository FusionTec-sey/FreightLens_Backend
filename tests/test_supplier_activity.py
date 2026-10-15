"""The activity feed: a recorded change, said in a sentence.

The audit rows were being written long before anything read them, so the risk
here is not the writing but the reading: a feed that renders "updated /
default_payment_term_id / 3 / 7" answers nobody's question, and a feed that
shows a shared vendor's events to a company that cannot see them is a leak.
"""
from Routes.MasterData.MasterDataRouter import (
    ACTIVITY_FIELD_LABELS,
    ACTIVITY_FINANCIAL_PREFIXES,
    ACTIVITY_LABELS,
    _activity_sentence,
)


def test_a_changed_field_reads_as_a_sentence():
    assert _activity_sentence("updated", "name", "FOSHAN GENTLE (TEST)", "FOSHAN GENTLE") == (
        "Changed name from “FOSHAN GENTLE (TEST)” to “FOSHAN GENTLE”"
    )


def test_a_field_filled_for_the_first_time_was_not_changed_from_anything():
    assert _activity_sentence("updated", "phone", None, "+86 555 0101") == 'Set phone to “+86 555 0101”'


def test_a_cleared_field_still_says_what_it_held():
    """The old value is the only part worth keeping when a field is emptied."""
    assert _activity_sentence("updated", "phone", "+86 555 0101", None) == 'Cleared phone (was “+86 555 0101”)'


def test_the_column_name_is_never_what_the_reader_sees():
    assert "payment terms" in _activity_sentence("updated", "default_payment_term_id", "30 days", "60 days")
    assert "default_payment_term_id" not in _activity_sentence("updated", "default_payment_term_id", "30", "60")


def test_a_retirement_carries_its_reason():
    said = _activity_sentence("retired", "retire_reason", None, "no longer trading")
    assert said == "Retired — no longer trading"


def test_a_retirement_recorded_as_a_flag_does_not_read_as_a_reason():
    """The older rows wrote is_deleted true/false, which is not an explanation."""
    assert _activity_sentence("deleted", "is_deleted", "false", "true") == "Retired"


def test_a_merge_names_the_vendor_it_went_into():
    said = _activity_sentence("merged_away", "merge_reason", "VEND-0181", "VEND-0042 — same company, two imports")
    assert said == "Merged into another vendor: VEND-0042 — same company, two imports"


def test_an_action_nobody_has_labelled_yet_still_reads():
    """A new event must appear in the feed the day it is first recorded."""
    said = _activity_sentence("licence_expired", None, None, None)
    assert said == "Licence expired"
    assert "licence_expired" not in ACTIVITY_LABELS, "the point is that it is not listed"


def test_a_contact_event_says_who_it_was_and_what_for():
    """The role is recorded where a field edit records a column, and reads as a word."""
    assert _activity_sentence("contact_added", "ACCOUNTS", None, "Mr Wang") == "Contact added: Mr Wang (accounts)"
    assert _activity_sentence("address_added", "REGISTERED", None, "Suite 4") == "Address added: Suite 4 (registered office)"


def test_a_removal_does_not_read_the_row_id_back_to_anyone():
    """Removals record the row id in field_name; "Contact removed: 3 Mr Wang" is noise."""
    assert _activity_sentence("contact_removed", "3", "Mr Wang", None) == "Contact removed: Mr Wang"


def test_a_label_is_not_repeated_as_its_own_detail():
    assert _activity_sentence("identifier_verified", "7", None, "verified") == "Identifier verified"


def test_bank_events_are_the_ones_a_non_financial_user_must_not_read():
    # Bank accounts are not built. The prefix filter exists now so the feed
    # cannot start leaking them on the day they are.
    assert ACTIVITY_FINANCIAL_PREFIXES == ("bank", "payment_account")
    for action in ("bank_account_added", "bank_account_verified", "payment_account_changed"):
        assert any(action.startswith(p) for p in ACTIVITY_FINANCIAL_PREFIXES)
    for action in ("contact_added", "identifier_verified", "retired"):
        assert not any(action.startswith(p) for p in ACTIVITY_FINANCIAL_PREFIXES)


def test_every_audited_field_has_a_label():
    """A field recorded but not labelled would reach the screen as a column name."""
    from Routes.MasterData.MasterDataRouter import SUPPLIER_AUDITED_FIELDS

    unlabelled = [f for f in SUPPLIER_AUDITED_FIELDS if f not in ACTIVITY_FIELD_LABELS]
    assert unlabelled == [], f"no plain-language label for: {unlabelled}"
