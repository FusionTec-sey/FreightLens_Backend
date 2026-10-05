"""Atomic, line-level physical collection for an already posted retail sale.

Payment confirmation and physical handover deliberately remain separate.  This
service consumes only the exact reservations committed by T13 and delegates each
physical/value issue to the existing T09 handover coordinator.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import func

from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
from Model.containermgmt.Inventory.BranchSettings import BranchSettingsRevision
from Model.containermgmt.Inventory.CostPool import BranchCostPool
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch, StockMovement, StockReservation
from Model.containermgmt.Inventory.StockSerial import StockSerialIdentity, StockSerialMovement, StockSerialPosition
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.SalesCollection import SalesCollection, SalesCollectionAllocation
from Model.containermgmt.Orders.SalesPosting import SalesInvoice, SalesInvoiceLine, SalesInvoiceReservation
from Schema.BranchCounterSchema import CounterConfig
from Schema.SalesCollectionSchema import SalesCollectionCreate, SalesCollectionRead
from Services.branch_action_context_service import require_branch_action_context
from Services.inventory_handover_movement_service import handover_reserved_stock
from Services.inventory_posting_service import PostingConflict, PostingEffect, execute_once
from Services.posting_authority_service import (
    AuthorityClaim,
    CostPoolAuthorityClaim,
    require_cost_pool_authority,
    require_posting_authority,
)
from Services.staff_store_assignment_service import latest_assignment, require_staff_store_assignment
from Utils.org_filter import apply_org_filter


ZERO = Decimal("0.000000")


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, model.is_deleted.is_(False)), model, context)


def _guard(context, authorize, db):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Collection company scope denied")
    if not callable(authorize):
        raise ValueError("Collection authorization guard required")
    authorize(db)


def _quantity(value):
    return format(Decimal(value), ".6f")


def _claim_snapshot(claim):
    if isinstance(claim, AuthorityClaim):
        return {"org_id": claim.org_id, "branch_id": claim.branch_id,
                "node_key": str(claim.node_key), "epoch": claim.epoch}
    if isinstance(claim, CostPoolAuthorityClaim):
        return {"org_id": claim.org_id, "cost_pool_id": claim.cost_pool_id,
                "node_key": str(claim.node_key), "epoch": claim.epoch}
    return None


def invoice_fulfilment_status(db, context, invoice_key):
    """Project immutable collection history without editing the invoice."""
    committed = _owned(db, SalesInvoiceReservation, context).filter_by(
        invoice_key=UUID(str(invoice_key))).with_entities(
        func.coalesce(func.sum(SalesInvoiceReservation.quantity), 0)).scalar()
    collected = _owned(db, SalesCollectionAllocation, context).filter_by(
        invoice_key=UUID(str(invoice_key))).with_entities(
        func.coalesce(func.sum(SalesCollectionAllocation.quantity), 0)).scalar()
    committed, collected = Decimal(committed), Decimal(collected)
    if collected == ZERO:
        return "AWAITING_COLLECTION"
    if collected < committed:
        return "PARTIALLY_COLLECTED"
    if collected == committed:
        return "COLLECTED"
    raise PostingConflict("Collection history exceeds the posted invoice")


def _collection_read(db, context, row):
    allocations = _owned(db, SalesCollectionAllocation, context).filter_by(
        collection_key=row.collection_key).order_by(
        SalesCollectionAllocation.line_key,
        SalesCollectionAllocation.reservation_key).all()
    serials_by_operation = defaultdict(list)
    operation_keys = [item.handover_operation_key for item in allocations]
    if operation_keys:
        serial_rows = _owned(db, StockSerialMovement, context).join(
            StockSerialIdentity,
            (StockSerialIdentity.id == StockSerialMovement.serial_id)
            & (StockSerialIdentity.org_id == StockSerialMovement.org_id)
            & (StockSerialIdentity.product_id == StockSerialMovement.product_id),
        ).filter(
            StockSerialMovement.operation_key.in_(operation_keys),
            StockSerialIdentity.is_deleted.is_(False),
        ).with_entities(
            StockSerialMovement.operation_key,
            StockSerialIdentity.serial_key,
            StockSerialIdentity.serial_number,
        ).order_by(
            StockSerialMovement.operation_key,
            StockSerialIdentity.serial_number,
            StockSerialIdentity.serial_key,
        ).all()
        for operation_key, serial_key, serial_number in serial_rows:
            serials_by_operation[operation_key].append(dict(
                serial_key=serial_key, serial_number=serial_number))
    return dict(
        collection_key=row.collection_key,
        operation_key=row.operation_key,
        invoice_key=row.invoice_key,
        branch_id=row.branch_id,
        counter_id=row.counter_id,
        branch_settings_version=row.branch_settings_version,
        counter_settings_version=row.counter_settings_version,
        assignment_version=row.assignment_version,
        business_date=row.business_date,
        collector_name=row.collector_name,
        collector_contact=row.collector_contact,
        collected_at=row.collected_at,
        collected_by=row.created_by,
        payment_status="PAID",
        fulfilment_status=invoice_fulfilment_status(
            db, context, row.invoice_key),
        allocations=[dict(
            line_key=item.line_key,
            reservation_key=item.reservation_key,
            balance_id=item.balance_id,
            location_id=item.location_id,
            batch_key=item.batch_key,
            handover_operation_key=item.handover_operation_key,
            quantity=_quantity(item.quantity),
            base_unit=item.base_unit,
            serials=serials_by_operation[item.handover_operation_key],
        ) for item in allocations],
    )


def read_collection(db, context, collection_key, *, authorize):
    _guard(context, authorize, db)
    row = _owned(db, SalesCollection, context).filter_by(
        collection_key=UUID(str(collection_key))).one_or_none()
    if row is None:
        raise LookupError("Sales collection not found")
    return _collection_read(db, context, row)


def list_invoice_collections(db, context, invoice_key, *, authorize):
    _guard(context, authorize, db)
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=UUID(str(invoice_key))).one_or_none()
    if invoice is None:
        raise LookupError("Sales invoice not found")
    rows = _owned(db, SalesCollection, context).filter_by(
        invoice_key=invoice.invoice_key).order_by(
        SalesCollection.collected_at, SalesCollection.collection_key).all()
    return [_collection_read(db, context, row) for row in rows]


def read_collection_options(db, context, actor_id, invoice_key, *, authorize):
    """Expose safe physical choices only for the actor's current working store."""
    _guard(context, authorize, db)
    invoice_key = UUID(str(invoice_key))
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=invoice_key).one_or_none()
    if invoice is None:
        raise LookupError("Sales invoice not found")
    assignment = latest_assignment(db, context, actor_id)
    if assignment is None:
        raise PermissionError("Working-store assignment missing")
    assignment = require_staff_store_assignment(db, context, actor_id,
        branch_id=assignment.branch_id, expected_version=assignment.version)
    if invoice.branch_id != assignment.branch_id:
        raise PermissionError(
            "Other-store collection requires its later approved workflow")
    settings = _owned(db, BranchSettingsRevision, context).filter_by(
        branch_id=assignment.branch_id).order_by(
        BranchSettingsRevision.version.desc()).first()
    if settings is None:
        raise PostingConflict("Branch trading settings are required")

    counters = []
    for counter in _owned(db, BranchCounter, context).filter_by(
            branch_id=assignment.branch_id).order_by(BranchCounter.code).all():
        revision = _owned(db, CounterSettingsRevision, context).filter_by(
            counter_id=counter.id).order_by(
            CounterSettingsRevision.version.desc()).first()
        if revision is None:
            continue
        config = CounterConfig.model_validate(revision.config)
        if config.is_enabled and config.purpose in ("COLLECTION", "BOTH"):
            counters.append(dict(counter_key=counter.counter_key,
                code=counter.code, name=config.name, version=revision.version))

    collected_by_reservation = defaultdict(lambda: ZERO)
    for reservation_key, quantity in _owned(
            db, SalesCollectionAllocation, context).filter_by(
                invoice_key=invoice_key).with_entities(
                    SalesCollectionAllocation.reservation_key,
                    func.sum(SalesCollectionAllocation.quantity)).group_by(
                        SalesCollectionAllocation.reservation_key).all():
        collected_by_reservation[reservation_key] = Decimal(quantity)

    line_totals = defaultdict(lambda: ZERO)
    for line_key, quantity in _owned(
            db, SalesCollectionAllocation, context).filter_by(
                invoice_key=invoice_key).with_entities(
                    SalesCollectionAllocation.line_key,
                    func.sum(SalesCollectionAllocation.quantity)).group_by(
                        SalesCollectionAllocation.line_key).all():
        line_totals[line_key] = Decimal(quantity)

    lines = _owned(db, SalesInvoiceLine, context).filter_by(
        invoice_key=invoice_key).order_by(SalesInvoiceLine.position).all()
    bindings = _owned(db, SalesInvoiceReservation, context).filter_by(
        invoice_key=invoice_key).order_by(
        SalesInvoiceReservation.line_key,
        SalesInvoiceReservation.reservation_key).all()
    reservations = []
    for binding in bindings:
        hold = _owned(db, StockReservation, context).filter_by(
            reservation_key=binding.reservation_key).one_or_none()
        balance = _owned(db, StockBalance, context).filter_by(
            id=hold.balance_id if hold else -1).one_or_none()
        if hold is None or balance is None:
            raise PostingConflict("Committed reservation stock is unavailable")
        if balance.branch_id != assignment.branch_id:
            continue
        remaining = Decimal(binding.quantity) - collected_by_reservation[
            binding.reservation_key]
        if remaining <= ZERO:
            continue
        location = _owned(db, StockLocation, context).filter_by(
            id=balance.location_id).one()
        batch = (_owned(db, StockBatch, context).filter_by(
            batch_key=balance.batch_key).one_or_none()
            if balance.batch_key else None)
        serials = []
        if balance.tracking_policy == "SERIAL":
            serials = _owned(db, StockSerialIdentity, context).join(
                StockSerialPosition,
                (StockSerialPosition.serial_id == StockSerialIdentity.id)
                & (StockSerialPosition.org_id == StockSerialIdentity.org_id)
                & (StockSerialPosition.product_id == StockSerialIdentity.product_id),
            ).filter(
                StockSerialIdentity.product_id == balance.product_id,
                StockSerialPosition.balance_id == balance.id,
                StockSerialPosition.condition == "AVAILABLE",
                StockSerialPosition.is_deleted.is_(False),
                ~_owned(db, StockSerialMovement, context).filter(
                    StockSerialMovement.serial_id == StockSerialIdentity.id,
                ).exists(),
            ).with_entities(
                StockSerialIdentity.serial_key,
                StockSerialIdentity.serial_number,
            ).order_by(
                StockSerialIdentity.serial_number,
                StockSerialIdentity.serial_key,
            ).all()
        reservations.append(dict(
            line_key=binding.line_key,
            reservation_key=binding.reservation_key,
            branch_id=balance.branch_id,
            balance_id=balance.id,
            location_id=balance.location_id,
            location_code=location.code,
            location_name=location.name,
            tracking_policy=balance.tracking_policy,
            batch_key=balance.batch_key,
            batch_code=batch.code if batch else None,
            shade=batch.shade if batch else None,
            calibre=batch.calibre if batch else None,
            base_unit=balance.base_unit,
            quantity=_quantity(binding.quantity),
            collected=_quantity(collected_by_reservation[binding.reservation_key]),
            remaining=_quantity(remaining),
            stock_version=balance.version,
            serials=[dict(serial_key=serial_key, serial_number=serial_number)
                for serial_key, serial_number in serials],
        ))
    return dict(
        invoice_key=invoice_key,
        invoice_number=invoice.invoice_number,
        payment_status="PAID",
        fulfilment_status=invoice_fulfilment_status(
            db, context, invoice_key),
        branch_id=assignment.branch_id,
        branch_settings_version=settings.version,
        assignment_version=assignment.version,
        counters=counters,
        lines=[dict(line_key=line.line_key, product_id=line.product_id,
            product_name=line.product_name, sku=line.sku,
            base_quantity=_quantity(line.base_quantity),
            collected=_quantity(line_totals[line.line_key]),
            remaining=_quantity(Decimal(line.base_quantity)
                - line_totals[line.line_key]),
            base_unit=line.base_unit) for line in lines],
        reservations=reservations,
    )


