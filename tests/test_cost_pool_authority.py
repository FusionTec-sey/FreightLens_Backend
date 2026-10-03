from uuid import uuid4
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.PostingAuthority import CostPoolAuthorityEpoch, StoreNode
from Services.posting_authority_service import CostPoolAuthorityClaim, require_cost_pool_authority
from tests.test_charge_posting import posting  # noqa: F401
from tests.test_cost_content_reviews import content_review  # noqa: F401
from tests.test_cost_charge_reviews import charge_review, charge, allocation, valued, stock  # noqa: F401


def append(f, epoch, state='SUSPENDED', node_id=None):
    with f.factory.begin() as db:
        db.add(CostPoolAuthorityEpoch(org_id=f.orgs[0], cost_pool_id=f.pool,
            node_id=f.node_id if node_id is None else node_id, epoch=epoch, state=state,
            reason='Synthetic central authority', created_by=f.actor))


@pytest.fixture
def central(posting):
    f = posting
    f.central_claim = CostPoolAuthorityClaim(f.orgs[0], f.pool, f.node_key, 1)
    f.central_guard = lambda db: require_cost_pool_authority(db, f.context, f.central_claim, cost_pool_id=f.pool)
    return f


def test_real_guard_checks_initial_post_and_revoked_replay(central):
    f = central
    assert not f.post(require_central_authority=f.central_guard).replayed
    assert f.post(require_central_authority=f.central_guard).replayed
    append(f, 2)
    with pytest.raises(PermissionError): f.post(require_central_authority=f.central_guard)


@pytest.mark.parametrize('field', ['org_id', 'cost_pool_id', 'node_key', 'epoch'])
def test_foreign_or_stale_claim_denied(central, field):
    f = central
    change = dict(org_id=f.orgs[1], cost_pool_id=f.pool + 100000, node_key=uuid4(), epoch=2)
    with f.factory.begin() as db, pytest.raises(PermissionError):
        require_cost_pool_authority(db, f.context, replace(f.central_claim, **{field: change[field]}), cost_pool_id=f.pool)


def test_branch_authority_does_not_grant_central_authority(stock):
    from Model.containermgmt.Inventory.CostPool import InventoryCostPool
    f = stock
    with f.factory.begin() as db:
        pool = InventoryCostPool(org_id=f.orgs[0], code='NOAUTH', name='Synthetic unconfigured', created_by=f.actor)
        db.add(pool); db.flush(); f.pool = pool.id
    with f.factory.begin() as db, pytest.raises(PermissionError):
        require_cost_pool_authority(db, f.context,
            CostPoolAuthorityClaim(f.orgs[0], f.pool, f.node_key, 1), cost_pool_id=f.pool)


@pytest.mark.parametrize('epoch', [0, 1, 3])
def test_epoch_must_be_consecutive(central, epoch):
    with pytest.raises(DBAPIError): append(central, epoch)


@pytest.mark.parametrize('sql', [
    'UPDATE containermgmt.inventory_cost_pool_authority_epochs SET is_deleted=true WHERE org_id=:org',
    'DELETE FROM containermgmt.inventory_cost_pool_authority_epochs WHERE org_id=:org'])
def test_history_immutable(central, sql):
    with central.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text(sql), {'org': central.orgs[0]})


def test_foreign_node_rejected_by_database(central):
    f = central
    with f.factory.begin() as db:
        node = StoreNode(org_id=f.orgs[1], node_key=uuid4(), created_by=f.actor)
        db.add(node); db.flush(); key = node.id
    with pytest.raises(DBAPIError): append(f, 2, 'ACTIVE', key)


def test_guard_holds_authority_stable_until_commit(central):
    f = central
    with f.factory.begin() as db:
        f.central_guard(db)
        with pytest.raises(DBAPIError):
            with f.factory.begin() as other:
                other.execute(text("SET LOCAL lock_timeout='100ms'"))
                other.add(CostPoolAuthorityEpoch(org_id=f.orgs[0], cost_pool_id=f.pool,
                    node_id=f.node_id, epoch=2, state='SUSPENDED', reason='Synthetic', created_by=f.actor))
    append(f, 2)


def test_competing_epochs_have_one_winner(central):
    f = central; barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        try: append(f, 2); return 'posted'
        except DBAPIError: return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ['posted', 'rejected']


def test_migration_replay_preserves_authority(central, monkeypatch):
    from Utils import migrate_20261003_cost_pool_authority as migration
    f = central
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_cost_pool_authority_schema(); migration.ensure_cost_pool_authority_schema()
    with f.factory.begin() as db:
        f.central_guard(db)
        assert db.query(CostPoolAuthorityEpoch).filter_by(org_id=f.orgs[0]).count() == 1


@pytest.mark.parametrize('new_node', [False, True])
def test_current_new_authority_cannot_relabel_historical_intent(central, new_node):
    from Services.inventory_posting_service import PostingConflict
    f = central; f.post()
    node_id, node_key = f.node_id, f.node_key
    if new_node:
        node_key = uuid4()
        with f.factory.begin() as db:
            node = StoreNode(org_id=f.orgs[0], node_key=node_key, created_by=f.actor)
            db.add(node); db.flush(); node_id = node.id
    append(f, 2, 'ACTIVE', node_id)
    claim = replace(f.central_claim, node_key=node_key, epoch=2)
    with pytest.raises(PermissionError): f.post()  # old claim is fenced
    with pytest.raises(PostingConflict): f.post(authority_claim=claim)  # new claim changes intent


def test_other_valid_pool_authority_cannot_post_this_proposal(central):
    from Model.containermgmt.Inventory.CostPool import InventoryCostPool
    f = central
    with f.factory.begin() as db:
        pool = InventoryCostPool(org_id=f.orgs[0], code='OTHER', name='Synthetic other pool', created_by=f.actor)
        db.add(pool); db.flush(); pool_id = pool.id
        db.add(CostPoolAuthorityEpoch(org_id=f.orgs[0], cost_pool_id=pool_id, node_id=f.node_id,
            epoch=1, state='ACTIVE', reason='Synthetic other authority', created_by=f.actor))
    with pytest.raises(PermissionError, match='proposal outside'):
        f.post(authority_claim=replace(f.central_claim, cost_pool_id=pool_id))
    assert f.content_evidence()


def test_noop_callback_cannot_bypass_persisted_authority(central):
    f = central; append(f, 2)
    with pytest.raises(PermissionError):
        f.post(require_central_authority=lambda db: None)
    assert f.content_evidence()
