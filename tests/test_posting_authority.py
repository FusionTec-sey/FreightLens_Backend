"""Durable local authority only; all identities belong to synthetic test tenants."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Inventory.PostingAuthority import StoreNode, BranchAuthorityEpoch
from Services.posting_authority_service import AuthorityClaim, require_posting_authority
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def authority(stock):
    f = stock
    f.guard = lambda db: require_posting_authority(db, f.context, f.claim, branch_id=f.branches[0])
    return f


def append_epoch(f, epoch, state="SUSPENDED"):
    with f.factory.begin() as db:
        db.add(BranchAuthorityEpoch(org_id=f.orgs[0], branch_id=f.branches[0], node_id=f.node_id,
            epoch=epoch, state=state, reason="Synthetic transition", created_by=f.actor))


def test_authority_is_persisted_and_rechecked_before_replay(authority):
    f = authority
    key = uuid4()
    f.open(key, authorize=f.guard)
    assert f.open(key, authorize=f.guard).replayed
    append_epoch(f, 2)
    with pytest.raises(PermissionError, match="suspended or stale"):
        f.open(key, authorize=f.guard)


@pytest.mark.parametrize("invalid", ["tenant", "branch", "node", "epoch"])
def test_claim_must_match_exact_owner_even_with_root_context(authority, invalid):
    f = authority
    values = dict(org_id=f.orgs[0], branch_id=f.branches[0], node_key=f.node_key, epoch=1)
    changes = {"tenant": ("org_id", f.orgs[1]), "branch": ("branch_id", f.branches[1]),
               "node": ("node_key", uuid4()), "epoch": ("epoch", 2)}
    field, value = changes[invalid]
    values[field] = value
    with f.factory.begin() as db:
        with pytest.raises(PermissionError):
            require_posting_authority(db, f.context, AuthorityClaim(**values), branch_id=f.branches[0])


def test_missing_authority_fails_closed(stock):
    f = stock
    from Model.containermgmt.Inventory.Location import InventoryBranch
    with f.factory.begin() as db:
        branch = InventoryBranch(org_id=f.orgs[0], code="UNCONFIGURED", name="Synthetic", kind="STORE")
        db.add(branch); db.flush()
        branch_id = branch.id
    with f.factory.begin() as db:
        with pytest.raises(PermissionError):
            require_posting_authority(db, f.context,
                AuthorityClaim(f.orgs[0], branch_id, uuid4(), 1), branch_id=branch_id)


@pytest.mark.parametrize("epoch", [1, 3, 0])
def test_duplicate_skipped_and_zero_epochs_rejected(authority, epoch):
    with pytest.raises(DBAPIError):
        append_epoch(authority, epoch)


@pytest.mark.parametrize("table", ["inventory_store_nodes", "inventory_branch_authority_epochs"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE"])
def test_authority_history_cannot_be_changed(authority, table, verb):
    f = authority
    sql = f"UPDATE containermgmt.{table} SET is_deleted = true WHERE org_id = :org" if verb == "UPDATE" else (
        f"DELETE FROM containermgmt.{table} WHERE org_id = :org")
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            db.execute(text(sql), {"org": f.orgs[0]})


def test_foreign_node_cannot_own_branch(authority):
    f = authority
    with f.factory.begin() as db:
        node = StoreNode(org_id=f.orgs[1], node_key=uuid4(), created_by=f.actor)
        db.add(node); db.flush()
        foreign_id = node.id
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            db.add(BranchAuthorityEpoch(org_id=f.orgs[0], branch_id=f.branches[0],
                node_id=foreign_id, epoch=2, state="ACTIVE", reason="Synthetic invalid scope", created_by=f.actor))


def test_competing_epoch_changes_have_one_winner(authority):
    f = authority
    barrier = Barrier(2, timeout=10)
    def change(_):
        barrier.wait()
        try:
            append_epoch(f, 2)
            return "posted"
        except DBAPIError:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(change, range(2))) == ["posted", "rejected"]


def test_guard_holds_branch_lock_until_posting_transaction_finishes(authority):
    f = authority
    with f.factory.begin() as posting_db:
        f.guard(posting_db)
        # A separate connection cannot promote an epoch under an in-flight writer.
        with pytest.raises(DBAPIError):
            with f.factory.begin() as change_db:
                change_db.execute(text("SET LOCAL lock_timeout = '100ms'"))
                change_db.add(BranchAuthorityEpoch(org_id=f.orgs[0], branch_id=f.branches[0],
                    node_id=f.node_id, epoch=2, state="SUSPENDED", reason="Synthetic suspension", created_by=f.actor))
    append_epoch(f, 2)


def test_migration_replay_keeps_authority_history(authority, test_engine, monkeypatch):
    import Utils.migrate_20261002_posting_authority as migration
    f = authority
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_posting_authority_schema()
    migration.ensure_posting_authority_schema()
    with f.factory.begin() as db:
        f.guard(db)
        assert db.query(BranchAuthorityEpoch).filter_by(org_id=f.orgs[0]).count() == 1
