"""Exact HANDOVER reversal into quarantine with proportional cost restoration."""
from decimal import Decimal, ROUND_HALF_UP, localcontext, Context
from uuid import UUID

from sqlalchemy import func

from Model.containermgmt.Inventory.CostPool import BranchCostPool
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.SalesReturn import SalesCreditNoteLine
from Services.inventory_costing_service import COSTING_POLICY_VERSION
from Services.inventory_posting_service import PostingConflict, PostingEffect, execute_once
from Services.inventory_quantity_service import QuantityBreakdown
from Services.posting_authority_service import (
    AuthorityClaim,
    CostPoolAuthorityClaim,
    require_cost_pool_authority,
    require_posting_authority,
)
from Services.stock_ledger_service import _locked_balance, _query, _record, _snapshot
from Utils.org_filter import apply_org_filter


ZERO = Decimal("0.000000")
COST_QUANTUM = Decimal("0.000001")


def _claim_snapshot(claim):
    if isinstance(claim, AuthorityClaim):
        return {"org_id": claim.org_id, "branch_id": claim.branch_id,
                "node_key": str(claim.node_key), "epoch": claim.epoch}
    if isinstance(claim, CostPoolAuthorityClaim):
        return {"org_id": claim.org_id, "cost_pool_id": claim.cost_pool_id,
                "node_key": str(claim.node_key), "epoch": claim.epoch}
    return None


def _proportional_issue_cost(issue_quantity, issue_value, prior_quantity,
                             prior_value, return_quantity):
    """Allocate original issue value cumulatively so a full return is exact."""
    values = tuple(Decimal(value) for value in (
        issue_quantity, issue_value, prior_quantity, prior_value, return_quantity))
    issue_quantity, issue_value, prior_quantity, prior_value, return_quantity = values
    remaining_quantity = issue_quantity - prior_quantity
    remaining_value = issue_value - prior_value
    if (issue_quantity <= ZERO or issue_value < ZERO or prior_quantity < ZERO
            or prior_value < ZERO or return_quantity <= ZERO
            or return_quantity > remaining_quantity or remaining_value < ZERO):
        raise PostingConflict("Original issue cost is unavailable for this return")
    cumulative_quantity = prior_quantity + return_quantity
    if return_quantity == remaining_quantity:
        return remaining_value.quantize(COST_QUANTUM)
    with localcontext(Context(prec=48)):
        cumulative_value = ((issue_value / issue_quantity) * cumulative_quantity).quantize(
            COST_QUANTUM, rounding=ROUND_HALF_UP)
        amount = cumulative_value - prior_value
    if amount > remaining_value:
        amount = remaining_value
    return amount


