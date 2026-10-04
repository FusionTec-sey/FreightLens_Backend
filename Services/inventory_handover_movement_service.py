"""Internal reservation-to-handover stock and cost issue coordinator.

This is the T09 pilot movement seam consumed later by T16. It owns no invoice,
collector, payment or collection eligibility policy. A trusted outer caller must
authorize those rules on every attempt. Serial stock remains blocked until the
identity-specific movement gateway can record exact assignment history.
"""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func

from Model.containermgmt.Inventory.CostPool import BranchCostPool
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockReservation
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.Product import Product
from Services.inventory_costing_service import COSTING_POLICY_VERSION, CostBalance, CostPool, issue
from Services.inventory_posting_service import PostingConflict, PostingEffect, execute_once
from Services.inventory_unit_service import convert_quantity
from Services.posting_authority_service import (
    AuthorityClaim,
    CostPoolAuthorityClaim,
    require_cost_pool_authority,
    require_posting_authority,
)
from Services.stock_ledger_service import (
    _effective_policy,
    _locked_balance,
    _parents,
    _query,
    _record,
    _snapshot,
)
from Utils.org_filter import apply_org_filter


ZERO = Decimal("0.000000")


def _claim_snapshot(claim):
    return {
        "org_id": claim.org_id,
        "node_key": str(claim.node_key),
        "epoch": claim.epoch,
        **({"branch_id": claim.branch_id} if isinstance(claim, AuthorityClaim)
           else {"cost_pool_id": claim.cost_pool_id}),
    }


