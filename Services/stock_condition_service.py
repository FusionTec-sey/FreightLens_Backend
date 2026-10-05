"""Bind one exact T18 return line to a reviewed quarantine disposition."""
from decimal import Context, Decimal, localcontext

from sqlalchemy import Numeric, String, cast, func
from sqlalchemy.orm import aliased

from Model.containermgmt.Inventory.ManagerCase import (
    ManagerCase,
    ManagerCaseDecision,
    ManagerCaseUse,
)
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Orders.SalesReturn import (
    SalesCreditNote,
    SalesCreditNoteLine,
    SalesReturnAllocation,
)
from Services.inventory_posting_service import PostingConflict
from Services.inventory_quantity_service import QuantityBreakdown
from Services.inventory_unit_service import convert_quantity
from Services.manager_case_service import CaseBinding
from Services.stock_ledger_service import _locked_balance, _query, _snapshot
from Schema.InventoryPolicySchema import InventoryPolicyConfig


ACTION = "inventory.stock.condition-transition"
SOURCE_TYPE = "sales.return-credit-line"
MOVEMENT_KIND = "CONDITION"
_CONTEXT = Context(prec=48)


def _exact_positive(value):
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("A positive exact quantity is required")
    if value != value.quantize(Decimal("0.000001")):
        raise ValueError("Quantity has more than six decimal places")
    return value


def _consumed_quantity(db, context, line_id):
    rows = _query(db, ManagerCase, context).join(
        ManagerCaseUse,
        (ManagerCaseUse.case_id == ManagerCase.id)
        & (ManagerCaseUse.org_id == ManagerCase.org_id),
    ).filter(
        ManagerCase.action == ACTION,
        ManagerCase.source_type == SOURCE_TYPE,
        ManagerCase.source_key == str(line_id),
    ).with_entities(ManagerCase.binding).all()
    total = Decimal("0.000000")
    with localcontext(_CONTEXT):
        for (binding,) in rows:
            total += Decimal(binding["details"]["quantity"])
    return total.quantize(Decimal("0.000001"))


def _pending_quantity(db, context, line_id, *, exclude_case_key=None):
    query = _query(db, ManagerCase, context).outerjoin(
        ManagerCaseDecision,
        (ManagerCaseDecision.case_id == ManagerCase.id)
        & (ManagerCaseDecision.org_id == ManagerCase.org_id),
    ).outerjoin(
        ManagerCaseUse,
        (ManagerCaseUse.case_id == ManagerCase.id)
        & (ManagerCaseUse.org_id == ManagerCase.org_id),
    ).filter(
        ManagerCase.action == ACTION,
        ManagerCase.source_type == SOURCE_TYPE,
        ManagerCase.source_key == str(line_id),
        ManagerCaseUse.id.is_(None),
        (ManagerCaseDecision.id.is_(None)) | (ManagerCaseDecision.outcome == "APPROVED"),
    )
    if exclude_case_key is not None:
        query = query.filter(ManagerCase.case_key != exclude_case_key)
    rows = query.with_entities(ManagerCase.binding).all()
    total = Decimal("0.000000")
    with localcontext(_CONTEXT):
        for (snapshot,) in rows:
            total += Decimal(snapshot["details"]["quantity"])
    return total.quantize(Decimal("0.000001"))