def return_handed_over_stock(factory, context, actor_id, operation_key, *,
        balance_id, handover_operation_key, quantity, expected_stock_version,
        expected_valuation_version, reason, stock_authority, cost_authority,
        authorize_stock, authorize_financial):
    """Restore one exact handed-over quantity to its original balance in quarantine."""
    if not isinstance(operation_key, UUID) or not operation_key.int:
        raise ValueError("Stable nonzero return operation identity required")
    if not isinstance(handover_operation_key, UUID) or not handover_operation_key.int:
        raise ValueError("Exact nonzero handover identity required")
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity <= ZERO:
        raise ValueError("Positive exact Decimal return quantity required")
    if type(expected_stock_version) is not int or expected_stock_version <= 0:
        raise ValueError("Positive expected stock version required")
    if type(expected_valuation_version) is not int or expected_valuation_version <= 0:
        raise ValueError("Positive expected valuation version required")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ValueError("A bounded return reason is required")
    if not isinstance(stock_authority, AuthorityClaim):
        raise PermissionError("Trusted branch stock authority required")
    if not isinstance(cost_authority, CostPoolAuthorityClaim):
        raise PermissionError("Trusted central cost authority required")
    if not callable(authorize_stock) or not callable(authorize_financial):
        raise ValueError("Stock and financial authorization guards are required")

    request = {
        "balance_id": balance_id,
        "handover_operation_key": str(handover_operation_key),
        "quantity": format(quantity, ".6f"),
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
            StockBalance.branch_id, StockBalance.product_id,
            StockBalance.base_unit,
        ).filter(
            StockBalance.id == balance_id,
            StockBalance.org_id == context.org_id,
            StockBalance.is_deleted.is_(False),
        ), StockBalance, context).one_or_none()
        if row is None:
            raise LookupError("Return stock scope not found")
        if (stock_authority.org_id != context.org_id
                or stock_authority.branch_id != row.branch_id):
            raise PermissionError("Branch authority does not own this return")
        if cost_authority.org_id != context.org_id:
            raise PermissionError("Central cost authority does not own this return")
        require_cost_pool_authority(db, context, cost_authority,
                                    cost_pool_id=cost_authority.cost_pool_id)
        mapping = apply_org_filter(db.query(BranchCostPool).filter_by(
            org_id=context.org_id,
            branch_id=row.branch_id,
            cost_pool_id=cost_authority.cost_pool_id,
            is_deleted=False,
        ), BranchCostPool, context).with_for_update(read=True).one_or_none()
        if mapping is None:
            raise PermissionError("Return branch has no exact cost authority")
        require_posting_authority(db, context, stock_authority,
                                  branch_id=row.branch_id)
        scope.update(branch_id=row.branch_id, product_id=row.product_id,
                     base_unit=row.base_unit, cost_pool_id=mapping.cost_pool_id)

    def apply(db):
        balance = _locked_balance(db, context, balance_id)
        if (balance.branch_id != scope["branch_id"]
                or balance.product_id != scope["product_id"]
                or balance.base_unit != scope["base_unit"]):
            raise PostingConflict("Return stock scope changed")
        if balance.version != expected_stock_version:
            raise PostingConflict("Stock version changed; refresh return processing")
        if balance.tracking_policy == "SERIAL":
            raise PostingConflict("Serial returns require exact serial history")

        handover = _query(db, StockMovement, context).filter_by(
            balance_id=balance.id,
            operation_key=handover_operation_key,
            kind="HANDOVER",
        ).with_for_update(read=True).one_or_none()
        issue = _query(db, InventoryValuation, context).filter_by(
            balance_id=balance.id,
            operation_key=handover_operation_key,
            kind="ISSUE",
        ).with_for_update(read=True).one_or_none()
        if handover is None or issue is None:
            raise PostingConflict("Original handover value is unavailable")
        if (-Decimal(handover.on_hand_delta) != Decimal(issue.quantity)
                or quantity > Decimal(issue.quantity)
                or issue.product_id != balance.product_id
                or issue.base_unit != balance.base_unit
                or issue.cost_pool_id != scope["cost_pool_id"]):
            raise PostingConflict("Original handover and issue do not match")

        latest = _query(db, InventoryValuation, context).filter_by(
            cost_pool_id=scope["cost_pool_id"],
            product_id=scope["product_id"],
        ).order_by(InventoryValuation.version.desc()).with_for_update().first()
        if latest is None or latest.version != expected_valuation_version:
            raise PostingConflict("Valuation version changed; refresh return processing")
        if latest.base_unit != balance.base_unit:
            raise PostingConflict("Valuation unit differs from returned stock")
        physical = _query(db, StockBalance, context).join(
            BranchCostPool,
            (BranchCostPool.branch_id == StockBalance.branch_id)
            & (BranchCostPool.org_id == StockBalance.org_id),
        ).filter(
            BranchCostPool.cost_pool_id == scope["cost_pool_id"],
            BranchCostPool.is_deleted.is_(False),
            StockBalance.product_id == scope["product_id"],
        ).with_entities(func.coalesce(func.sum(StockBalance.on_hand), 0)).scalar()
        if Decimal(physical) != Decimal(latest.pool_quantity):
            raise PostingConflict("Physical and valued stock must reconcile before return")

        prior_quantity, prior_value = _query(
            db, SalesCreditNoteLine, context,
        ).filter_by(source_issue_valuation_id=issue.id).with_entities(
            func.coalesce(func.sum(SalesCreditNoteLine.quantity), 0),
            func.coalesce(func.sum(SalesCreditNoteLine.restored_cost_scr), 0),
        ).one()
        restored_cost = _proportional_issue_cost(
            issue.quantity, issue.goods_value_scr,
            prior_quantity, prior_value, quantity,
        )

        before = _snapshot(balance)
        balance.on_hand = Decimal(balance.on_hand) + quantity
        balance.quarantined = Decimal(balance.quarantined) + quantity
        balance.version += 1
        balance.updated_by = actor_id
        QuantityBreakdown(balance.on_hand, balance.reserved,
                          balance.damaged, balance.quarantined)
        movement_effect = _record(
            db, balance, operation_key, actor_id, "RETURN", reason.strip(), before,
        )
        db.flush()
        movement = _query(db, StockMovement, context).filter_by(
            balance_id=balance.id,
            operation_key=operation_key,
            kind="RETURN",
        ).one()
        valuation = InventoryValuation(
            org_id=context.org_id,
            kind="RETURN",
            source_valuation_id=latest.id,
            operation_key=operation_key,
            cost_pool_id=scope["cost_pool_id"],
            product_id=scope["product_id"],
            balance_id=balance.id,
            source_version=movement.version,
            version=latest.version + 1,
            base_unit=balance.base_unit,
            quantity=quantity,
            goods_value_scr=restored_cost,
            additional_cost_scr=ZERO,
            pool_quantity=Decimal(latest.pool_quantity) + quantity,
            pool_value_scr=Decimal(latest.pool_value_scr) + restored_cost,
            calculation_policy=COSTING_POLICY_VERSION,
            currency="SCR",
            status="UNRECONCILED",
            reason=reason.strip(),
            created_by=actor_id,
        )
        db.add(valuation)
        db.flush()
        result = dict(
            movement_effect.result,
            handover_operation_key=str(handover_operation_key),
            returned=format(quantity, ".6f"),
            source_issue_valuation_id=issue.id,
            return_valuation_id=valuation.id,
            valuation_version=valuation.version,
            restored_cost_scr=format(restored_cost, ".6f"),
            pool_quantity=format(Decimal(valuation.pool_quantity), ".6f"),
            pool_value_scr=format(Decimal(valuation.pool_value_scr), ".6f"),
            valuation_status="UNRECONCILED",
        )
        return PostingEffect(result, {
            "kind": "inventory.stock.returned-quarantine",
            "balance_id": balance.id,
            "stock_version": balance.version,
            "handover_operation_key": str(handover_operation_key),
            "quantity": format(quantity, ".6f"),
            "source_issue_valuation_id": issue.id,
            "return_valuation_id": valuation.id,
        })

    return execute_once(
        factory, context, actor_id, operation_key,
        "inventory.return.receive.v1", request, apply, authorize=guard,
    )
