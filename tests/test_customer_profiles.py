from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.Credentials.users import User
from Model.containermgmt.Inventory.ManagerCase import (
    ManagerCase, ManagerCaseDecision, ManagerCaseUse)
from Model.containermgmt.MasterData.CustomerProfileRevision import CustomerProfileRevision
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Schema.CustomerDuplicateSchema import CustomerDuplicateRequest
from Schema.CustomerSchema import CustomerIdentityInput, CustomerProfileUpdate
from Services.customer_duplicate_service import request_duplicate_review, review_duplicate
from Services.customer_identity_service import create_customer
from Services.customer_profile_service import (
    customer_profile_history, historical_names_for_page, read_customer_profile,
    update_customer_profile)
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext
from tests.test_customer_identity import customer, profile  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


def revised(name='Revised Customer'):
    return CustomerIdentityInput(name=name, kind='BUSINESS', contacts=[
        dict(kind='EMAIL', value='accounts@example.test', label='Accounts', primary=True),
        dict(kind='PHONE', value='+248 2000000', label='Store', primary=False)])


def update(f, *, operation=None, expected=1, current=None, authorize=lambda db: None):
    payload = CustomerProfileUpdate(operation_key=operation or uuid4(),
        expected_version=expected, profile=current or revised(),
        reason='Synthetic verified profile correction')
    return update_customer_profile(f.factory, f.context, f.actor,
        f.customer_key, payload, authorize=authorize), payload


def test_profile_update_is_append_only_exact_and_replayable(customer):
    f = customer; f.create_customer(); operation = uuid4()
    result, payload = update(f, operation=operation)
    assert result.result == {'customer_key': str(f.customer_key), 'version': 2}
    assert update(f, operation=operation)[0].replayed
    with f.factory() as db:
        current = read_customer_profile(db, f.context, f.customer_key,
            authorize=lambda session: None)
        original = read_customer_profile(db, f.context, f.customer_key,
            version=1, authorize=lambda session: None)
        assert current.version == 2 and current.name == 'Revised Customer'
        assert original.name == 'Synthetic Customer'
        row = db.query(CustomerProfileRevision).filter_by(
            org_id=f.orgs[0], customer_key=f.customer_key).one()
        assert row.reason == payload.reason


def test_profile_history_pages_original_and_exact_revisions(customer):
    f = customer; f.create_customer(); update(f)
    current = revised('Third Profile')
    update(f, expected=2, current=current)
    with f.factory.begin() as db:
        first = customer_profile_history(db, f.context, f.customer_key,
            authorize=lambda session: None, page=1, limit=2)
        second = customer_profile_history(db, f.context, f.customer_key,
            authorize=lambda session: None, page=2, limit=2)
        assert [item.version for item in first['items']] == [3, 2]
        assert [item.version for item in second['items']] == [1]
        names = historical_names_for_page(db, f.context,
            [(f.customer_key, 1), (f.customer_key, 2), (f.customer_key, 3)],
            authorize=lambda session: None)
        assert names == {(f.customer_key, 1): 'Synthetic Customer',
            (f.customer_key, 2): 'Revised Customer',
            (f.customer_key, 3): 'Third Profile'}


def test_profile_stale_noop_permission_and_foreign_scope_fail_closed(customer):
    f = customer; f.create_customer(); update(f)
    with pytest.raises(PostingConflict): update(f, expected=1)
    with pytest.raises(ValueError, match='no changes'):
        update(f, expected=2, current=revised())
    def denied(db): raise PermissionError('Personal data denied')
    with pytest.raises(PermissionError, match='denied'): update(f, expected=2, authorize=denied)
    foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    payload = CustomerProfileUpdate(operation_key=uuid4(), expected_version=2,
        profile=revised('Foreign attempt'), reason='Denied')
    with pytest.raises(LookupError):
        update_customer_profile(f.factory, foreign, f.actor, f.customer_key,
            payload, authorize=lambda session: None)


def test_concurrent_profile_updates_create_one_next_version(customer):
    f = customer; f.create_customer(); barrier = Barrier(2, timeout=10)
    def run(index):
        barrier.wait()
        try:
            return update(f, current=revised(f'Concurrent {index}'))[0]
        except PostingConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (1, 2)))
    assert sum(result is not None for result in results) == 1
    with f.factory() as db:
        assert db.query(CustomerProfileRevision).filter_by(
            org_id=f.orgs[0], customer_key=f.customer_key).count() == 1