def list_return_condition_sources(db, context, *, page, limit,
                                  invoice_key=None, credit_note_key=None):
    """Return only current, eligible T18 sources; never expose guessed identities."""
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Stock-condition company denied")
    if type(page) is not int or page <= 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Valid source pagination is required")
    used = db.query(
        ManagerCase.source_key.label("source_key"),
        func.sum(cast(
            ManagerCase.binding["details"]["quantity"].astext,
            Numeric(18, 6),
        )).label("transitioned"),
    ).join(
        ManagerCaseUse,
        (ManagerCaseUse.case_id == ManagerCase.id)
        & (ManagerCaseUse.org_id == ManagerCase.org_id),
    ).filter(
        ManagerCase.org_id == context.org_id,
        ManagerCaseUse.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False),
        ManagerCaseUse.is_deleted.is_(False),
        ManagerCase.action == ACTION,
        ManagerCase.source_type == SOURCE_TYPE,
    ).group_by(ManagerCase.source_key).subquery()
    pending = db.query(
        ManagerCase.source_key.label("source_key"),
        func.sum(cast(
            ManagerCase.binding["details"]["quantity"].astext,
            Numeric(18, 6),
        )).label("pending"),
    ).outerjoin(
        ManagerCaseDecision,
        (ManagerCaseDecision.case_id == ManagerCase.id)
        & (ManagerCaseDecision.org_id == ManagerCase.org_id),
    ).outerjoin(
        ManagerCaseUse,
        (ManagerCaseUse.case_id == ManagerCase.id)
        & (ManagerCaseUse.org_id == ManagerCase.org_id),
    ).filter(
        ManagerCase.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False),
        ManagerCase.action == ACTION,
        ManagerCase.source_type == SOURCE_TYPE,
        ManagerCaseUse.id.is_(None),
        (ManagerCaseDecision.id.is_(None)) | (ManagerCaseDecision.outcome == "APPROVED"),
    ).group_by(ManagerCase.source_key).subquery()
    return_totals = db.query(
        SalesCreditNoteLine.org_id.label("org_id"),
        SalesCreditNoteLine.balance_id.label("balance_id"),
        SalesCreditNoteLine.return_operation_key.label("operation_key"),
        func.sum(SalesCreditNoteLine.quantity).label("quantity"),
    ).filter(SalesCreditNoteLine.is_deleted.is_(False)).group_by(
        SalesCreditNoteLine.org_id,
        SalesCreditNoteLine.balance_id,
        SalesCreditNoteLine.return_operation_key,
    ).subquery()
    returned = aliased(StockMovement)
    transitioned = func.coalesce(used.c.transitioned, Decimal("0.000000"))
    pending_quantity = func.coalesce(pending.c.pending, Decimal("0.000000"))
    remaining = func.greatest(
        SalesCreditNoteLine.quantity - transitioned - pending_quantity,
        Decimal("0.000000"),
    )
    query = _query(db, SalesCreditNoteLine, context).join(
        SalesCreditNote,
        (SalesCreditNote.credit_note_key == SalesCreditNoteLine.credit_note_key)
        & (SalesCreditNote.org_id == SalesCreditNoteLine.org_id)
        & SalesCreditNote.is_deleted.is_(False),
    ).join(
        SalesReturnAllocation,
        (SalesReturnAllocation.id == SalesCreditNoteLine.return_allocation_id)
        & (SalesReturnAllocation.org_id == SalesCreditNoteLine.org_id)
        & SalesReturnAllocation.is_deleted.is_(False),
    ).join(
        StockBalance,
        (StockBalance.id == SalesCreditNoteLine.balance_id)
        & (StockBalance.org_id == SalesCreditNoteLine.org_id)
        & StockBalance.is_deleted.is_(False),
    ).join(
        InventoryBranch,
        (InventoryBranch.id == StockBalance.branch_id)
        & (InventoryBranch.org_id == StockBalance.org_id)
        & InventoryBranch.is_deleted.is_(False)
        & InventoryBranch.is_active.is_(True),
    ).join(
        StockLocation,
        (StockLocation.id == StockBalance.location_id)
        & (StockLocation.branch_id == StockBalance.branch_id)
        & (StockLocation.org_id == StockBalance.org_id)
        & StockLocation.is_deleted.is_(False)
        & StockLocation.is_active.is_(True),
    ).join(
        Product,
        (Product.id == StockBalance.product_id)
        & (Product.org_id == StockBalance.org_id)
        & Product.is_deleted.is_(False)
        & (Product.status == "active")
        & Product.is_shared.is_(False),
    ).join(
        returned,
        (returned.org_id == SalesCreditNoteLine.org_id)
        & (returned.balance_id == SalesCreditNoteLine.balance_id)
        & (returned.operation_key == SalesCreditNoteLine.return_operation_key)
        & (returned.kind == "RETURN")
        & returned.is_deleted.is_(False),
    ).join(
        return_totals,
        (return_totals.c.org_id == returned.org_id)
        & (return_totals.c.balance_id == returned.balance_id)
        & (return_totals.c.operation_key == returned.operation_key)
        & (return_totals.c.quantity == returned.on_hand_delta),
    ).outerjoin(
        used, used.c.source_key == cast(SalesCreditNoteLine.id, String)
    ).outerjoin(
        pending, pending.c.source_key == cast(SalesCreditNoteLine.id, String)
    ).filter(
        SalesCreditNote.org_id == context.org_id,
        SalesReturnAllocation.org_id == context.org_id,
        StockBalance.org_id == context.org_id,
        returned.org_id == context.org_id,
        StockBalance.tracking_policy.in_(("UNTRACKED", "BATCH")),
        StockBalance.policy_config.is_not(None),
        StockBalance.base_unit == SalesCreditNoteLine.base_unit,
        SalesCreditNoteLine.quantity - transitioned > 0,
        StockBalance.quarantined > 0,
    )
    if invoice_key is not None:
        query = query.filter(SalesCreditNoteLine.invoice_key == invoice_key)
    if credit_note_key is not None:
        query = query.filter(SalesCreditNoteLine.credit_note_key == credit_note_key)
    total = query.count()
    rows = query.with_entities(
        SalesCreditNoteLine,
        SalesCreditNote.credit_note_number,
        SalesCreditNote.return_key,
        StockBalance.location_id,
        InventoryBranch.id,
        InventoryBranch.name,
        StockLocation.name,
        Product.id,
        Product.name,
        Product.sku,
        StockBalance.tracking_policy,
        StockBalance.batch_key,
        StockBalance.quarantined,
        StockBalance.version,
        transitioned.label("transitioned"),
        pending_quantity.label("pending"),
    ).order_by(SalesCreditNoteLine.id.desc()).offset((page - 1) * limit).limit(limit).all()
    items = []
    for line, number, return_key, location_id, branch_id, branch_name, location_name, product_id, product_name, product_sku, tracking, batch_key, quarantined, version, consumed, pending_value in rows:
        consumed = Decimal(consumed)
        pending_value = Decimal(pending_value)
        with localcontext(_CONTEXT):
            eligible = Decimal(line.quantity) - consumed - pending_value
        items.append({
            "credit_note_line_id": line.id,
            "credit_note_key": line.credit_note_key,
            "credit_note_number": number,
            "return_key": return_key,
            "return_operation_key": line.return_operation_key,
            "invoice_key": line.invoice_key,
            "invoice_line_key": line.invoice_line_key,
            "handover_allocation_key": line.handover_allocation_key,
            "branch_id": branch_id,
            "branch_name": branch_name,
            "location_id": location_id,
            "location_name": location_name,
            "product_id": product_id,
            "product_name": product_name,
            "product_sku": product_sku,
            "base_unit": line.base_unit,
            "tracking_policy": tracking,
            "batch_key": batch_key,
            "source_quantity": format(Decimal(line.quantity), ".6f"),
            "previously_transitioned": format(consumed, ".6f"),
            "pending_review_quantity": format(pending_value, ".6f"),
            "remaining_eligible": format(eligible, ".6f"),
            "quarantined_available": format(Decimal(quarantined), ".6f"),
            "stock_version": version,
        })
    return total, items


