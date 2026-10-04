from datetime import date
from decimal import Decimal as D
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
import pytest
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch, StockReservation
from Schema.BranchCounterSchema import CounterSave
from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.branch_action_context_service import BranchActionContext
from Services.inventory_quantity_service import QuantityBreakdown
from Services.inventory_posting_service import PostingConflict
from Services.stock_ledger_service import open_batch_stock, reserve_stock
from Services.store_allocation_service import allocate_store_stock
from Routes.Inventory.BranchCounterRouter import save_counter
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401
from tests.test_branch_counters import payload
from Utils.org_filter import OrgContext


@pytest.fixture
def allocation(demand):
    f = demand
    with f.factory.begin() as db:
        location = StockLocation(org_id=f.orgs[0], branch_id=f.branches[0], code='TOOLS', name='Tools counter', kind='SITE')
        db.add(location); db.flush(); f.preferred = location.id
        balance = db.get(StockBalance, f.balance)
        batch = db.get(StockBatch, balance.batch_key)
        f.policy = InventoryPolicyConfig.model_validate(balance.policy_config)
        f.batch = StockBatchIdentity(batch_key=batch.batch_key, code=batch.code, shade=batch.shade, calibre=batch.calibre)
    opened = open_batch_stock(f.factory, f.context, f.actor, uuid4(), branch_id=f.branches[0],
        location_id=f.preferred, product_id=f.products[0], policy=f.policy, batch=f.batch,
        quantities=QuantityBreakdown(D('5')), reason='Synthetic plumbing product at tools counter',
        authorize=lambda db: None, authority=f.claim)
    f.preferred_balance = opened.result['balance_id']
    f.counter_key = uuid4()
    with f.factory() as db:
        f.counter = save_counter(f.branches[0], f.counter_key, CounterSave.model_validate(payload(config=dict(
            name='Tools specialist', purpose='CHECKOUT', is_enabled=True, default_stock_location_id=f.preferred))),
            db, f.context, SimpleNamespace(id=f.actor))
    f.action = BranchActionContext(f.branches[0], f.counter.id, 1, 1, date(2026,10,3), 'CHECKOUT')
    from Services.staff_store_assignment_service import save_staff_store_assignment
    from Schema.StaffStoreAssignmentSchema import StaffStoreConfig
    save_staff_store_assignment(f.factory, f.context, f.actor, uuid4(), user_id=f.actor,
        config=StaffStoreConfig(branch_id=f.branches[0], counter_id=f.counter.id, is_enabled=True),
        expected_version=0, authorize=lambda db: None)
    def allocate(**kw):
        return allocate_store_stock(kw.pop('factory', f.factory), kw.pop('context', f.context), f.actor,
            kw.pop('operation', f.operation), source=kw.pop('source', f.source),
            action_context=kw.pop('action', f.action), quantity=kw.pop('quantity', D('20')), input_unit='PCS',
            review_at=f.review_at, reason='Synthetic store-wide request', authority=kw.pop('authority', f.claim),
            authorize=kw.pop('authorize', lambda db: None), assignment_version=kw.pop('assignment_version', 1))
    f.allocate = allocate
    return f


def test_preferred_then_store_wide_split_exact_retry(allocation):
    f = allocation
    first = f.allocate(); again = f.allocate()
    assert not first.replayed and again.replayed and first.result == again.result
    assert {r['location_id']: D(r['quantity']) for r in first.result['reservations']} == {f.preferred: D(5), f.locations[0]: D(15)}
    with f.factory() as db:
        assert db.query(StockReservation).filter_by(org_id=f.orgs[0]).count() == 2
    with pytest.raises(PostingConflict, match='history'): f.allocate(operation=uuid4())


def test_missing_counter_preference_does_not_block(allocation):
    f = allocation
    with f.factory() as db:
        save_counter(f.branches[0], f.counter_key, CounterSave.model_validate(payload(expected_version=1, config=dict(
            name='Tools specialist', purpose='CHECKOUT', is_enabled=True))), db, f.context, SimpleNamespace(id=f.actor))
    assert f.allocate(action=replace(f.action, counter_settings_version=2)).result['quantity'] == '20'


def test_combined_source_cap_is_enforced_for_same_store_splits(allocation):
    f = allocation; f.hold(quantity=D('20'))
    with pytest.raises(PostingConflict, match='Combined holds'):
        reserve_stock(f.factory, f.context, f.actor, uuid4(), balance_id=f.preferred_balance,
            reservation_key=uuid4(), source_line_key=f.source.stock_source_key(), quantity=D('5'), input_unit='PCS',
            review_at=f.review_at, business_date=f.action.business_date, reason='Synthetic excess',
            authority=f.claim, authorize=lambda db: None, sales_source=f.source)


def test_failure_after_children_rolls_back_and_can_retry(allocation):
    f = allocation
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.allocate(factory=db)
            raise RuntimeError('Synthetic later invoice failure')
    with f.factory() as db:
        assert db.query(StockReservation).filter_by(org_id=f.orgs[0]).count() == 0
    assert not f.allocate().replayed


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_allocations_have_one_effect(allocation, same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = allocation; barrier = Barrier(2)
    def run(key):
        barrier.wait(timeout=10)
        try: return f.allocate(operation=key).replayed
        except PostingConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, [f.operation, f.operation if same_key else uuid4()]))
    assert results.count(False) == 1 and results.count(True if same_key else 'conflict') == 1


