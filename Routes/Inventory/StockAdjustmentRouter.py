"""Reviewed exact location-stock correction; never edits Product.current_stock."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.InventoryLocationSchema import LocationPage
from Schema.ManagerCaseSchema import CaseActionRead, PolicyCaseReview
from Schema.StockAdjustmentSchema import (
    StockAdjustmentCaseRead,
    StockAdjustmentExecutionRead,
    StockAdjustmentExecutionRequest,
    StockAdjustmentRequest,
)
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_read_service import case_metadata, case_page
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.stock_adjustment_service import (
    load_stock_adjustment_binding,
    reload_stock_adjustment_binding,
)
from Services.stock_ledger_service import adjust_stock_balance
from Services.stock_runtime_service import StockRuntimeUnavailable, server_stock_runtime
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_current_user, get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission


StockAdjustmentRouter = APIRouter(
    prefix="/inventory/stock-adjustment-cases",
    tags=["Inventory Stock Adjustments"],
    dependencies=[Depends(require_module("INVENTORY"))],
)


def translate(error):
    if isinstance(error, LookupError):
        return HTTPException(404, str(error))
    if isinstance(error, PermissionError):
        return HTTPException(403, str(error))
    if isinstance(error, PostingConflict):
        return HTTPException(409, str(error))
    if isinstance(error, ValueError):
        return HTTPException(422, str(error))
    return error


def guard(policy, permission):
    def check(db):
        if not policy.has(permission):
            raise PermissionError("Stock-adjustment permission required")
    return check


def scoped_cases(db, context):
    query = db.query(ManagerCase).filter(
        ManagerCase.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False),
        ManagerCase.action == "inventory.stock.adjust",
        ManagerCase.source_type == "inventory.stock-balance",
    )
    return apply_org_filter(query, ManagerCase, context)


@StockAdjustmentRouter.post("", response_model=CaseActionRead)
def request_adjustment(payload: StockAdjustmentRequest,
                       db: Session = Depends(get_db),
                       context: OrgContext = Depends(get_org_context),
                       policy: AccessPolicy = Depends(get_request_policy),
                       user=Depends(require_permission("Request_StockAdjustment"))):
    try:
        if not db.in_transaction():
            db.begin()
        binding = load_stock_adjustment_binding(
            db, context, payload.balance_id, payload.target_on_hand,
            payload.target_damaged, payload.target_quarantined, lock=True,
        )
        if binding.source_version != payload.expected_source_version:
            raise PostingConflict("Stock changed; refresh before requesting review")
        result = request_case(
            db, context, user.id, payload.operation_key,
            binding=binding, reason=payload.reason,
            load_binding=lambda session: reload_stock_adjustment_binding(session, context, binding),
            authorize=guard(policy, "Request_StockAdjustment"),
        )
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@StockAdjustmentRouter.get("", response_model=LocationPage[StockAdjustmentCaseRead])
def list_adjustments(page: int = Query(1, ge=1),
                     limit: int = Query(25, ge=1, le=100),
                     balance_id: int | None = Query(None, ge=1),
                     view: Literal["ALL", "NEEDS_MY_REVIEW", "MY_REQUESTS"] = "ALL",
                     db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context),
                     policy: AccessPolicy = Depends(get_request_policy),
                     user=Depends(get_current_user)):
    permissions = {
        "Request_StockAdjustment", "Review_StockAdjustment", "Execute_StockAdjustment",
    }
    if not any(policy.has(permission) for permission in permissions):
        raise HTTPException(403, "Stock-adjustment access required")
    query = scoped_cases(db, context)
    if balance_id is not None:
        query = query.filter(ManagerCase.source_key == str(balance_id))
    if not policy.has("Review_StockAdjustment") and not policy.has("Execute_StockAdjustment"):
        query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = []
    for case, decision, used in rows:
        details = case.binding["details"]
        items.append(StockAdjustmentCaseRead(
            **case_metadata(case, decision, used),
            **{key: details[key] for key in (
                "balance_id", "branch_id", "location_id", "product_id", "product_name",
                "base_unit", "tracking_policy", "batch_key", "before_on_hand", "reserved",
                "before_damaged", "before_quarantined", "target_on_hand",
                "target_damaged", "target_quarantined",
            )},
        ))
    return {"items": items, "total": total, "page": page, "limit": limit,
            "pages": max(1, (total + limit - 1) // limit)}


@StockAdjustmentRouter.post("/{case_key}/review", response_model=CaseActionRead)
def review_adjustment(case_key: UUID, payload: PolicyCaseReview,
                      db: Session = Depends(get_db),
                      context: OrgContext = Depends(get_org_context),
                      policy: AccessPolicy = Depends(get_request_policy),
                      user=Depends(require_permission("Review_StockAdjustment"))):
    try:
        case = scoped_cases(db, context).filter(ManagerCase.case_key == case_key).one_or_none()
        if case is None:
            raise LookupError("Stock-adjustment case not found")
        binding = CaseBinding(**case.binding)
        result = review_case(
            db, context, user.id, payload.operation_key,
            case_key=case_key, binding=binding,
            expected_version=payload.expected_version, outcome=payload.outcome,
            reason=payload.reason,
            load_binding=lambda session: reload_stock_adjustment_binding(session, context, binding),
            authorize=guard(policy, "Review_StockAdjustment"),
        )
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@StockAdjustmentRouter.post("/{case_key}/execute", response_model=StockAdjustmentExecutionRead)
def execute_adjustment(case_key: UUID, payload: StockAdjustmentExecutionRequest,
                       db: Session = Depends(get_db),
                       context: OrgContext = Depends(get_org_context),
                       policy: AccessPolicy = Depends(get_request_policy),
                       user=Depends(require_permission("Execute_StockAdjustment"))):
    try:
        case = scoped_cases(db, context).filter(ManagerCase.case_key == case_key).one_or_none()
        if case is None:
            raise LookupError("Stock-adjustment case not found")
        binding = CaseBinding(**case.binding)
        authority = server_stock_runtime().claim_for(db, context, binding.details["branch_id"])
        result = adjust_stock_balance(
            db, context, user.id, payload.operation_key,
            case_key=case_key, binding=binding,
            reason=f"Approved stock adjustment {case_key}",
            authorize=guard(policy, "Execute_StockAdjustment"), authority=authority,
        )
        db.commit()
        return StockAdjustmentExecutionRead(
            operation_key=result.operation_key, case_key=case_key, status="CONSUMED",
            replayed=result.replayed, **result.result,
        )
    except StockRuntimeUnavailable as error:
        db.rollback()
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback()
        raise translate(error) from error

