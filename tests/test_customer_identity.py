from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Schema.CustomerSchema import CustomerIdentityInput
from Services.customer_identity_service import create_customer, get_customer
from Services.inventory_posting_service import PostingConflict
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Utils.org_filter import OrgContext
from tests.test_stock_ledger import stock  # noqa: F401


def profile(**changes):
    return CustomerIdentityInput(**(dict(name='Synthetic Customer', kind='PERSON',
        contacts=[dict(kind='PHONE', value='+248 2000000', primary=True)]) | changes))


@pytest.fixture
def customer(stock):
    f = stock; f.customer_key = uuid4()
    f.create_customer = lambda **kw: create_customer(kw.pop('factory', f.factory), f.context, f.actor,
        kw.pop('key', f.customer_key), kw.pop('profile', profile()), expected_version=kw.pop('expected_version', 0),
        authorize=kw.pop('authorize', lambda db: None), **kw)
    return f


@pytest.mark.parametrize('changes', [dict(name=' '), dict(kind='UNKNOWN'), dict(contacts=[]),
    dict(name='bad\nname'), dict(contacts=[dict(kind='PHONE', value='12345')]),
    dict(contacts=[dict(kind='PHONE', value='bad', primary=True)]),
    dict(contacts=[dict(kind='EMAIL', value='invalid', primary=True)]),
    dict(contacts=[dict(kind='EMAIL', value='a@b.test', primary=True)] * 2),
    dict(contacts=[dict(kind='PHONE', value='123456', primary=True)] * 17)])
def test_invalid_identity_rejected(changes):
    with pytest.raises(ValidationError): profile(**changes)


def test_identity_retry_and_scoped_read(customer):
    f = customer
    assert not f.create_customer().replayed
    assert f.create_customer().replayed
    with f.factory() as db:
        result = get_customer(db, f.context, f.customer_key, authorize=lambda db: None)
        assert result.name == 'Synthetic Customer' and result.version == 1
        receipt = db.query(PostingOperation).filter_by(org_id=f.orgs[0], operation_key=f.customer_key).one()
        assert 'Synthetic Customer' not in str(receipt.result)
    with pytest.raises(PostingConflict): f.create_customer(profile=profile(name='Changed'))


def test_contact_reuse_does_not_merge_distinct_customers(customer):
    f = customer
    one = f.create_customer(); two = f.create_customer(key=uuid4())
    assert one.result['customer_key'] != two.result['customer_key']


def test_permission_denial_and_foreign_root_lookup(customer):
    f = customer; f.create_customer()
    def deny(db): raise PermissionError('Synthetic denied')
    with pytest.raises(PermissionError): f.create_customer(authorize=deny)
    with f.factory() as db:
        with pytest.raises(PermissionError): get_customer(db, f.context, f.customer_key, authorize=deny)
        other = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
        with pytest.raises(LookupError): get_customer(db, other, f.customer_key, authorize=lambda db: None)


def test_outer_rollback_and_retry(customer):
    f = customer
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.create_customer(factory=db)
            raise RuntimeError('Synthetic rollback')
    with f.factory() as db:
        assert db.get(RetailCustomer, f.customer_key) is None
    assert not f.create_customer().replayed


def test_concurrent_same_creation_has_one_identity(customer):
    f = customer; barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        return f.create_customer().replayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == [False, True]


def test_creation_requires_expected_zero(customer):
    with pytest.raises(ValueError): customer.create_customer(expected_version=1)


def test_original_identity_cannot_be_rewritten(customer):
    f = customer; f.create_customer()
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text('UPDATE containermgmt.retail_customers SET is_deleted=true WHERE customer_key=:key'),
                   {'key': f.customer_key})


def test_migration_replay_keeps_customer(customer, monkeypatch):
    from Utils import migrate_20261003_retail_customers as migration
    f = customer; f.create_customer()
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_retail_customers_schema(); migration.ensure_retail_customers_schema()
    assert f.create_customer().replayed
