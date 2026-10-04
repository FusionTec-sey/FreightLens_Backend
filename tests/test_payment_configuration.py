"""Synthetic T12A configuration and exact fail-closed lookup."""
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Inventory.Location import InventoryBranch
from Schema.PaymentConfigurationSchema import (
    MethodConfig, MethodSave, MappingConfig, MappingSave)
from Services.inventory_posting_service import PostingConflict
from Services.payment_configuration_service import (
    list_methods, lookup_receiving_account, save_mapping, save_method)
from Utils.migrate_20261005_payment_methods import ensure_payment_methods_schema
from Utils.migrate_20261005_branch_receiving_accounts import ensure_branch_receiving_accounts_schema
from Utils.org_filter import OrgContext
from tests.test_stock_ledger import stock  # noqa: F401


def method_payload(*, operation=None, expected=0, enabled=True, label="Synthetic cash"):
    return MethodSave(operation_key=operation or uuid4(), expected_version=expected,
        code="SYNTH_CASH", config=MethodConfig(label=label, kind="CASH",
        is_enabled=enabled), reason="Synthetic setup")


def mapping_payload(f, method_key, *, operation=None, expected=0, enabled=True,
                    branch=None, account="SYNTH_LEDGER_A"):
    return MappingSave(operation_key=operation or uuid4(), expected_version=expected,
        branch_id=branch or f.branches[0], method_key=method_key,
        config=MappingConfig(account_ref=account, label="Synthetic receiving account",
        is_enabled=enabled), reason="Synthetic setup")


@pytest.fixture
def configured(stock):
    ensure_payment_methods_schema()
    ensure_branch_receiving_accounts_schema()
    # Replay-safe startup calls must not rewrite history.
    ensure_payment_methods_schema()
    ensure_branch_receiving_accounts_schema()
    stock.method_key = uuid4()
    stock.mapping_key = uuid4()
    stock.authorize = lambda db: None
    return stock


def write(f, action):
    with f.factory.begin() as db:
        return action(db)


def lookup(f, branch=None, method=None, context=None):
    with f.factory() as db:
        return lookup_receiving_account(db, context or f.context,
            branch or f.branches[0], method or f.method_key, authorize=f.authorize)


def test_exact_mapping_versions_replay_and_fail_closed(configured):
    f = configured
    assert write(f, lambda db: save_method(db, f.context, f.actor, f.method_key,
        method_payload(), authorize=f.authorize)).result["version"] == 1
    assert lookup(f)["reason"] == "MAPPING_MISSING"
    payload = mapping_payload(f, f.method_key)
    first = write(f, lambda db: save_mapping(db, f.context, f.actor, f.mapping_key,
        payload, authorize=f.authorize))
    assert first.result["version"] == 1
    assert write(f, lambda db: save_mapping(db, f.context, f.actor, f.mapping_key,
        payload, authorize=f.authorize)).replayed
    assert lookup(f)["account_ref"] == "SYNTH_LEDGER_A"
    with f.factory.begin() as db:
        other = InventoryBranch(org_id=f.orgs[0], code="SECOND", name="Second synthetic",
                                kind="STORE")
        db.add(other); db.flush(); other_id = other.id
    assert lookup(f, branch=other_id)["reason"] == "MAPPING_MISSING"
    with pytest.raises(LookupError):
        lookup(f, branch=f.branches[1])
    with pytest.raises(PostingConflict):
        write(f, lambda db: save_mapping(db, f.context, f.actor, f.mapping_key,
            mapping_payload(f, f.method_key, operation=payload.operation_key,
                            account="SYNTH_DIFFERENT"), authorize=f.authorize))
    second = write(f, lambda db: save_mapping(db, f.context, f.actor, f.mapping_key,
        mapping_payload(f, f.method_key, expected=1, enabled=False),
        authorize=f.authorize))
    assert second.result["version"] == 2
    assert lookup(f)["reason"] == "MAPPING_DISABLED"
    with pytest.raises(PostingConflict):
        write(f, lambda db: save_mapping(db, f.context, f.actor, f.mapping_key,
            mapping_payload(f, f.method_key, expected=1), authorize=f.authorize))


def test_tenant_permission_and_immutable_sql(configured):
    f = configured
    payload = method_payload()
    write(f, lambda db: save_method(db, f.context, f.actor, f.method_key,
        payload, authorize=f.authorize))
    foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=[f.orgs[1]], is_root=False)
    with f.factory() as db:
        assert list_methods(db, foreign, page=1, limit=10, authorize=f.authorize)["total"] == 0
        with pytest.raises(PermissionError):
            list_methods(db, f.context, page=1, limit=10,
                         authorize=lambda session: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(LookupError):
        lookup(f, context=foreign)
    with f.factory.begin() as db:
        with pytest.raises(DBAPIError):
            db.execute(text("""UPDATE containermgmt.payment_method_revisions
                SET label = 'Tampered' WHERE method_key = :key"""), {"key": f.method_key})
        db.rollback()


def test_disabled_method_and_concurrent_revision(configured):
    f = configured
    write(f, lambda db: save_method(db, f.context, f.actor, f.method_key,
        method_payload(), authorize=f.authorize))
    write(f, lambda db: save_mapping(db, f.context, f.actor, f.mapping_key,
        mapping_payload(f, f.method_key), authorize=f.authorize))
    barrier = Barrier(2)

    def change(label):
        payload = method_payload(expected=1, label=label)
        barrier.wait()
        try:
            return write(f, lambda db: save_method(db, f.context, f.actor,
                f.method_key, payload, authorize=f.authorize)).result["version"]
        except PostingConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, ("Synthetic one", "Synthetic two")))
    assert sorted(map(str, results)) == ["2", "CONFLICT"]
    write(f, lambda db: save_method(db, f.context, f.actor, f.method_key,
        method_payload(expected=2, enabled=False, label="Synthetic disabled"),
        authorize=f.authorize))
    assert lookup(f)["reason"] == "METHOD_DISABLED"
