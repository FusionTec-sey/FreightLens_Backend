"""Reviewed, cumulative customer returns and immutable credit notes."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, localcontext, Context
from hashlib import sha256
import json
from math import ceil
from uuid import UUID, uuid5

from sqlalchemy import func

from Model.containermgmt.Inventory.CostPool import BranchCostPool
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.ManagerCase import (
    ManagerCase,
    ManagerCaseDecision,
    ManagerCaseUse,
)
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.SalesCollection import (
    SalesCollection,
    SalesCollectionAllocation,
)
from Model.containermgmt.Orders.SalesPosting import (
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoicePayment,
)
from Model.containermgmt.Orders.SalesReturn import (
    CustomerCreditLiabilityEntry,
    SalesCreditNote,
    SalesCreditNoteLine,
    SalesInvoiceDebtApplication,
    SalesReturnAllocation,
    SalesReturnClaim,
)
from Schema.SalesReturnSchema import (
    SalesCreditNoteRead,
    SalesReturnClaimCreate,
    SalesReturnClaimRead,
    SalesReturnCreditNoteCreate,
    SalesReturnReview,
)
from Services.inventory_posting_service import (
    PostingConflict,
    PostingEffect,
    execute_once,
)
from Services.inventory_return_movement_service import return_handed_over_stock
from Services.sales_posting_service import read_invoice
from Services.manager_case_service import (
    CaseBinding,
    consume_case,
    request_case,
    review_case,
)
from Services.posting_authority_service import AuthorityClaim, CostPoolAuthorityClaim
from Utils.org_filter import apply_org_filter


ZERO_QTY = Decimal("0.000000")
ZERO_MONEY = Decimal("0.00")
MONEY_QUANTUM = Decimal("0.01")
ACTION = "sales.return.claim"
SOURCE = "sales.return"


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id,
        model.is_deleted.is_(False),
    ), model, context)


def _guard(context, authorize, db):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Return company scope denied")
    if not callable(authorize):
        raise ValueError("Return authorization guard required")
    authorize(db)


def _quantity(value):
    return format(Decimal(value), ".6f")


def _money(value):
    return format(Decimal(value), ".2f")


def _customer_name(invoice):
    name = invoice.customer_snapshot.get("name") if invoice.customer_snapshot else None
    return name.strip() if isinstance(name, str) and name.strip() else "Customer"


def _case_rows(db, context, return_key):
    case = _owned(db, ManagerCase, context).filter_by(
        case_key=return_key, action=ACTION, source_type=SOURCE,
    ).one_or_none()
    decision = (_owned(db, ManagerCaseDecision, context).filter_by(
        case_id=case.id).one_or_none() if case else None)
    used = (_owned(db, ManagerCaseUse, context).filter_by(
        case_id=case.id).one_or_none() if case else None)
    return case, decision, used


def _claim_status(db, context, claim):
    case, decision, used = _case_rows(db, context, claim.return_key)
    credit = _owned(db, SalesCreditNote, context).filter_by(
        return_key=claim.return_key).one_or_none()
    if credit is not None:
        return "CREDITED", 3, case, decision, used
    if decision is not None:
        return decision.outcome, 2, case, decision, used
    return "REQUESTED", 1, case, decision, used


def _estimated_gross(db, context, allocations):
    total = ZERO_MONEY
    lines = {line.line_key: line for line in _owned(
        db, SalesInvoiceLine, context,
    ).filter(SalesInvoiceLine.line_key.in_(
        [row.invoice_line_key for row in allocations]
    )).all()}
    for allocation in allocations:
        line = lines[allocation.invoice_line_key]
        with localcontext(Context(prec=48)):
            total += (Decimal(line.gross_total_scr) * Decimal(allocation.quantity)
                      / Decimal(line.base_quantity)).quantize(
                          MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    return total


def _claim_read(db, context, claim):
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=claim.invoice_key).one()
    allocations = _owned(db, SalesReturnAllocation, context).filter_by(
        return_key=claim.return_key).order_by(SalesReturnAllocation.id).all()
    invoice_lines = {line.line_key: line for line in _owned(
        db, SalesInvoiceLine, context,
    ).filter(SalesInvoiceLine.line_key.in_(
        [row.invoice_line_key for row in allocations]
    )).all()}
    status, version, case, decision, _ = _claim_status(db, context, claim)
    if case is None:
        raise PostingConflict("Return review case is unavailable")
    if status == "CREDITED":
        estimated_gross = Decimal(_owned(db, SalesCreditNote, context).filter_by(
            return_key=claim.return_key).with_entities(
                SalesCreditNote.gross_credit_scr).scalar())
    elif status in ("REQUESTED", "APPROVED"):
        estimated_gross = sum((row["gross"] for row in _money_plan(
            db, context, claim, allocations, invoice_lines).values()), ZERO_MONEY)
    else:
        estimated_gross = _estimated_gross(db, context, allocations)
    return dict(
        return_key=claim.return_key,
        operation_key=claim.operation_key,
        invoice_key=claim.invoice_key,
        invoice_number=invoice.invoice_number,
        branch_id=claim.branch_id,
        customer_key=claim.customer_key,
        returner_name=claim.returner_name,
        returner_contact=claim.returner_contact,
        reason=claim.reason,
        status=status,
        version=version,
        requested_by=claim.created_by,
        requested_at=claim.requested_at,
        review=dict(
            case_key=case.case_key,
            outcome=decision.outcome if decision else None,
            reviewer_id=decision.created_by if decision else None,
            reason=decision.reason if decision else None,
            reviewed_at=decision.created_at if decision else None,
        ),
        estimated_gross_credit_scr=_money(estimated_gross),
        lines=[dict(
            invoice_line_key=row.invoice_line_key,
            handover_allocation_key=row.handover_allocation_key,
            product_id=invoice_lines[row.invoice_line_key].product_id,
            product_name=invoice_lines[row.invoice_line_key].product_name,
            sku=invoice_lines[row.invoice_line_key].sku,
            balance_id=row.balance_id,
            location_id=row.location_id,
            batch_key=row.batch_key,
            quantity=_quantity(row.quantity),
            base_unit=row.base_unit,
            condition=row.condition,
        ) for row in allocations],
    )


def read_return_claim(db, context, return_key, *, authorize):
    _guard(context, authorize, db)
    claim = _owned(db, SalesReturnClaim, context).filter_by(
        return_key=UUID(str(return_key))).one_or_none()
    if claim is None:
        raise LookupError("Return claim not found")
    return _claim_read(db, context, claim)


def list_invoice_returns(db, context, invoice_key, *, page, limit, authorize):
    _guard(context, authorize, db)
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=UUID(str(invoice_key))).one_or_none()
    if invoice is None:
        raise LookupError("Sales invoice not found")
    query = _owned(db, SalesReturnClaim, context).filter_by(
        invoice_key=invoice.invoice_key)
    total = query.count()
    rows = query.order_by(SalesReturnClaim.requested_at.desc()).offset(
        (page - 1) * limit).limit(limit).all()
    return dict(items=[_claim_read(db, context, row) for row in rows],
                total=total, page=page, pages=max(1, ceil(total / limit)), limit=limit)


def _active_claim_totals(db, context, *, invoice_key):
    rows = _owned(db, SalesReturnAllocation, context).join(
        SalesReturnClaim,
        (SalesReturnClaim.return_key == SalesReturnAllocation.return_key)
        & (SalesReturnClaim.org_id == SalesReturnAllocation.org_id),
    ).join(
        ManagerCase,
        (ManagerCase.case_key == SalesReturnClaim.return_key)
        & (ManagerCase.org_id == SalesReturnClaim.org_id),
    ).outerjoin(
        ManagerCaseDecision,
        (ManagerCaseDecision.case_id == ManagerCase.id)
        & (ManagerCaseDecision.org_id == ManagerCase.org_id),
    ).outerjoin(
        SalesCreditNote,
        (SalesCreditNote.return_key == SalesReturnClaim.return_key)
        & (SalesCreditNote.org_id == SalesReturnClaim.org_id),
    ).filter(
        SalesReturnAllocation.invoice_key == invoice_key,
        (ManagerCaseDecision.id.is_(None))
        | (ManagerCaseDecision.outcome == "APPROVED"),
    ).with_entities(
        SalesReturnAllocation.handover_allocation_key,
        SalesReturnAllocation.invoice_line_key,
        SalesReturnAllocation.quantity,
        SalesCreditNote.credit_note_key,
    ).all()
    by_handover = defaultdict(lambda: {"accepted": ZERO_QTY, "pending": ZERO_QTY})
    by_line = defaultdict(lambda: {"accepted": ZERO_QTY, "pending": ZERO_QTY})
    for row in rows:
        bucket = "accepted" if row.credit_note_key is not None else "pending"
        quantity = Decimal(row.quantity)
        by_handover[row.handover_allocation_key][bucket] += quantity
        by_line[row.invoice_line_key][bucket] += quantity
    return by_handover, by_line


def read_return_options(db, context, invoice_key, *, authorize):
    _guard(context, authorize, db)
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=UUID(str(invoice_key))).one_or_none()
    if invoice is None:
        raise LookupError("Sales invoice not found")
    branch = _owned(db, InventoryBranch, context).filter_by(
        id=invoice.branch_id).one_or_none()
    if branch is None:
        raise PostingConflict("Invoice branch is unavailable")
    lines = _owned(db, SalesInvoiceLine, context).filter_by(
        invoice_key=invoice.invoice_key).order_by(SalesInvoiceLine.position).all()
    handovers = _owned(db, SalesCollectionAllocation, context).join(
        SalesCollection,
        (SalesCollection.collection_key == SalesCollectionAllocation.collection_key)
        & (SalesCollection.org_id == SalesCollectionAllocation.org_id),
    ).filter(
        SalesCollectionAllocation.invoice_key == invoice.invoice_key,
    ).order_by(
        SalesCollection.collected_at, SalesCollectionAllocation.id,
    ).with_entities(SalesCollectionAllocation, SalesCollection).all()
    active_handover, active_line = _active_claim_totals(
        db, context, invoice_key=invoice.invoice_key)
    handed_by_line = defaultdict(lambda: ZERO_QTY)
    options = []
    for handed, collection in handovers:
        balance = _owned(db, StockBalance, context).filter_by(
            id=handed.balance_id).one()
        if balance.tracking_policy == "SERIAL":
            continue
        location = _owned(db, StockLocation, context).filter_by(
            id=handed.location_id).one()
        batch = (_owned(db, StockBatch, context).filter_by(
            batch_key=handed.batch_key).one_or_none() if handed.batch_key else None)
        totals = active_handover[handed.handover_operation_key]
        handed_quantity = Decimal(handed.quantity)
        handed_by_line[handed.line_key] += handed_quantity
        remaining = handed_quantity - totals["accepted"] - totals["pending"]
        options.append(dict(
            handover_allocation_key=handed.handover_operation_key,
            collection_key=handed.collection_key,
            invoice_line_key=handed.line_key,
            balance_id=handed.balance_id,
            location_id=handed.location_id,
            location_code=location.code,
            location_name=location.name,
            batch_key=handed.batch_key,
            batch_code=batch.code if batch else None,
            shade=batch.shade if batch else None,
            calibre=batch.calibre if batch else None,
            base_unit=handed.base_unit,
            handed_over=_quantity(handed_quantity),
            accepted_returned=_quantity(totals["accepted"]),
            pending_return=_quantity(totals["pending"]),
            returnable=_quantity(remaining),
            collected_at=collection.collected_at,
        ))
    return dict(
        invoice_key=invoice.invoice_key,
        invoice_number=invoice.invoice_number,
        invoice_version=1,
        customer_key=invoice.customer_key,
        customer_name=_customer_name(invoice),
        branch_id=invoice.branch_id,
        branch_name=branch.name,
        lines=[dict(
            invoice_line_key=line.line_key,
            product_id=line.product_id,
            product_name=line.product_name,
            sku=line.sku,
            base_unit=line.base_unit,
            handed_over=_quantity(handed_by_line[line.line_key]),
            accepted_returned=_quantity(active_line[line.line_key]["accepted"]),
            pending_return=_quantity(active_line[line.line_key]["pending"]),
            returnable=_quantity(
                handed_by_line[line.line_key]
                - active_line[line.line_key]["accepted"]
                - active_line[line.line_key]["pending"]),
        ) for line in lines],
        handovers=options,
    )


def read_posted_invoice_for_draft(db, context, document_key, draft_version, *, authorize):
    """Narrow View_Sale lookup without checkout/posting authority or account data."""
    _guard(context, authorize, db)
    if type(draft_version) is not int or draft_version <= 0:
        raise ValueError("Positive exact draft version required")
    invoice = _owned(db, SalesInvoice, context).filter_by(
        document_key=UUID(str(document_key)),
        draft_version=draft_version,
    ).one_or_none()
    if invoice is None:
        raise LookupError("Posted sales invoice not found for this draft revision")
    return read_invoice(
        db, context, invoice.invoice_key, authorize=authorize)


def return_binding(db, context, return_key, *, authorize, lock=True):
    _guard(context, authorize, db)
    query = _owned(db, SalesReturnClaim, context).filter_by(return_key=return_key)
    claim = query.with_for_update().one_or_none() if lock else query.one_or_none()
    if claim is None:
        raise LookupError("Return claim not found")
    allocations = _owned(db, SalesReturnAllocation, context).filter_by(
        return_key=claim.return_key).order_by(
            SalesReturnAllocation.handover_allocation_key,
    ).all()
    details = {
        "return_key": str(claim.return_key),
        "invoice_key": str(claim.invoice_key),
        "invoice_version": claim.invoice_version,
        "branch_id": claim.branch_id,
        "customer_key": str(claim.customer_key),
        "returner_name": claim.returner_name,
        "returner_contact": claim.returner_contact,
        "requestor_id": claim.created_by,
        "lines": [{
            "invoice_line_key": str(row.invoice_line_key),
            "handover_allocation_key": str(row.handover_allocation_key),
            "collection_key": str(row.collection_key),
            "balance_id": row.balance_id,
            "location_id": row.location_id,
            "batch_key": str(row.batch_key) if row.batch_key else None,
            "quantity": _quantity(row.quantity),
            "base_unit": row.base_unit,
            "condition": row.condition,
        } for row in allocations],
    }
    return CaseBinding(context.org_id, ACTION, SOURCE, str(claim.return_key), 1, details)


def request_return_claim(factory, context, actor_id, payload, *, authorize):
    if not isinstance(payload, SalesReturnClaimCreate):
        raise ValueError("Typed return claim request required")
    request = payload.model_dump(mode="json")

    def guard(db):
        _guard(context, authorize, db)
        invoice = _owned(db, SalesInvoice, context).filter_by(
            invoice_key=payload.invoice_key).one_or_none()
        if invoice is None:
            raise LookupError("Sales invoice not found")

    def apply(db):
        invoice = _owned(db, SalesInvoice, context).filter_by(
            invoice_key=payload.invoice_key).with_for_update().one_or_none()
        if invoice is None:
            raise LookupError("Sales invoice not found")
        if payload.expected_invoice_version != 1:
            raise PostingConflict("Invoice version changed")
        keys = sorted((line.handover_allocation_key for line in payload.lines), key=str)
        handed_rows = _owned(db, SalesCollectionAllocation, context).filter(
            SalesCollectionAllocation.handover_operation_key.in_(keys),
        ).order_by(SalesCollectionAllocation.handover_operation_key).with_for_update().all()
        handed = {row.handover_operation_key: row for row in handed_rows}
        if len(handed) != len(keys):
            raise PostingConflict("One or more handover allocations are unavailable")
        invoice_line_keys = sorted({line.invoice_line_key for line in payload.lines}, key=str)
        invoice_line_rows = _owned(db, SalesInvoiceLine, context).filter(
            SalesInvoiceLine.invoice_key == invoice.invoice_key,
            SalesInvoiceLine.line_key.in_(invoice_line_keys),
        ).order_by(SalesInvoiceLine.line_key).with_for_update().all()
        if len(invoice_line_rows) != len(invoice_line_keys):
            raise PostingConflict("One or more invoice lines are unavailable")
        invoice_line_map = {line.line_key: line for line in invoice_line_rows}
        claim = SalesReturnClaim(
            org_id=context.org_id,
            return_key=payload.return_key,
            operation_key=payload.operation_key,
            invoice_key=invoice.invoice_key,
            invoice_version=1,
            branch_id=invoice.branch_id,
            customer_key=invoice.customer_key,
            returner_name=payload.returner_name,
            returner_contact=payload.returner_contact,
            reason=payload.reason,
            created_by=actor_id,
        )
        db.add(claim)
        db.flush()
        created_allocations = []
        for item in sorted(payload.lines, key=lambda row: str(row.handover_allocation_key)):
            source = handed[item.handover_allocation_key]
            if (source.invoice_key != invoice.invoice_key
                    or source.line_key != item.invoice_line_key):
                raise PostingConflict("Return line does not match the exact invoice handover")
            balance = _owned(db, StockBalance, context).filter_by(
                id=source.balance_id).one_or_none()
            collection = _owned(db, SalesCollection, context).filter_by(
                collection_key=source.collection_key).one_or_none()
            if balance is None or collection is None:
                raise PostingConflict("Handover stock scope is unavailable")
            if balance.branch_id != invoice.branch_id or collection.branch_id != invoice.branch_id:
                raise PermissionError("Cross-store returns are not supported in this pilot")
            if balance.tracking_policy == "SERIAL":
                raise PostingConflict("Serial returns require exact serial history")
            existing = _owned(db, SalesReturnAllocation, context).join(
                SalesReturnClaim,
                (SalesReturnClaim.return_key == SalesReturnAllocation.return_key)
                & (SalesReturnClaim.org_id == SalesReturnAllocation.org_id),
            ).join(
                ManagerCase,
                (ManagerCase.case_key == SalesReturnClaim.return_key)
                & (ManagerCase.org_id == SalesReturnClaim.org_id),
            ).outerjoin(
                ManagerCaseDecision,
                (ManagerCaseDecision.case_id == ManagerCase.id)
                & (ManagerCaseDecision.org_id == ManagerCase.org_id),
            ).filter(
                SalesReturnAllocation.handover_allocation_key
                == item.handover_allocation_key,
                (ManagerCaseDecision.id.is_(None))
                | (ManagerCaseDecision.outcome == "APPROVED"),
            ).with_entities(func.coalesce(func.sum(SalesReturnAllocation.quantity), 0)).scalar()
            if Decimal(existing) + Decimal(item.quantity) > Decimal(source.quantity):
                raise PostingConflict("Pending and accepted returns exceed this handover")
            allocation = SalesReturnAllocation(
                org_id=context.org_id,
                return_key=claim.return_key,
                invoice_key=invoice.invoice_key,
                invoice_line_key=item.invoice_line_key,
                handover_allocation_key=item.handover_allocation_key,
                collection_key=source.collection_key,
                balance_id=source.balance_id,
                location_id=source.location_id,
                batch_key=source.batch_key,
                quantity=Decimal(item.quantity),
                base_unit=source.base_unit,
                condition=item.condition,
                created_by=actor_id,
            )
            db.add(allocation)
            created_allocations.append(allocation)
        db.flush()
        _money_plan(db, context, claim, created_allocations, invoice_line_map)
        binding = return_binding(db, context, claim.return_key,
                                 authorize=authorize, lock=True)
        request_case(
            db, context, actor_id, claim.return_key,
            binding=binding,
            reason=payload.reason,
            load_binding=lambda session: return_binding(
                session, context, claim.return_key, authorize=authorize, lock=True),
            authorize=authorize,
        )
        result = SalesReturnClaimRead.model_validate(
            _claim_read(db, context, claim)).model_dump(mode="json")
        return PostingEffect(result, {
            "kind": "sales.return.requested",
            "return_key": str(claim.return_key),
            "invoice_key": str(invoice.invoice_key),
            "branch_id": invoice.branch_id,
            "line_count": len(payload.lines),
        })

    return execute_once(factory, context, actor_id, payload.operation_key,
                        "sales.return.request.v1", request, apply, authorize=guard)


def review_return_claim(factory, context, actor_id, return_key, payload, *, authorize):
    if not isinstance(payload, SalesReturnReview):
        raise ValueError("Typed return review required")
    return_key = UUID(str(return_key))
    binding = None
    if hasattr(factory, "query"):
        binding = return_binding(factory, context, return_key,
                                 authorize=authorize, lock=False)
    else:
        with factory() as db:
            binding = return_binding(db, context, return_key,
                                     authorize=authorize, lock=False)
    outcome = review_case(
        factory, context, actor_id, payload.operation_key,
        case_key=return_key,
        binding=binding,
        expected_version=payload.expected_version,
        outcome=payload.outcome,
        reason=payload.reason,
        load_binding=lambda session: return_binding(
            session, context, return_key, authorize=authorize, lock=True),
        authorize=authorize,
    )
    if hasattr(factory, "query"):
        claim = _owned(factory, SalesReturnClaim, context).filter_by(
            return_key=return_key).one()
        read = _claim_read(factory, context, claim)
    else:
        with factory() as db:
            claim = _owned(db, SalesReturnClaim, context).filter_by(
                return_key=return_key).one()
            read = _claim_read(db, context, claim)
    return dict(claim=read, replayed=outcome.replayed)


def _cumulative_money(total, cumulative_quantity, line_quantity):
    if cumulative_quantity == line_quantity:
        return Decimal(total).quantize(MONEY_QUANTUM)
    with localcontext(Context(prec=48)):
        return (Decimal(total) * cumulative_quantity / line_quantity).quantize(
            MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _money_plan(db, context, claim, allocations, invoice_lines):
    grouped = defaultdict(list)
    for row in allocations:
        grouped[row.invoice_line_key].append(row)
    plan = {}
    for line_key in sorted(grouped, key=str):
        line = invoice_lines.get(line_key)
        if line is None:
            raise PostingConflict("Return invoice line is unavailable")
        prior_quantity, prior_net, prior_tax = _owned(
            db, SalesCreditNoteLine, context,
        ).filter_by(invoice_key=claim.invoice_key, invoice_line_key=line_key).with_entities(
            func.coalesce(func.sum(SalesCreditNoteLine.quantity), 0),
            func.coalesce(func.sum(SalesCreditNoteLine.net_credit_scr), 0),
            func.coalesce(func.sum(SalesCreditNoteLine.tax_credit_scr), 0),
        ).one()
        prior_quantity = Decimal(prior_quantity)
        current_quantity = sum((Decimal(row.quantity) for row in grouped[line_key]), ZERO_QTY)
        cumulative_quantity = prior_quantity + current_quantity
        if cumulative_quantity > Decimal(line.base_quantity):
            raise PostingConflict("Cumulative return exceeds the original invoice line")
        target_net = _cumulative_money(
            line.net_total_scr, cumulative_quantity, Decimal(line.base_quantity))
        target_tax = _cumulative_money(
            line.tax_total_scr, cumulative_quantity, Decimal(line.base_quantity))
        current_net = target_net - Decimal(prior_net)
        current_tax = target_tax - Decimal(prior_tax)
        running_quantity = ZERO_QTY
        allocated_net = ZERO_MONEY
        allocated_tax = ZERO_MONEY
        rows = sorted(grouped[line_key], key=lambda row: row.id)
        for index, row in enumerate(rows):
            running_quantity += Decimal(row.quantity)
            if index == len(rows) - 1:
                row_net = current_net - allocated_net
                row_tax = current_tax - allocated_tax
            else:
                row_net_target = _cumulative_money(
                    current_net, running_quantity, current_quantity)
                row_tax_target = _cumulative_money(
                    current_tax, running_quantity, current_quantity)
                row_net = row_net_target - allocated_net
                row_tax = row_tax_target - allocated_tax
            allocated_net += row_net
            allocated_tax += row_tax
            plan[row.id] = dict(net=row_net, tax=row_tax, gross=row_net + row_tax)
    return plan


def _processing_snapshot(db, context, return_key, *, authorize, lock=False):
    _guard(context, authorize, db)
    query = _owned(db, SalesReturnClaim, context).filter_by(return_key=return_key)
    claim = query.with_for_update().one_or_none() if lock else query.one_or_none()
    if claim is None:
        raise LookupError("Return claim not found")
    status, version, _, decision, _ = _claim_status(db, context, claim)
    if status != "APPROVED" or version != 2 or decision is None:
        raise PostingConflict("Return must have an unused approved manager review")
    allocations = _owned(db, SalesReturnAllocation, context).filter_by(
        return_key=claim.return_key).order_by(
            SalesReturnAllocation.balance_id,
            SalesReturnAllocation.id,
        ).all()
    invoice_query = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=claim.invoice_key)
    invoice = (invoice_query.with_for_update().one()
               if lock else invoice_query.one())
    line_keys = sorted({row.invoice_line_key for row in allocations}, key=str)
    line_query = _owned(db, SalesInvoiceLine, context).filter(
        SalesInvoiceLine.invoice_key == claim.invoice_key,
        SalesInvoiceLine.line_key.in_(line_keys),
    ).order_by(SalesInvoiceLine.line_key)
    invoice_lines = (line_query.with_for_update().all()
                     if lock else line_query.all())
    if len(invoice_lines) != len(line_keys):
        raise PostingConflict("Return invoice lines are unavailable")
    money_plan = _money_plan(
        db, context, claim, allocations,
        {line.line_key: line for line in invoice_lines},
    )
    balance_rows = {}
    details = []
    for allocation in allocations:
        balance = _owned(db, StockBalance, context).filter_by(
            id=allocation.balance_id).one()
        if balance.branch_id != claim.branch_id:
            raise PermissionError("Cross-store return processing is denied")
        if balance.tracking_policy == "SERIAL":
            raise PostingConflict("Serial returns require exact serial history")
        mapping = _owned(db, BranchCostPool, context).filter_by(
            branch_id=balance.branch_id).one_or_none()
        if mapping is None:
            raise PostingConflict("Return store has no exact cost pool")
        latest = _owned(db, InventoryValuation, context).filter_by(
            cost_pool_id=mapping.cost_pool_id,
            product_id=balance.product_id,
        ).order_by(InventoryValuation.version.desc()).first()
        if latest is None:
            raise PostingConflict("Returned stock requires current valuation")
        balance_rows[balance.id] = dict(
            balance_id=balance.id,
            expected_stock_version=balance.version,
            expected_valuation_version=latest.version,
        )
        details.append(dict(
            allocation_id=allocation.id,
            handover_allocation_key=str(allocation.handover_allocation_key),
            balance_id=balance.id,
            quantity=_quantity(allocation.quantity),
            stock_version=balance.version,
            cost_pool_id=mapping.cost_pool_id,
            valuation_version=latest.version,
            gross_credit_scr=_money(money_plan[allocation.id]["gross"]),
            net_credit_scr=_money(money_plan[allocation.id]["net"]),
            tax_credit_scr=_money(money_plan[allocation.id]["tax"]),
        ))
    gross = sum((row["gross"] for row in money_plan.values()), ZERO_MONEY)
    net = sum((row["net"] for row in money_plan.values()), ZERO_MONEY)
    tax = sum((row["tax"] for row in money_plan.values()), ZERO_MONEY)
    paid = _owned(db, SalesInvoicePayment, context).filter_by(
        invoice_key=claim.invoice_key).with_entities(
            func.coalesce(func.sum(SalesInvoicePayment.amount_scr), 0)).scalar()
    prior_debt = _owned(db, SalesInvoiceDebtApplication, context).filter_by(
        invoice_key=claim.invoice_key).with_entities(
            func.coalesce(func.sum(SalesInvoiceDebtApplication.amount_scr), 0)).scalar()
    outstanding = max(Decimal(invoice.gross_total_scr) - Decimal(paid)
                      - Decimal(prior_debt), ZERO_MONEY)
    debt = min(gross, outstanding)
    credit = gross - debt
    canonical = dict(
        return_key=str(claim.return_key),
        claim_version=2,
        decision_id=decision.id,
        branch_id=claim.branch_id,
        gross_credit_scr=_money(gross),
        net_credit_scr=_money(net),
        tax_credit_scr=_money(tax),
        invoice_debt_applied_scr=_money(debt),
        customer_credit_scr=_money(credit),
        allocations=details,
    )
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    fingerprint = sha256(encoded.encode()).hexdigest()
    return dict(
        return_key=claim.return_key,
        claim_version=2,
        option_version=1,
        fingerprint=fingerprint,
        branch_id=claim.branch_id,
        gross_credit_scr=_money(gross),
        net_credit_scr=_money(net),
        tax_credit_scr=_money(tax),
        invoice_debt_applied_scr=_money(debt),
        customer_credit_scr=_money(credit),
        balances=[balance_rows[key] for key in sorted(balance_rows)],
        _claim=claim,
        _invoice=invoice,
        _allocations=allocations,
        _money_plan=money_plan,
        _details=details,
    )


def read_return_processing_options(db, context, return_key, *, authorize):
    snapshot = _processing_snapshot(
        db, context, UUID(str(return_key)), authorize=authorize)
    return {key: value for key, value in snapshot.items() if not key.startswith("_")}


def _credit_read(db, context, credit):
    lines = _owned(db, SalesCreditNoteLine, context).filter_by(
        credit_note_key=credit.credit_note_key).order_by(
            SalesCreditNoteLine.id).all()
    debt = _owned(db, SalesInvoiceDebtApplication, context).filter_by(
        credit_note_key=credit.credit_note_key).with_entities(
            func.coalesce(func.sum(SalesInvoiceDebtApplication.amount_scr), 0)).scalar()
    customer_credit = _owned(db, CustomerCreditLiabilityEntry, context).filter_by(
        credit_note_key=credit.credit_note_key).with_entities(
            func.coalesce(func.sum(CustomerCreditLiabilityEntry.amount_scr), 0)).scalar()
    return dict(
        credit_note_key=credit.credit_note_key,
        credit_note_number=credit.credit_note_number,
        return_key=credit.return_key,
        invoice_key=credit.invoice_key,
        invoice_number=credit.invoice_number,
        branch_id=credit.branch_id,
        customer_key=credit.customer_key,
        currency=credit.currency,
        gross_credit_scr=_money(credit.gross_credit_scr),
        net_credit_scr=_money(credit.net_credit_scr),
        tax_credit_scr=_money(credit.tax_credit_scr),
        invoice_debt_applied_scr=_money(debt),
        customer_credit_scr=_money(customer_credit),
        issued_at=credit.issued_at,
        issued_by=credit.created_by,
        lines=[dict(
            invoice_line_key=line.invoice_line_key,
            handover_allocation_key=line.handover_allocation_key,
            quantity=_quantity(line.quantity),
            base_unit=line.base_unit,
            gross_credit_scr=_money(line.gross_credit_scr),
            net_credit_scr=_money(line.net_credit_scr),
            tax_credit_scr=_money(line.tax_credit_scr),
        ) for line in lines],
    )


def _credit_effect_snapshot(value):
    """Return the immutable credit-note result in operation-safe JSON form."""
    return SalesCreditNoteRead.model_validate(value).model_dump(mode="json")


def read_credit_note(db, context, credit_note_key, *, authorize):
    _guard(context, authorize, db)
    credit = _owned(db, SalesCreditNote, context).filter_by(
        credit_note_key=UUID(str(credit_note_key))).one_or_none()
    if credit is None:
        raise LookupError("Sales credit note not found")
    return _credit_read(db, context, credit)


def list_invoice_credit_notes(db, context, invoice_key, *, page, limit, authorize):
    _guard(context, authorize, db)
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=UUID(str(invoice_key))).one_or_none()
    if invoice is None:
        raise LookupError("Sales invoice not found")
    query = _owned(db, SalesCreditNote, context).filter_by(
        invoice_key=invoice.invoice_key)
    total = query.count()
    rows = query.order_by(SalesCreditNote.issued_at.desc()).offset(
        (page - 1) * limit).limit(limit).all()
    return dict(items=[_credit_read(db, context, row) for row in rows],
                total=total, page=page, pages=max(1, ceil(total / limit)), limit=limit)


def read_return_credit_note(db, context, return_key, *, authorize):
    _guard(context, authorize, db)
    credit = _owned(db, SalesCreditNote, context).filter_by(
        return_key=UUID(str(return_key))).one_or_none()
    if credit is None:
        raise LookupError("Return has no credit note")
    return _credit_read(db, context, credit)


def process_return_credit(factory, context, actor_id, return_key, payload, *,
        stock_authority, cost_authority, authorize):
    if not isinstance(payload, SalesReturnCreditNoteCreate):
        raise ValueError("Typed return processing request required")
    if not isinstance(stock_authority, AuthorityClaim):
        raise PermissionError("Trusted return-store authority required")
    if not isinstance(cost_authority, CostPoolAuthorityClaim):
        raise PermissionError("Trusted return valuation authority required")
    return_key = UUID(str(return_key))
    request = payload.model_dump(mode="json") | {
        "return_key": str(return_key),
        "stock_authority": {
            "org_id": stock_authority.org_id,
            "branch_id": stock_authority.branch_id,
            "node_key": str(stock_authority.node_key),
            "epoch": stock_authority.epoch,
        },
        "cost_authority": {
            "org_id": cost_authority.org_id,
            "cost_pool_id": cost_authority.cost_pool_id,
            "node_key": str(cost_authority.node_key),
            "epoch": cost_authority.epoch,
        },
    }
    scope = {}

    def guard(db):
        _guard(context, authorize, db)
        claim = _owned(db, SalesReturnClaim, context).filter_by(
            return_key=return_key).one_or_none()
        if claim is None:
            raise LookupError("Return claim not found")
        if (stock_authority.org_id != context.org_id
                or stock_authority.branch_id != claim.branch_id
                or cost_authority.org_id != context.org_id):
            raise PermissionError("Return runtime authority does not own this scope")
        existing = _owned(db, SalesCreditNote, context).filter_by(
            return_key=return_key).one_or_none()
        if existing is not None:
            if (existing.operation_key != payload.operation_key
                    or existing.processing_fingerprint != payload.expected_fingerprint):
                raise PostingConflict("Return already has a different credit note")
            scope["existing"] = existing
            return
        snapshot = _processing_snapshot(
            db, context, return_key, authorize=authorize, lock=False)
        if (payload.expected_claim_version != snapshot["claim_version"]
                or payload.expected_option_version != snapshot["option_version"]
                or payload.expected_fingerprint != snapshot["fingerprint"]):
            raise PostingConflict("Return processing options changed; reload before posting")
        mappings = _owned(db, BranchCostPool, context).filter_by(
            branch_id=claim.branch_id).one_or_none()
        if mappings is None or mappings.cost_pool_id != cost_authority.cost_pool_id:
            raise PermissionError("Return store has no exact cost authority")
        scope["snapshot"] = snapshot

    def apply(db):
        snapshot = _processing_snapshot(
            db, context, return_key, authorize=authorize, lock=True)
        if snapshot["fingerprint"] != payload.expected_fingerprint:
            raise PostingConflict("Return processing options changed; reload before posting")
        claim = snapshot["_claim"]
        invoice = snapshot["_invoice"]
        allocations = snapshot["_allocations"]
        binding = return_binding(
            db, context, return_key, authorize=authorize, lock=True)
        consume_case(
            db, context, actor_id, payload.operation_key,
            case_key=return_key,
            binding=binding,
            load_binding=lambda session: return_binding(
                session, context, return_key, authorize=authorize, lock=True),
            authorize=authorize,
        )

        starting = {row["balance_id"]: row for row in snapshot["balances"]}
        stock_offsets = defaultdict(int)
        valuation_offsets = defaultdict(int)
        outcomes = {}
        detail_by_id = {row["allocation_id"]: row for row in snapshot["_details"]}
        for allocation in allocations:
            detail = detail_by_id[allocation.id]
            pool_product = (detail["cost_pool_id"],
                            _owned(db, StockBalance, context).filter_by(
                                id=allocation.balance_id).with_entities(
                                    StockBalance.product_id).scalar())
            movement_key = uuid5(
                payload.operation_key,
                f"return:{allocation.id}:{allocation.handover_allocation_key}",
            )
            outcome = return_handed_over_stock(
                db, context, actor_id, movement_key,
                balance_id=allocation.balance_id,
                handover_operation_key=allocation.handover_allocation_key,
                quantity=Decimal(allocation.quantity),
                expected_stock_version=(
                    starting[allocation.balance_id]["expected_stock_version"]
                    + stock_offsets[allocation.balance_id]),
                expected_valuation_version=(
                    detail["valuation_version"] + valuation_offsets[pool_product]),
                reason=f"Return {return_key}",
                stock_authority=stock_authority,
                cost_authority=cost_authority,
                authorize_stock=authorize,
                authorize_financial=authorize,
            )
            outcomes[allocation.id] = (movement_key, outcome.result)
            stock_offsets[allocation.balance_id] += 1
            valuation_offsets[pool_product] += 1

        credit_key = uuid5(return_key, "credit-note")
        credit = SalesCreditNote(
            org_id=context.org_id,
            credit_note_key=credit_key,
            credit_note_number=(
                f"CN-{invoice.branch_id:04d}-{invoice.business_date:%Y%m%d}-"
                f"{return_key.hex[:12].upper()}"),
            return_key=return_key,
            operation_key=payload.operation_key,
            processing_fingerprint=snapshot["fingerprint"],
            invoice_key=invoice.invoice_key,
            invoice_number=invoice.invoice_number,
            branch_id=invoice.branch_id,
            customer_key=invoice.customer_key,
            currency="SCR",
            gross_credit_scr=Decimal(snapshot["gross_credit_scr"]),
            net_credit_scr=Decimal(snapshot["net_credit_scr"]),
            tax_credit_scr=Decimal(snapshot["tax_credit_scr"]),
            created_by=actor_id,
        )
        db.add(credit)
        db.flush()
        for allocation in allocations:
            movement_key, outcome = outcomes[allocation.id]
            amounts = snapshot["_money_plan"][allocation.id]
            db.add(SalesCreditNoteLine(
                org_id=context.org_id,
                credit_note_key=credit.credit_note_key,
                return_allocation_id=allocation.id,
                invoice_key=invoice.invoice_key,
                invoice_line_key=allocation.invoice_line_key,
                handover_allocation_key=allocation.handover_allocation_key,
                balance_id=allocation.balance_id,
                return_operation_key=movement_key,
                source_issue_valuation_id=outcome["source_issue_valuation_id"],
                return_valuation_id=outcome["return_valuation_id"],
                quantity=allocation.quantity,
                base_unit=allocation.base_unit,
                gross_credit_scr=amounts["gross"],
                net_credit_scr=amounts["net"],
                tax_credit_scr=amounts["tax"],
                restored_cost_scr=Decimal(outcome["restored_cost_scr"]),
                created_by=actor_id,
            ))
        debt = Decimal(snapshot["invoice_debt_applied_scr"])
        customer_credit = Decimal(snapshot["customer_credit_scr"])
        if debt > ZERO_MONEY:
            db.add(SalesInvoiceDebtApplication(
                org_id=context.org_id,
                credit_note_key=credit.credit_note_key,
                invoice_key=invoice.invoice_key,
                amount_scr=debt,
                created_by=actor_id,
            ))
        if customer_credit > ZERO_MONEY:
            db.add(CustomerCreditLiabilityEntry(
                org_id=context.org_id,
                entry_key=uuid5(credit.credit_note_key, "customer-credit"),
                credit_note_key=credit.credit_note_key,
                customer_key=invoice.customer_key,
                kind="RETURN_SURPLUS",
                currency="SCR",
                amount_scr=customer_credit,
                created_by=actor_id,
            ))
        db.flush()
        result = _credit_effect_snapshot(_credit_read(db, context, credit))
        return PostingEffect(result, {
            "kind": "sales.return.credited",
            "return_key": str(return_key),
            "credit_note_key": str(credit.credit_note_key),
            "invoice_key": str(invoice.invoice_key),
            "branch_id": invoice.branch_id,
            "gross_credit_scr": snapshot["gross_credit_scr"],
            "invoice_debt_applied_scr": snapshot["invoice_debt_applied_scr"],
            "customer_credit_scr": snapshot["customer_credit_scr"],
        })

    outcome = execute_once(
        factory, context, actor_id, payload.operation_key,
        "sales.return.credit.v1", request, apply, authorize=guard,
    )
    if hasattr(factory, "query"):
        credit = _owned(factory, SalesCreditNote, context).filter_by(
            return_key=return_key).one()
        result = _credit_read(factory, context, credit)
    else:
        with factory() as db:
            credit = _owned(db, SalesCreditNote, context).filter_by(
                return_key=return_key).one()
            result = _credit_read(db, context, credit)
    return dict(credit_note=result, replayed=outcome.replayed)