def handover_reserved_stock(factory, context, actor_id, operation_key, *,
        balance_id, reservation_key, source_line_key, quantity, input_unit,
        expected_stock_version, expected_valuation_version, reason,
        stock_authority, cost_authority, authorize_stock, authorize_financial):
    """Consume one owned hold and its pool value in one retry-safe transaction.

    The future collection coordinator may pass its active Session as ``factory``.
    A returned result is then provisional until that outer transaction commits.
    """
    if not isinstance(operation_key, UUID) or not operation_key.int:
        raise ValueError("Stable nonzero handover operation identity required")
    if not isinstance(reservation_key, UUID) or not reservation_key.int:
        raise ValueError("Exact nonzero reservation identity required")
    if not isinstance(source_line_key, UUID) or not source_line_key.int:
        raise ValueError("Exact nonzero source-line identity required")
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= 0:
        raise ValueError("Positive exact Decimal handover quantity required")
    if type(expected_stock_version) is not int or expected_stock_version <= 0:
        raise ValueError("Positive expected stock version required")
    if type(expected_valuation_version) is not int or expected_valuation_version <= 0:
        raise ValueError("Positive expected valuation version required")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ValueError("A bounded handover reason is required")
    if not isinstance(stock_authority, AuthorityClaim):
        raise PermissionError("Trusted branch stock authority required")
    if not isinstance(cost_authority, CostPoolAuthorityClaim):
        raise PermissionError("Trusted central cost authority required")
    if not callable(authorize_stock) or not callable(authorize_financial):
        raise ValueError("Stock and financial authorization guards are required")

    request = {
        "balance_id": balance_id,
        "reservation_key": str(reservation_key),
        "source_line_key": str(source_line_key),
        "quantity": str(quantity),
        "input_unit": input_unit,
        "expected_stock_version": expected_stock_version,
        "expected_valuation_version": expected_valuation_version,
        "reason": reason.strip(),
        "stock_authority": _claim_snapshot(stock_authority),
        "cost_authority": _claim_snapshot(cost_authority),
    }
    scope = {}

    def guard(db):
        authorize_stock(db)
        authorize_financial(db)
        row = apply_org_filter(db.query(
            StockBalance.branch_id, StockBalance.location_id,
            StockBalance.product_id, StockBalance.base_unit,
        ).filter(
            StockBalance.id == balance_id,
            StockBalance.org_id == context.org_id,
            StockBalance.is_deleted.is_(False),
        ), StockBalance, context).one_or_none()
        if row is None:
            raise ValueError("Stock scope not found")
        if stock_authority.org_id != context.org_id or stock_authority.branch_id != row.branch_id:
            raise PermissionError("Branch stock authority does not own this handover")
        if cost_authority.org_id != context.org_id:
            raise PermissionError("Central cost authority does not own this handover")
        # Global lock order: operation -> central pool -> branch -> product/balance.
        require_cost_pool_authority(db, context, cost_authority,
            cost_pool_id=cost_authority.cost_pool_id)
        mapping = apply_org_filter(db.query(BranchCostPool).filter(
            BranchCostPool.org_id == context.org_id,
            BranchCostPool.branch_id == row.branch_id,
            BranchCostPool.cost_pool_id == cost_authority.cost_pool_id,
            BranchCostPool.is_deleted.is_(False),
        ), BranchCostPool, context).with_for_update(read=True).one_or_none()
        if mapping is None:
            raise PermissionError("Selling branch has no exact mapping to this cost authority")
        require_posting_authority(db, context, stock_authority, branch_id=row.branch_id)
        _parents(db, context, row.branch_id, row.location_id, row.product_id, row.base_unit)
        scope.update(branch_id=row.branch_id, product_id=row.product_id,
            base_unit=row.base_unit, cost_pool_id=mapping.cost_pool_id)

    def apply(db):
        product = _query(db, Product, context).filter_by(
            id=scope["product_id"], status="active", is_shared=False,
        ).with_for_update(of=Product).one_or_none()
        if product is None:
            raise PermissionError("Handover product is unavailable")
        balance = _locked_balance(db, context, balance_id)
        if balance.branch_id != scope["branch_id"] or balance.product_id != scope["product_id"]:
            raise PostingConflict("Handover stock scope changed")
        if balance.version != expected_stock_version:
            raise PostingConflict("Stock version changed; refresh before handover")
        if balance.tracking_policy == "SERIAL":
            raise PostingConflict("Serial handover requires exact serial assignment history")
        base_quantity = convert_quantity(
            _effective_policy(db, context, balance), quantity,
            input_unit if input_unit is not None else balance.base_unit,
        )
        hold = _query(db, StockReservation, context).filter_by(
            balance_id=balance.id,
            reservation_key=reservation_key,
            source_line_key=source_line_key,
        ).populate_existing().with_for_update().one_or_none()
        if hold is None:
            raise ValueError("Owned reservation not found")
        remaining = Decimal(hold.quantity) - Decimal(hold.released)
        if base_quantity > remaining:
            raise PostingConflict("Handover exceeds this reservation's remaining quantity")

        latest = _query(db, InventoryValuation, context).filter_by(
            cost_pool_id=scope["cost_pool_id"], product_id=scope["product_id"],
        ).order_by(InventoryValuation.version.desc()).first()
        if latest is None:
            raise PostingConflict("Valued stock is required before physical handover")
        if latest.version != expected_valuation_version:
            raise PostingConflict("Valuation version changed; refresh before handover")
        if latest.base_unit != balance.base_unit:
            raise PostingConflict("Valuation base unit differs from handover stock")
        physical = _query(db, StockBalance, context).join(BranchCostPool,
            (BranchCostPool.branch_id == StockBalance.branch_id) &
            (BranchCostPool.org_id == StockBalance.org_id)).filter(
                BranchCostPool.cost_pool_id == scope["cost_pool_id"],
                BranchCostPool.is_deleted.is_(False),
                StockBalance.product_id == scope["product_id"],
            ).with_entities(func.coalesce(func.sum(StockBalance.on_hand), 0)).scalar()
        if Decimal(physical) != Decimal(latest.pool_quantity):
            raise PostingConflict("Physical and valued stock must reconcile before handover")
        issued = issue(CostBalance(CostPool(context.org_id, scope["cost_pool_id"],
            scope["product_id"]), Decimal(latest.pool_quantity),
            Decimal(latest.pool_value_scr)), base_quantity)

        before = _snapshot(balance)
        after = before.handover_reserved(base_quantity)
        balance.on_hand = after.on_hand
        balance.reserved = after.reserved
        balance.version += 1
        balance.updated_by = actor_id
        hold.released = Decimal(hold.released) + base_quantity
        hold.updated_by = actor_id
        movement = _record(db, balance, operation_key, actor_id, "HANDOVER",
            reason.strip(), before, hold)
        db.flush()
        valuation = InventoryValuation(
            org_id=context.org_id, kind="ISSUE", source_valuation_id=latest.id,
            operation_key=operation_key, cost_pool_id=scope["cost_pool_id"],
            product_id=scope["product_id"], balance_id=balance.id,
            source_version=balance.version, version=latest.version + 1,
            base_unit=balance.base_unit, quantity=base_quantity,
            goods_value_scr=issued.value_scr, additional_cost_scr=ZERO,
            pool_quantity=issued.remaining.quantity,
            pool_value_scr=issued.remaining.value_scr,
            calculation_policy=COSTING_POLICY_VERSION, currency="SCR",
            status="UNRECONCILED", reason=reason.strip(), created_by=actor_id,
        )
        db.add(valuation)
        db.flush()
        result = dict(movement.result,
            source_line_key=str(source_line_key),
            handed_over=format(base_quantity, ".6f"),
            valuation_id=valuation.id,
            valuation_version=valuation.version,
            issued_value_scr=format(issued.value_scr, ".6f"),
            pool_quantity=format(issued.remaining.quantity, ".6f"),
            pool_value_scr=format(issued.remaining.value_scr, ".6f"),
            valuation_status="UNRECONCILED",
        )
        return PostingEffect(result, {
            "kind": "inventory.stock.handed-over",
            "balance_id": balance.id,
            "stock_version": balance.version,
            "reservation_key": str(reservation_key),
            "source_line_key": str(source_line_key),
            "quantity": format(base_quantity, ".6f"),
            "valuation_id": valuation.id,
            "valuation_version": valuation.version,
        })

    return execute_once(factory, context, actor_id, operation_key,
        "inventory.handover.issue.v1", request, apply, authorize=guard)