def post_collection(factory, context, actor_id, payload: SalesCollectionCreate, *,
        stock_authority, cost_authority, authorize, instant=None):
    """Atomically append collection history and its T09 HANDOVER/ISSUE rows."""
    if not isinstance(payload, SalesCollectionCreate):
        raise ValueError("Typed collection request required")
    if not isinstance(stock_authority, AuthorityClaim):
        raise PermissionError("Trusted collection-store authority required")
    if not isinstance(cost_authority, CostPoolAuthorityClaim):
        raise PermissionError("Trusted collection cost authority required")
    instant = instant or datetime.now(timezone.utc)
    request = payload.model_dump(mode="json") | {
        "stock_authority": _claim_snapshot(stock_authority),
        "cost_authority": _claim_snapshot(cost_authority),
    }
    scope = {}

    def guard(db):
        _guard(context, authorize, db)
        mapping = _owned(db, BranchCostPool, context).filter_by(
            branch_id=payload.branch_id).one_or_none()
        if mapping is None or mapping.cost_pool_id != cost_authority.cost_pool_id:
            raise PermissionError("Collection store has no exact cost authority")
        require_cost_pool_authority(db, context, cost_authority,
            cost_pool_id=mapping.cost_pool_id)
        require_posting_authority(db, context, stock_authority,
            branch_id=payload.branch_id)
        action = require_branch_action_context(db, context,
            branch_id=payload.branch_id, counter_key=payload.counter_key,
            branch_version=payload.expected_branch_settings_version,
            counter_version=payload.expected_counter_settings_version,
            instant=instant, action="COLLECTION", authorize=authorize)
        assignment = require_staff_store_assignment(db, context, actor_id,
            branch_id=payload.branch_id,
            expected_version=payload.expected_assignment_version)
        scope.update(action=action, assignment=assignment,
            cost_pool_id=mapping.cost_pool_id)

    def apply(db):
        invoice = _owned(db, SalesInvoice, context).filter_by(
            invoice_key=payload.invoice_key).with_for_update(
                read=True).one_or_none()
        if invoice is None:
            raise LookupError("Sales invoice not found")
        if invoice.branch_id != payload.branch_id:
            raise PermissionError(
                "Other-store collection requires its later approved workflow")
        requested = sorted(payload.allocations,
            key=lambda row: (str(row.line_key), str(row.reservation_key)))
        results = []
        base_versions = {}
        balance_offsets = defaultdict(int)
        for index, item in enumerate(requested):
            quantity = Decimal(item.quantity)
            binding = _owned(db, SalesInvoiceReservation, context).filter_by(
                invoice_key=invoice.invoice_key,
                line_key=item.line_key,
                reservation_key=item.reservation_key).with_for_update(
                    read=True).one_or_none()
            line = _owned(db, SalesInvoiceLine, context).filter_by(
                invoice_key=invoice.invoice_key,
                line_key=item.line_key).with_for_update(read=True).one_or_none()
            hold = _owned(db, StockReservation, context).filter_by(
                reservation_key=item.reservation_key).with_for_update().one_or_none()
            balance = _owned(db, StockBalance, context).filter_by(
                id=hold.balance_id if hold else -1).with_for_update().one_or_none()
            if binding is None or line is None or hold is None or balance is None:
                raise PostingConflict("Collection allocation is not an exact invoice reservation")
            if balance.branch_id != payload.branch_id:
                raise PermissionError("Collection stock belongs to another store")
            base_version = base_versions.setdefault(
                balance.id, item.expected_stock_version)
            if item.expected_stock_version != base_version:
                raise PostingConflict(
                    "One stock balance must use one expected starting version")
            effective_version = base_version + balance_offsets[balance.id]
            if balance.version != effective_version:
                raise PostingConflict("Stock version changed; refresh collection options")
            if balance.base_unit != line.base_unit:
                raise PostingConflict("Collection stock unit differs from the invoice")
            already = _owned(db, SalesCollectionAllocation, context).filter_by(
                invoice_key=invoice.invoice_key,
                reservation_key=item.reservation_key).with_entities(
                    func.coalesce(func.sum(
                        SalesCollectionAllocation.quantity), 0)).scalar()
            if Decimal(already) + quantity > Decimal(binding.quantity):
                raise PostingConflict("Collection exceeds this invoice reservation")
            valuation = _owned(db, InventoryValuation, context).filter_by(
                cost_pool_id=scope["cost_pool_id"],
                product_id=balance.product_id).order_by(
                    InventoryValuation.version.desc()).first()
            if valuation is None:
                raise PostingConflict("Valued stock is required before collection")
            handover_key = uuid5(payload.operation_key,
                f"collection:{index}:{item.line_key}:{item.reservation_key}")
            outcome = handover_reserved_stock(db, context, actor_id,
                handover_key, balance_id=balance.id,
                reservation_key=item.reservation_key,
                source_line_key=hold.source_line_key,
                quantity=quantity, input_unit=balance.base_unit,
                expected_stock_version=effective_version,
                expected_valuation_version=valuation.version,
                reason=f"Collection {payload.collection_key}",
                stock_authority=stock_authority,
                cost_authority=cost_authority,
                authorize_stock=authorize,
                authorize_financial=authorize,
                serial_keys=item.serial_keys)
            movement = _owned(db, StockMovement, context).filter_by(
                balance_id=balance.id, operation_key=handover_key,
                kind="HANDOVER").one()
            results.append((item, quantity, balance, movement, handover_key,
                outcome.result))
            balance_offsets[balance.id] += 1

        action = scope["action"]
        collection = SalesCollection(
            org_id=context.org_id,
            collection_key=payload.collection_key,
            operation_key=payload.operation_key,
            invoice_key=payload.invoice_key,
            branch_id=payload.branch_id,
            counter_id=action.counter_id,
            branch_settings_version=action.branch_settings_version,
            counter_settings_version=action.counter_settings_version,
            assignment_version=scope["assignment"].version,
            business_date=action.business_date,
            collector_name=payload.collector_name.strip(),
            collector_contact=payload.collector_contact.strip(),
            collected_at=instant,
            created_by=actor_id,
        )
        db.add(collection)
        db.flush()
        for item, quantity, balance, movement, handover_key, result in results:
            db.add(SalesCollectionAllocation(
                org_id=context.org_id,
                collection_key=payload.collection_key,
                invoice_key=payload.invoice_key,
                line_key=item.line_key,
                reservation_key=item.reservation_key,
                balance_id=balance.id,
                location_id=balance.location_id,
                batch_key=balance.batch_key,
                handover_operation_key=handover_key,
                quantity=quantity,
                base_unit=balance.base_unit,
                created_by=actor_id,
            ))
        db.flush()
        response = _collection_read(db, context, collection)
        response = SalesCollectionRead.model_validate(response).model_dump(
            mode="json")
        return PostingEffect(response, {
            "kind": "sales.collection.posted",
            "collection_key": str(payload.collection_key),
            "invoice_key": str(payload.invoice_key),
            "branch_id": payload.branch_id,
            "allocation_count": len(results),
            "fulfilment_status": response["fulfilment_status"],
        })

    return execute_once(factory, context, actor_id, payload.operation_key,
        "sales.collection.post.v1", request, apply, authorize=guard)