def load_return_condition_binding(db, context, credit_note_line_id, quantity, *,
                                  lock=True, exclude_case_key=None):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Stock-condition company denied")
    if type(credit_note_line_id) is not int or credit_note_line_id <= 0:
        raise ValueError("Positive return credit-line identity required")
    quantity = _exact_positive(quantity)
    line_query = _query(db, SalesCreditNoteLine, context).filter(
        SalesCreditNoteLine.id == credit_note_line_id)
    if lock:
        line_query = line_query.populate_existing().with_for_update()
    line = line_query.one_or_none()
    if line is None:
        raise LookupError("Return credit line not found")
    note = _query(db, SalesCreditNote, context).filter_by(
        credit_note_key=line.credit_note_key).one_or_none()
    allocation = _query(db, SalesReturnAllocation, context).filter_by(
        id=line.return_allocation_id).one_or_none()
    if note is None or allocation is None or (
        allocation.return_key != note.return_key
        or allocation.balance_id != line.balance_id
        or allocation.invoice_key != line.invoice_key
        or allocation.invoice_line_key != line.invoice_line_key
        or allocation.handover_allocation_key != line.handover_allocation_key
        or Decimal(allocation.quantity) != Decimal(line.quantity)
        or allocation.base_unit != line.base_unit
    ):
        raise PostingConflict("Return credit-line allocation lineage is incomplete")
    returned = _query(db, StockMovement, context).filter_by(
        balance_id=line.balance_id,
        operation_key=line.return_operation_key,
        kind="RETURN",
    ).one_or_none()
    return_total = _query(db, SalesCreditNoteLine, context).filter_by(
        balance_id=line.balance_id,
        return_operation_key=line.return_operation_key,
    ).with_entities(func.sum(SalesCreditNoteLine.quantity)).scalar()
    if returned is None or return_total is None or Decimal(returned.on_hand_delta) != Decimal(return_total):
        raise PostingConflict("Return stock lineage is incomplete")
    balance = _locked_balance(db, context, line.balance_id) if lock else _query(
        db, StockBalance, context).filter_by(id=line.balance_id).one_or_none()
    if balance is None:
        raise LookupError("Return stock balance not found")
    if balance.tracking_policy not in ("UNTRACKED", "BATCH"):
        raise ValueError("Serial stock requires exact serial-identity condition workflow")
    if balance.base_unit != line.base_unit:
        raise PostingConflict("Return stock unit no longer matches its credit line")
    convert_quantity(
        InventoryPolicyConfig.model_validate(balance.policy_config),
        quantity, balance.base_unit, allow_zero=False)
    before = _snapshot(balance)
    branch = _query(db, InventoryBranch, context).filter_by(
        id=balance.branch_id, is_active=True).one_or_none()
    location = _query(db, StockLocation, context).filter_by(
        id=balance.location_id, branch_id=balance.branch_id, is_active=True).one_or_none()
    product = _query(db, Product, context).filter_by(
        id=balance.product_id, status="active", is_shared=False).one_or_none()
    if branch is None or location is None or product is None:
        raise LookupError("Active return-stock scope not found")
    consumed = _consumed_quantity(db, context, line.id)
    pending = _pending_quantity(
        db, context, line.id, exclude_case_key=exclude_case_key)
    with localcontext(_CONTEXT):
        remaining = Decimal(line.quantity) - consumed - pending
        target_damaged = before.damaged + quantity
        target_quarantined = before.quarantined - quantity
    if remaining < quantity:
        raise PostingConflict("Condition transitions exceed the exact returned source quantity")
    if before.quarantined < quantity:
        raise PostingConflict("Condition transition exceeds current quarantined stock")
    QuantityBreakdown(before.on_hand, before.reserved, target_damaged, target_quarantined)
    return CaseBinding(
        org_id=context.org_id,
        action=ACTION,
        source_type=SOURCE_TYPE,
        source_key=str(line.id),
        source_version=balance.version,
        details={
            "credit_note_line_id": line.id,
            "credit_note_key": str(line.credit_note_key),
            "credit_note_number": note.credit_note_number,
            "return_key": str(note.return_key),
            "return_operation_key": str(line.return_operation_key),
            "invoice_key": str(line.invoice_key),
            "invoice_line_key": str(line.invoice_line_key),
            "handover_allocation_key": str(line.handover_allocation_key),
            "balance_id": balance.id,
            "branch_id": balance.branch_id,
            "branch_name": branch.name,
            "location_id": balance.location_id,
            "location_name": location.name,
            "product_id": balance.product_id,
            "product_name": product.name,
            "product_sku": product.sku,
            "base_unit": balance.base_unit,
            "tracking_policy": balance.tracking_policy,
            "batch_key": str(balance.batch_key) if balance.batch_key else None,
            "source_return_quantity": format(Decimal(line.quantity), ".6f"),
            "previously_transitioned": format(consumed, ".6f"),
            "pending_review_quantity": format(pending, ".6f"),
            "quantity": format(quantity, ".6f"),
            "from_condition": "QUARANTINED",
            "to_condition": "DAMAGED",
            "before_on_hand": format(before.on_hand, ".6f"),
            "before_reserved": format(before.reserved, ".6f"),
            "before_damaged": format(before.damaged, ".6f"),
            "before_quarantined": format(before.quarantined, ".6f"),
            "target_damaged": format(target_damaged, ".6f"),
            "target_quarantined": format(target_quarantined, ".6f"),
        },
    )


def reload_return_condition_binding(db, context, binding, *, replay_operation=None,
                                    current_case_key=None):
    details = binding.details
    if replay_operation is not None:
        movement = _query(db, StockMovement, context).filter_by(
            operation_key=replay_operation,
            balance_id=details["balance_id"],
            kind=MOVEMENT_KIND,
            version=binding.source_version + 1,
        ).one_or_none()
        if movement is not None and (
            format(movement.on_hand, ".6f") == details["before_on_hand"]
            and format(movement.reserved, ".6f") == details["before_reserved"]
            and format(movement.damaged, ".6f") == details["target_damaged"]
            and format(movement.quarantined, ".6f") == details["target_quarantined"]
        ):
            return binding
    current = load_return_condition_binding(
        db, context, details["credit_note_line_id"], Decimal(details["quantity"]),
        lock=True, exclude_case_key=current_case_key)
    if current.snapshot() != binding.snapshot():
        raise PostingConflict("Return stock or exact source cap changed")
    return current
