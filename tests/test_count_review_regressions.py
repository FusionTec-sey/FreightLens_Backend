"""Focused source-level regressions; database/concurrency acceptance remains separate."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from Services import count_session_service as sessions
from Services import count_discrepancy_service as reviews
from Services.inventory_posting_service import PostingConflict


@pytest.mark.parametrize('home,allowed,accepted', [(1, [2], True), (2, [1], True), (2, [2], False)])
def test_assignment_and_recount_counter_membership(home, allowed, accepted):
    db = MagicMock()
    user = SimpleNamespace(id=10, org_id=home, allowed_org_ids=allowed)
    db.query.return_value.filter.return_value.one_or_none.return_value = user
    context = SimpleNamespace(org_id=1, allowed_org_ids=[1])
    if accepted:
        assert sessions.eligible_counter(db, context, 10) is user
    else:
        with pytest.raises(PermissionError): sessions.eligible_counter(db, context, 10)


def test_exact_review_replay_does_not_append_again(monkeypatch):
    db = MagicMock(); key = uuid4()
    previous = SimpleNamespace(case_key=key, outcome='ACCEPTED', reason='Checked', created_by=12)
    monkeypatch.setattr(reviews, 'locked_discrepancy', lambda *args: (SimpleNamespace(id=4), SimpleNamespace(round=1)))
    monkeypatch.setattr(reviews, 'load_discrepancy_binding', lambda *args: 'same-binding')
    owned = MagicMock(); owned.filter_by.return_value.one_or_none.return_value = previous
    monkeypatch.setattr(reviews, 'owned', lambda *args: owned)
    outcome = SimpleNamespace(replayed=True)
    review = MagicMock(return_value=outcome)
    monkeypatch.setattr(reviews, 'review_case', review)
    payload = SimpleNamespace(case_key=key, outcome='ACCEPTED', reason='Checked', expected_version=1)
    authorize = MagicMock()
    assert reviews.decide_discrepancy(db, object(), 12, uuid4(), 4, payload, authorize=authorize) is outcome
    authorize.assert_called_once_with(db)
    db.add.assert_not_called()
    payload.outcome = 'RECOUNT_REQUIRED'
    with pytest.raises(PostingConflict):
        reviews.decide_discrepancy(db, object(), 12, uuid4(), 4, payload, authorize=authorize)
    assert review.call_count == 1
