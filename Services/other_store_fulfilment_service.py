"""Exact other-store review binding, not authority to reserve or move stock.

The user chooses one same-company stock bucket. Request/review never posts stock;
execution must independently validate target-node authority and business date.
"""
from datetime import datetime, timezone
from decimal import Context, Decimal, localcontext
from sqlalchemy import text
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch, StockReservation, StockMovement
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseUse
from Services.reservation_release_service import current_review_schedule
from Model.containermgmt.Orders.SalesIntent import SalesIntentRevision
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.sales_reservation_source_service import owned, load_reservation_demand
from Services.staff_store_assignment_service import require_staff_store_assignment
from Services.default_stock_area_service import require_owned_stock_area
from Services.inventory_unit_service import convert_quantity
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding
from Services.reservation_reallocation_service import target_hold_snapshot
from Services.stock_ledger_service import _locked_balance, _snapshot, _effective_policy


def load_other_store_binding(db, context, source, *, requestor_id, assignment_version,
                             balance_id, expected_stock_version, quantity, input_unit, review_at,
                             replay_operation=None, reservation_key=None, case_key=None):
    """Lock assignment, saved source and chosen stock; bind exact review intent.

    Other-store means a different configured branch, not a different island label.
    Candidate expiry is recorded, not treated as permission to post on a later date.
    Caller supplies domain-specific RBAC via the shared manager-case service.
    """
    if not db.in_transaction() or not isinstance(source, SalesDemandReference):
        raise ValueError('Active transaction and typed saved demand required')
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Company denied')
    if not isinstance(review_at, datetime) or review_at.utcoffset() is None:
        raise ValueError('An aware customer-agreed review time is required')
    if type(expected_stock_version) is not int or expected_stock_version <= 0:
        raise ValueError('Explicit stock version required')
    # Read immutable scope first; take branch locks before user/document/stock locks.
    chosen = owned(db, StockBalance, context).filter_by(id=balance_id).one_or_none()
    preview = owned(db, SalesIntentRevision, context).filter_by(document_key=source.document_key, version=source.version).one_or_none()
    if chosen is None or preview is None: raise LookupError('Chosen stock or saved demand not found')
    if chosen.branch_id == preview.branch_id: raise ValueError('Same-store stock uses the ordinary allocation workflow')
    branches = {chosen.branch_id, preview.branch_id}
    locked = owned(db, InventoryBranch, context).filter(InventoryBranch.id.in_(branches),
        InventoryBranch.is_active.is_(True)).order_by(InventoryBranch.id).with_for_update(read=True).all()
    if len(locked) != 2: raise LookupError('Active fulfilment branches not found')
    assignment = require_staff_store_assignment(db, context, requestor_id,
        branch_id=preview.branch_id, expected_version=assignment_version)
    revision, line = load_reservation_demand(db, context, source)
    if revision.status != 'DRAFT': raise PostingConflict('Only unconfirmed draft demand is supported')
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
        {'key': f'stock-source:{context.org_id}:{source.stock_source_key()}'})
    require_owned_stock_area(db, context, chosen.branch_id, chosen.location_id)
    balance = _locked_balance(db, context, balance_id)
    if balance.product_id != line.product_id or balance.base_unit != line.base_unit:
        raise PostingConflict('Chosen stock does not match saved demand')
    base = convert_quantity(InventoryPolicyConfig.model_validate(line.policy), quantity, input_unit)
    if base <= 0: raise ValueError('Positive quantity required')
    if convert_quantity(_effective_policy(db, context, balance), quantity, input_unit) != base:
        raise PostingConflict('Source and stock unit policies disagree')
    # Normalize only this exact committed effect for receipt replay. Any later
    # stock movement, release, schedule or source change still invalidates replay.
    own_replay = False
    if replay_operation is not None:
        use = owned(db, ManagerCaseUse, context).join(ManagerCase,
            (ManagerCase.id == ManagerCaseUse.case_id) & (ManagerCase.org_id == ManagerCaseUse.org_id)).filter(
                ManagerCase.case_key == case_key, ManagerCase.action == 'inventory.fulfilment.other-store',
                ManagerCaseUse.operation_key == replay_operation).one_or_none()
        hold = owned(db, StockReservation, context).filter_by(reservation_key=reservation_key,
            balance_id=balance_id, source_line_key=source.stock_source_key()).one_or_none()
        movement = owned(db, StockMovement, context).filter_by(operation_key=replay_operation,
            balance_id=balance_id, kind='RESERVE').one_or_none()
        if use and hold and movement:
            own_replay = (balance.version == expected_stock_version + 1 and hold.quantity == base
                and hold.released == 0 and hold.review_at == review_at and movement.reservation_id == hold.id
                and movement.reserved_delta == base and current_review_schedule(db, context, hold)[2] == 0)
    if balance.version != expected_stock_version and not own_replay:
        raise PostingConflict('Chosen stock changed; refresh before requesting review')
    if not own_replay and review_at <= datetime.now(timezone.utc): raise ValueError('Choose a future customer follow-up')
    history = target_hold_snapshot(db, context, source, balance_id, compatible_branches=branches,
        exclude=reservation_key if own_replay else None)
    with localcontext(Context(prec=48)):
        if Decimal(history['remaining']) + base > line.base_quantity:
            raise PostingConflict('Combined holds exceed saved demand')
    with localcontext(Context(prec=48)):
        available = _snapshot(balance).available + (base if own_replay else Decimal(0))
    if base > available: raise PostingConflict('Chosen stock has insufficient available quantity')
    batch = owned(db, StockBatch, context).filter_by(batch_key=balance.batch_key,
        product_id=balance.product_id).one() if balance.batch_key else None
    return CaseBinding(org_id=context.org_id, action='inventory.fulfilment.other-store',
        source_type='sales.demand', source_key=str(source.stock_source_key()), source_version=source.version,
        details=dict(source=source.model_dump(mode='json'), requestor_id=requestor_id,
            assignment_version=assignment.version, selling_branch_id=revision.branch_id,
            fulfilment_branch_id=balance.branch_id, location_id=balance.location_id, balance_id=balance.id,
            stock_version=expected_stock_version, product_id=line.product_id, base_unit=line.base_unit,
            quantity=format(base, 'f'), input_quantity=format(quantity, 'f'), input_unit=input_unit,
            review_at=review_at.astimezone(timezone.utc).isoformat(), existing_holds=history,
            batch_key=str(balance.batch_key) if balance.batch_key else None,
            batch_expires_on=batch.expires_on.isoformat() if batch and batch.expires_on else None))
