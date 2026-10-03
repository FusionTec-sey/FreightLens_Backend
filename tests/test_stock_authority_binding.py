"""Authority is mandatory and bound to stock scope and durable retry intent."""
from dataclasses import replace
from uuid import uuid4

import pytest

from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.PostingAuthority import BranchAuthorityEpoch
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Services.inventory_posting_service import PostingConflict, PostingEffect, execute_once
from tests.test_stock_ledger import stock  # noqa: F401
from tests.test_stock_batches import opening as batch_opening
from tests.test_stock_serials import opening as serial_opening


@pytest.mark.parametrize("missing", ["authority", "authorize"])
@pytest.mark.parametrize("shared", [False, True])
def test_no_missing_authority_or_permission_callback_path(stock, missing, shared):
    f = stock
    factory = f.factory
    with factory() as db:
        if shared:
            db.begin()
            f.factory = db
        try:
            with pytest.raises(ValueError):
                f.open(**{missing: None})
        finally:
            f.factory = factory
        if shared:
            assert not db.in_transaction()
    with factory() as db:
        assert db.query(PostingOperation).filter_by(org_id=f.orgs[0]).count() == 0
        assert db.query(StockBalance).filter_by(org_id=f.orgs[0]).count() == 0


@pytest.mark.parametrize("opener", [lambda f, **kw: f.open(**kw), batch_opening, serial_opening])
def test_all_opening_types_check_claim_even_if_callback_allows(stock, opener):
    f = stock
    with pytest.raises(PermissionError):
        opener(f, authority=replace(f.claim, node_key=uuid4()), authorize=lambda db: None)


@pytest.mark.parametrize("action", ["reserve", "release"])
def test_authority_for_other_same_company_branch_cannot_touch_balance(stock, action):
    f = stock
    balance = f.open().result["balance_id"]
    hold, source = uuid4(), uuid4()
    if action == "release":
        f.reserve(balance, reservation_key=hold, source_line_key=source)
    with f.factory.begin() as db:
        branch = InventoryBranch(org_id=f.orgs[0], code="OTHER", name="Synthetic other", kind="STORE")
        db.add(branch); db.flush()
        other_claim = replace(f.claim, branch_id=branch.id)
        db.add(BranchAuthorityEpoch(org_id=f.orgs[0], branch_id=branch.id, node_id=f.node_id,
            epoch=1, state="ACTIVE", reason="Synthetic other branch", created_by=f.actor))
    with pytest.raises(PermissionError, match="scope"):
        if action == "reserve":
            f.reserve(balance, authority=other_claim)
        else:
            f.release(balance, hold, source, authority=other_claim)


@pytest.mark.parametrize("action", ["opening", "reserve", "release"])
def test_old_epoch_cannot_replay_and_new_epoch_cannot_relabel_intent(stock, action):
    f = stock
    key, hold, source = uuid4(), uuid4(), uuid4()
    balance = None if action == "opening" else f.open().result["balance_id"]
    if action == "release":
        f.reserve(balance, reservation_key=hold, source_line_key=source)
    def run(claim):
        if action == "opening":
            return f.open(key, authority=claim)
        if action == "reserve":
            return f.reserve(balance, key, reservation_key=hold, source_line_key=source, authority=claim)
        return f.release(balance, hold, source, key, authority=claim)
    run(f.claim)
    assert run(f.claim).replayed
    with f.factory.begin() as db:
        db.add(BranchAuthorityEpoch(org_id=f.orgs[0], branch_id=f.branches[0], node_id=f.node_id,
            epoch=2, state="ACTIVE", reason="Synthetic next epoch", created_by=f.actor))
    with pytest.raises(PermissionError, match="stale"):
        run(f.claim)
    with pytest.raises(PostingConflict):
        run(replace(f.claim, epoch=2))


def test_revoked_action_permission_blocks_stock_replay(stock):
    f = stock
    key = uuid4()
    f.open(key)
    def denied(db):
        raise PermissionError("Synthetic action permission revoked")
    with pytest.raises(PermissionError, match="revoked"):
        f.open(key, authorize=denied)


def test_legacy_receipt_cannot_be_reinterpreted_as_authorized_stock(stock):
    f = stock
    key = uuid4()
    execute_once(f.factory, f.context, f.actor, key, "stock.opening.v2", {},
                 lambda db: PostingEffect({"historical": True}, {}))
    with pytest.raises(PostingConflict):
        f.open(key)
    with f.factory() as db:
        assert db.query(StockBalance).filter_by(org_id=f.orgs[0]).count() == 0


def test_inactive_location_cannot_return_saved_stock_result(stock):
    f = stock
    key = uuid4()
    f.open(key)
    with f.factory.begin() as db:
        db.get(StockLocation, f.locations[0]).is_active = False
    with pytest.raises(ValueError, match="scope"):
        f.open(key)
