from decimal import Decimal as D
from dataclasses import replace
from uuid import uuid4
import pytest
from Model.Credentials.users import User
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.PostingAuthority import BranchAuthorityEpoch
from Model.containermgmt.Inventory.StockLedger import StockReservation
from Services.stock_ledger_service import open_batch_stock
from Services.inventory_quantity_service import QuantityBreakdown
from Services.inventory_posting_service import PostingConflict
from Services.other_store_fulfilment_service import load_other_store_binding
from Services.manager_case_service import request_case, review_case
from tests.test_store_allocation import allocation  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def fulfilment(allocation):
    f = allocation
    with f.factory.begin() as db:
        branch = InventoryBranch(org_id=f.orgs[0], code='SEPARATE', name='Synthetic separate warehouse', kind='WAREHOUSE')
        db.add(branch); db.flush(); f.other_branch = branch.id
        location = StockLocation(org_id=f.orgs[0], branch_id=branch.id, code='SITE', name='Synthetic site', kind='SITE')
        reviewer = User(org_id=f.orgs[0], username='review-'+uuid4().hex, password_hash='synthetic')
        db.add_all([location, reviewer]); db.flush(); f.reviewer = reviewer.id; location_id = location.id
        db.add(BranchAuthorityEpoch(org_id=f.orgs[0], branch_id=branch.id, node_id=f.node_id,
            epoch=1, state='ACTIVE', reason='Synthetic other authority', created_by=f.actor))
    f.other_claim = replace(f.claim, branch_id=f.other_branch)
    opened = open_batch_stock(f.factory, f.context, f.actor, uuid4(), branch_id=f.other_branch,
        location_id=location_id, product_id=f.products[0], policy=f.policy, batch=f.batch,
        quantities=QuantityBreakdown(D('30')), reason='Synthetic other-store stock',
        authorize=lambda db: None, authority=f.other_claim)
    f.other_balance = opened.result['balance_id']
    f.load_other = lambda db, **changes: load_other_store_binding(db, f.context, f.source, **dict(
        dict(requestor_id=f.actor, assignment_version=1, balance_id=f.other_balance,
            expected_stock_version=1, quantity=D('5'), input_unit='PCS', review_at=f.review_at), **changes))
    return f


def test_explicit_other_store_review_has_no_stock_effect(fulfilment):
    f = fulfilment
    with f.factory.begin() as db: binding = f.load_other(db)
    assert binding.details['selling_branch_id'] == f.branches[0]
    assert binding.details['fulfilment_branch_id'] == f.other_branch
    case = uuid4()
    request_case(f.factory, f.context, f.actor, case, binding=binding, reason='Explicit customer request',
        load_binding=f.load_other, authorize=lambda db: None)
    with pytest.raises(PermissionError):
        review_case(f.factory, f.context, f.actor, uuid4(), case_key=case, binding=binding,
            expected_version=1, outcome='APPROVED', reason='Invalid self review', load_binding=f.load_other, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=case, binding=binding,
        expected_version=1, outcome='APPROVED', reason='Independent approval', load_binding=f.load_other, authorize=lambda db: None)
    with f.factory() as db: assert db.query(StockReservation).filter_by(org_id=f.orgs[0]).count() == 0


def test_existing_local_holds_count_towards_cross_store_cap(fulfilment):
    f = fulfilment; f.hold(quantity=D('20'))
    with f.factory.begin() as db, pytest.raises(PostingConflict, match='Combined holds'): f.load_other(db)
    with f.factory.begin() as db:
        assert f.load_other(db, quantity=D('4')).details['existing_holds']['remaining'] == '20.000000'


def test_local_stock_does_not_use_exception_path(fulfilment):
    f = fulfilment
    with f.factory.begin() as db, pytest.raises(ValueError, match='Same-store'): f.load_other(db, balance_id=f.balance)


def test_changed_chosen_stock_invalidates_review(fulfilment):
    f = fulfilment
    with f.factory.begin() as db: binding = f.load_other(db)
    key = uuid4()
    request_case(f.factory, f.context, f.actor, key, binding=binding, reason='Explicit request', load_binding=f.load_other, authorize=lambda db: None)
    f.reserve(f.other_balance, quantity=D('1'), business_date=f.action.business_date, authority=f.other_claim)
    with pytest.raises(PostingConflict, match='Chosen stock changed'):
        review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=key, binding=binding,
            expected_version=1, outcome='APPROVED', reason='Stale review', load_binding=f.load_other, authorize=lambda db: None)


def test_revoked_staff_assignment_denies_exception(fulfilment):
    from Services.staff_store_assignment_service import save_staff_store_assignment
    from Schema.StaffStoreAssignmentSchema import StaffStoreConfig
    f = fulfilment
    save_staff_store_assignment(f.factory, f.context, f.actor, uuid4(), user_id=f.actor,
        config=StaffStoreConfig(branch_id=f.branches[0], is_enabled=False), expected_version=1, authorize=lambda db: None)
    with f.factory.begin() as db, pytest.raises(PermissionError): f.load_other(db)


def test_foreign_company_cannot_load_demand_or_chosen_stock(fulfilment):
    f = fulfilment; f.context.current_org_id = f.orgs[1]
    with f.factory.begin() as db, pytest.raises(LookupError): f.load_other(db)


def test_insufficient_chosen_stock_cannot_be_approved(fulfilment):
    f = fulfilment
    f.reserve(f.other_balance, quantity=D('26'), business_date=f.action.business_date, authority=f.other_claim)
    with f.factory.begin() as db, pytest.raises(PostingConflict, match='insufficient'):
        f.load_other(db, expected_stock_version=2)