@pytest.mark.parametrize('denial', ['permission', 'foreign', 'other_store', 'stale_epoch'])
def test_replay_rechecks_current_authority(allocation, denial):
    f = allocation; f.allocate()
    def deny(db): raise PermissionError('Synthetic revoked access')
    changes = {'permission': dict(authorize=deny),
        'foreign': dict(context=OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)),
        'other_store': dict(action=replace(f.action, branch_id=f.branches[1])),
        'stale_epoch': dict(authority=replace(f.claim, epoch=2))}[denial]
    with pytest.raises((PermissionError, ValueError, LookupError)): f.allocate(**changes)


def test_short_preferred_lot_does_not_hide_sufficient_compatible_lot(allocation):
    f = allocation
    f.reserve(f.balance, quantity=D('38'), business_date=f.action.business_date)
    other = open_batch_stock(f.factory, f.context, f.actor, uuid4(), branch_id=f.branches[0],
        location_id=f.locations[0], product_id=f.products[0], policy=f.policy,
        batch=StockBatchIdentity(batch_key=uuid4(), code='SECOND-LOT', shade='DIFFERENT'),
        quantities=QuantityBreakdown(D('30')), reason='Synthetic other lot',
        authorize=lambda db: None, authority=f.claim)
    result = f.allocate().result
    assert len(result['reservations']) == 1
    assert result['reservations'][0]['balance_id'] == other.result['balance_id']


@pytest.mark.parametrize('unavailable', ['expired', 'inactive_parent', 'other_warehouse'])
def test_ineligible_stock_cannot_cover_shortage(allocation, unavailable):
    from Model.containermgmt.Inventory.Location import InventoryBranch
    from Model.containermgmt.Inventory.PostingAuthority import BranchAuthorityEpoch
    f = allocation; f.reserve(f.balance, quantity=D('38'), business_date=f.action.business_date)
    branch_id, claim = f.branches[0], f.claim
    with f.factory.begin() as db:
        if unavailable == 'other_warehouse':
            branch = InventoryBranch(org_id=f.orgs[0], code='WAREHOUSE', name='Separate warehouse', kind='WAREHOUSE')
            db.add(branch); db.flush(); branch_id = branch.id
            db.add(BranchAuthorityEpoch(org_id=f.orgs[0], branch_id=branch_id, node_id=f.node_id,
                epoch=1, state='ACTIVE', reason='Synthetic', created_by=f.actor))
            claim = replace(f.claim, branch_id=branch_id)
        location = StockLocation(org_id=f.orgs[0], branch_id=branch_id, code='EXTRA', name='Synthetic', kind='SITE')
        db.add(location); db.flush(); location_id = location.id
        if unavailable == 'inactive_parent':
            child = StockLocation(org_id=f.orgs[0], branch_id=branch_id, code='CHILD', name='Synthetic', kind='ZONE', parent_id=location.id)
            db.add(child); db.flush(); location_id = child.id
        root_id = location.id
    open_batch_stock(f.factory, f.context, f.actor, uuid4(), branch_id=branch_id, location_id=location_id,
        product_id=f.products[0], policy=f.policy,
        batch=StockBatchIdentity(batch_key=uuid4(), code='EXTRA', shade='EXTRA', expires_on=date(2026,10,2) if unavailable == 'expired' else None),
        quantities=QuantityBreakdown(D('30')), reason='Synthetic ineligible stock', authorize=lambda db: None, authority=claim)
    if unavailable == 'inactive_parent':
        with f.factory.begin() as db: db.get(StockLocation, root_id).is_active = False
    with pytest.raises(PostingConflict, match='Insufficient compatible'): f.allocate()


def test_competing_documents_cannot_oversell_store_stock(allocation):
    from Services.sales_intent_service import save_sales_intent
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = allocation; other = uuid4()
    save_sales_intent(f.factory, f.context, f.actor, uuid4(), other, f.payload, expected_version=0, authorize=lambda db: None)
    source = f.source.model_copy(update={'document_key': other})
    barrier = Barrier(2)
    def run(demand_source):
        barrier.wait(timeout=10)
        try:
            f.allocate(operation=uuid4(), source=demand_source, quantity=D('24'))
            return 'ok'
        except PostingConflict: return 'shortage'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, [f.source, source])) == ['ok', 'shortage']
    with f.factory() as db:
        assert sum(row.reserved for row in db.query(StockBalance).filter_by(org_id=f.orgs[0])) == D('24')


def test_failed_second_child_rolls_back_first(allocation, monkeypatch):
    import Services.store_allocation_service as service
    f = allocation; original = service.reserve_stock; calls = []
    def fail_second(*args, **kwargs):
        calls.append(kwargs['balance_id'])
        if len(calls) == 2: raise PostingConflict('Synthetic second-child rejection')
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'reserve_stock', fail_second)
    with pytest.raises(PostingConflict, match='second-child'): f.allocate()
    with f.factory() as db:
        assert db.query(StockReservation).filter_by(org_id=f.orgs[0]).count() == 0
        assert all(row.reserved == 0 for row in db.query(StockBalance).filter_by(org_id=f.orgs[0]))


def test_changed_staff_assignment_denies_allocation_replay(allocation):
    from Services.staff_store_assignment_service import save_staff_store_assignment
    from Schema.StaffStoreAssignmentSchema import StaffStoreConfig
    f = allocation; f.allocate()
    save_staff_store_assignment(f.factory, f.context, f.actor, uuid4(), user_id=f.actor,
        config=StaffStoreConfig(branch_id=f.branches[0], is_enabled=False), expected_version=1, authorize=lambda db: None)
    with pytest.raises(PermissionError, match='assignment'): f.allocate()
