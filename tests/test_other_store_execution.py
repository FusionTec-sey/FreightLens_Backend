from decimal import Decimal as D
from uuid import uuid4
import pytest
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Model.containermgmt.Inventory.StockLedger import StockReservation, StockBalance
from Services.manager_case_service import request_case, review_case
from Services.stock_ledger_service import reserve_stock
from Services.inventory_posting_service import PostingConflict
from tests.test_other_store_fulfilment import fulfilment  # noqa: F401
from tests.test_store_allocation import allocation  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def approved(fulfilment):
    f = fulfilment
    with f.factory.begin() as db: f.binding = f.load_other(db)
    f.case = uuid4(); f.execute_op = uuid4(); f.execute_hold = uuid4()
    request_case(f.factory, f.context, f.actor, f.case, binding=f.binding, reason='Explicit other-store request',
        load_binding=f.load_other, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=f.case, binding=f.binding,
        expected_version=1, outcome='APPROVED', reason='Independent review', load_binding=f.load_other, authorize=lambda db: None)
    def execute(**changes):
        return reserve_stock(f.factory, f.context, f.actor, changes.pop('operation_key', f.execute_op), **dict(dict(
            balance_id=f.other_balance, reservation_key=f.execute_hold, source_line_key=f.source.stock_source_key(),
            quantity=D('5'), input_unit='PCS', review_at=f.review_at, reason='Approved explicit fulfilment',
            sales_source=f.source, other_store_case_key=f.case, other_store_binding=f.binding,
            business_date=f.action.business_date, authority=f.other_claim, authorize=lambda db: None), **changes))
    f.execute = execute
    return f


def test_approved_hold_is_atomic_and_replay_has_one_effect(approved):
    f = approved
    first = f.execute(); replay = f.execute()
    assert replay.replayed and replay.result == first.result
    with f.factory() as db:
        assert db.query(StockReservation).filter_by(org_id=f.orgs[0], reservation_key=f.execute_hold).count() == 1
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0], operation_key=f.execute_op).count() == 1
        assert db.get(StockBalance, f.other_balance).reserved == D('5')


def test_ordinary_writer_cannot_use_other_store_without_exact_case(approved):
    f = approved
    with pytest.raises(PostingConflict, match='explicit fulfilment approval'):
        f.execute(other_store_case_key=None, other_store_binding=None)
    with pytest.raises(PostingConflict, match='differs'):
        f.execute(quantity=D('6'))


def test_replay_rechecks_authority_and_permission(approved):
    f = approved; f.execute()
    with pytest.raises((PermissionError, PostingConflict, ValueError)):
        f.execute(authority=f.claim)
    def denied(db): raise PermissionError('Revoked')
    with pytest.raises(PermissionError): f.execute(authorize=denied)


def test_stale_stock_denies_and_does_not_consume_case(approved):
    f = approved
    f.reserve(f.other_balance, quantity=D('1'), business_date=f.action.business_date, authority=f.other_claim)
    with pytest.raises(PostingConflict, match='Chosen stock changed'): f.execute()
    with f.factory() as db:
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0], operation_key=f.execute_op).count() == 0


def test_stock_effect_failure_rolls_back_case_consumption(approved):
    f = approved
    import Services.stock_ledger_service as ledger
    def failed(*args): raise ValueError('Synthetic stock failure')
    with pytest.MonkeyPatch.context() as monkey:
        # Loader uses its imported original; effect fails after case consumption.
        monkey.setattr(ledger, '_effective_policy', failed)
        with pytest.raises(ValueError, match='Synthetic stock failure'): f.execute()
    with f.factory() as db:
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0], operation_key=f.execute_op).count() == 0
        assert db.get(StockBalance, f.other_balance).reserved == 0
    assert not f.execute().replayed


def test_changed_source_hold_state_denies_approved_execution(approved):
    f = approved; f.hold(quantity=D('20'))
    with pytest.raises(PostingConflict): f.execute()


def test_new_operation_cannot_reuse_consumed_approval(approved):
    f = approved; f.execute()
    with pytest.raises(PostingConflict): f.execute(operation_key=uuid4(), reservation_key=uuid4())


def test_concurrent_identical_execution_has_one_effect(approved):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = approved; barrier = Barrier(2)
    def run():
        barrier.wait(timeout=10)
        return f.execute()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert sorted(result.replayed for result in results) == [False, True]
    with f.factory() as db: assert db.get(StockBalance, f.other_balance).reserved == D('5')


def test_compatible_local_holds_remain_protected_when_other_store_executes(approved):
    f = approved; f.hold(quantity=D('10'))
    with f.factory.begin() as db: f.binding = f.load_other(db)
    f.case = uuid4()
    request_case(f.factory, f.context, f.actor, f.case, binding=f.binding, reason='Exact combined demand',
        load_binding=f.load_other, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=f.case, binding=f.binding,
        expected_version=1, outcome='APPROVED', reason='Explicit compatible locations', load_binding=f.load_other, authorize=lambda db: None)
    f.execute()
    with f.factory() as db:
        holds = db.query(StockReservation).filter_by(org_id=f.orgs[0], source_line_key=f.source.stock_source_key()).all()
        assert sum(row.quantity-row.released for row in holds) == D('15')
        assert db.get(StockBalance, f.other_balance).reserved == D('5')