def test_profile_history_and_original_identity_are_immutable(customer):
    f = customer; f.create_customer(); update(f)
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text('UPDATE containermgmt.customer_profile_revisions '
            'SET reason=:reason WHERE customer_key=:key'),
            {'reason': 'Changed', 'key': f.customer_key})


@pytest.fixture
def duplicate_pair(customer):
    f = customer; f.create_customer(); f.other_key = uuid4()
    create_customer(f.factory, f.context, f.actor, f.other_key,
        profile(name='Synthetic Other'), expected_version=0,
        authorize=lambda db: None)
    with f.factory.begin() as db:
        reviewer = User(org_id=f.orgs[0], username='review-' + uuid4().hex,
            password_hash='unusable-test-only')
        db.add(reviewer); db.flush(); f.reviewer = reviewer.id
    f.case_key = uuid4()
    f.duplicate_payload = CustomerDuplicateRequest(operation_key=f.case_key,
        customer_key=f.customer_key, other_customer_key=f.other_key,
        expected_customer_version=1, expected_other_version=1,
        assessment='SAME_CUSTOMER', reason='Synthetic possible duplicate')
    return f


def request_duplicate(f):
    with f.factory.begin() as db:
        return request_duplicate_review(db, f.context, f.actor,
            f.duplicate_payload, authorize=lambda session: None)


def test_duplicate_review_records_assessment_but_never_merges(duplicate_pair):
    f = duplicate_pair; assert not request_duplicate(f).replayed
    with f.factory.begin() as db:
        with pytest.raises(PermissionError):
            review_duplicate(db, f.context, f.actor, uuid4(),
                case_key=f.case_key, expected_version=1, outcome='APPROVED',
                reason='Self review', authorize=lambda session: None)
    with f.factory.begin() as db:
        result = review_duplicate(db, f.context, f.reviewer, uuid4(),
            case_key=f.case_key, expected_version=1, outcome='APPROVED',
            reason='Profiles reviewed', authorize=lambda session: None)
        assert result.result['status'] == 'APPROVED'
    with f.factory() as db:
        case = db.query(ManagerCase).filter_by(
            org_id=f.orgs[0], case_key=f.case_key).one()
        assert case.binding['details']['merge_authorized'] is False
        assert db.query(ManagerCaseDecision).filter_by(
            org_id=f.orgs[0], case_id=case.id).count() == 1
        assert db.query(ManagerCaseUse).filter_by(
            org_id=f.orgs[0], case_id=case.id).count() == 0
        assert db.query(RetailCustomer).filter_by(org_id=f.orgs[0]).count() == 2


def test_duplicate_review_is_invalidated_by_either_profile_change(duplicate_pair):
    f = duplicate_pair; request_duplicate(f)
    update(f)
    with f.factory.begin() as db, pytest.raises(PostingConflict):
        review_duplicate(db, f.context, f.reviewer, uuid4(),
            case_key=f.case_key, expected_version=1, outcome='APPROVED',
            reason='Stale review', authorize=lambda session: None)


def test_duplicate_pair_order_replays_one_case_and_foreign_scope_is_denied(duplicate_pair):
    f = duplicate_pair; request_duplicate(f)
    assert request_duplicate(f).replayed
    reversed_payload = f.duplicate_payload.model_copy(update={
        'operation_key': uuid4(), 'customer_key': f.other_key,
        'other_customer_key': f.customer_key})
    with f.factory.begin() as db:
        request_duplicate_review(db, f.context, f.actor, reversed_payload,
            authorize=lambda session: None)
    foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    with f.factory.begin() as db, pytest.raises(LookupError):
        request_duplicate_review(db, foreign, f.actor,
            f.duplicate_payload.model_copy(update={'operation_key': uuid4()}),
            authorize=lambda session: None)


def test_profile_migration_replays_without_rewriting_history(customer, monkeypatch):
    from Utils import migrate_20261004_customer_profiles as migration
    f = customer; f.create_customer(); update(f)
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_customer_profiles_schema()
    migration.ensure_customer_profiles_schema()
    with f.factory() as db:
        assert read_customer_profile(db, f.context, f.customer_key,
            authorize=lambda session: None).version == 2
