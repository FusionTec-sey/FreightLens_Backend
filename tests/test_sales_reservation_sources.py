from datetime import date
from decimal import Decimal as D
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource
from Services.stock_ledger_service import open_batch_stock, reserve_stock
from Services.inventory_quantity_service import QuantityBreakdown
from Services.inventory_posting_service import PostingConflict
from Services.sales_intent_service import save_sales_intent
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401
from tests.test_inventory_policy_drafts import config


@pytest.fixture
def demand(ready):
    f = ready; f.save(uuid4())
    f.source = SalesDemandReference(document_key=f.document, version=1, line_key=f.payload.lines[0].line_key)
    opened = open_batch_stock(f.factory, f.context, f.actor, uuid4(), branch_id=f.branches[0],
        location_id=f.locations[0], product_id=f.products[0], policy=InventoryPolicyConfig(**config()),
        batch=StockBatchIdentity(batch_key=uuid4(), code='DEMO', shade='DEMO'),
        quantities=QuantityBreakdown(D('40')), reason='Synthetic reviewed opening',
        authorize=lambda db: None, authority=f.claim)
    f.balance = opened.result['balance_id']; f.reservation = uuid4(); f.operation = uuid4()
    def hold(**kw):
        source = kw.pop('source', f.source)
        return reserve_stock(kw.pop('factory', f.factory), f.context, f.actor, kw.pop('operation', f.operation),
            balance_id=f.balance, reservation_key=f.reservation, source_line_key=source.stock_source_key(),
            quantity=kw.pop('quantity', D('20')), input_unit=kw.pop('unit', 'PCS'), review_at=f.review_at,
            reason='Synthetic customer interaction hold', business_date=date(2026, 10, 3),
            authorize=kw.pop('authorize', lambda db: None), authority=f.claim, sales_source=source)
    f.hold = hold
    return f


def test_link_and_stock_effect_commit_once(demand):
    f = demand
    assert not f.hold().replayed and f.hold().replayed
    with f.factory() as db:
        link = db.get(SalesReservationSource, f.reservation)
        assert link.document_key == f.document and link.line_key == f.source.line_key
        assert link.version == 1


@pytest.mark.parametrize('quantity,unit', [('25', 'PCS'), ('3', 'BOX')])
def test_line_cap_applies_after_exact_unit_conversion(demand, quantity, unit):
    with pytest.raises(PostingConflict, match='exceeds'):
        demand.hold(quantity=D(quantity), unit=unit)


def test_unknown_and_stale_sources_fail_before_posting(demand):
    f = demand
    with pytest.raises(LookupError): f.hold(source=f.source.model_copy(update={'document_key': uuid4()}))
    with pytest.raises(PostingConflict): f.hold(source=f.source.model_copy(update={'version': 2}))
    with pytest.raises(LookupError): f.hold(source=f.source.model_copy(update={'line_key': uuid4()}))


def test_source_link_and_stock_rollback_together(demand):
    f = demand
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.hold(factory=db)
            raise RuntimeError('Synthetic rollback')
    with f.factory() as db: assert db.get(SalesReservationSource, f.reservation) is None
    assert not f.hold().replayed


def test_active_hold_blocks_reducing_or_removing_demand_but_allows_increase(demand):
    f = demand; f.hold()
    changed = f.payload.model_copy(deep=True); changed.lines[0].quantity = '1'
    def revise(payload):
        return save_sales_intent(f.factory, f.context, f.actor, uuid4(), f.document,
            payload, expected_version=1, authorize=lambda db: None)
    with pytest.raises(PostingConflict, match='below'): revise(changed)
    changed.lines[0].quantity = '2'; changed.lines[0].line_key = uuid4()
    with pytest.raises(PostingConflict, match='removed'): revise(changed)
    changed = f.payload.model_copy(deep=True); changed.lines[0].quantity = '3'
    assert revise(changed).result['version'] == 2
    with pytest.raises(PostingConflict, match='changed'): f.hold()


def test_source_history_cannot_be_deleted(demand):
    f = demand; f.hold()
    with pytest.raises(DBAPIError), f.factory.begin() as db:
        db.execute(text('DELETE FROM containermgmt.sales_reservation_sources WHERE reservation_key=:key'), {'key': f.reservation})


def test_revoked_permission_denies_existing_receipt(demand):
    f = demand; f.hold()
    def deny(db): raise PermissionError('Denied')
    with pytest.raises(PermissionError): f.hold(authorize=deny)


def test_hold_and_draft_reduction_race_has_one_winner(demand):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = demand; barrier = Barrier(2)
    changed = f.payload.model_copy(deep=True); changed.lines[0].quantity = '1'
    def run(action):
        barrier.wait(timeout=10)
        try:
            if action == 'hold': f.hold()
            else: save_sales_intent(f.factory, f.context, f.actor, uuid4(), f.document,
                    changed, expected_version=1, authorize=lambda db: None)
            return action
        except PostingConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes = list(pool.map(run, ['hold', 'edit']))
    assert outcomes.count('conflict') == 1


def test_other_store_and_customer_reassignment_are_not_automatic(demand):
    from Model.containermgmt.Inventory.Location import InventoryBranch
    f = demand
    with f.factory.begin() as db:
        branch = InventoryBranch(org_id=f.orgs[0], code='SECOND', name='Synthetic second', kind='STORE')
        db.add(branch); db.flush(); branch_id = branch.id
    changed = f.payload.model_copy(deep=True); changed.branch_id = branch_id
    f.hold()
    with pytest.raises(PostingConflict, match='customer or selling store'):
        save_sales_intent(f.factory, f.context, f.actor, uuid4(), f.document,
            changed, expected_version=1, authorize=lambda db: None)


def test_detail_exposes_reserved_quantity_separately(demand):
    from Services.sales_intent_service import get_sales_intent
    f = demand; f.hold()
    with f.factory() as db:
        result = get_sales_intent(db, f.context, f.document, authorize=lambda db: None)
    assert D(result['lines'][0]['reserved_quantity']) == 20
    assert D(result['lines'][0]['base_quantity']) == 24
    assert result['status'] == 'DRAFT'


def test_link_migration_is_replayable(demand, monkeypatch, test_engine):
    import Utils.migrate_20261003_sales_reservation_sources as migration
    monkeypatch.setattr(migration, 'engine', test_engine)
    migration.ensure_sales_reservation_sources_schema(); migration.ensure_sales_reservation_sources_schema()
    assert not demand.hold().replayed


def test_generic_release_cannot_bypass_source_review(demand):
    from Services.stock_ledger_service import release_stock
    f = demand; f.hold()
    with pytest.raises(PostingConflict, match='reviewed release'):
        release_stock(f.factory, f.context, f.actor, uuid4(), balance_id=f.balance,
            reservation_key=f.reservation, source_line_key=f.source.stock_source_key(),
            quantity=D('1'), reason='Not an approved case', authorize=lambda db: None, authority=f.claim)
