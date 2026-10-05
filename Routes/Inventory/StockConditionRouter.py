"""Reviewed T18 return-stock quarantine-to-damaged transition endpoints."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.InventoryLocationSchema import LocationPage
from Schema.ManagerCaseSchema import CaseActionRead, PolicyCaseReview
from Schema.StockConditionSchema import (
    StockConditionCaseRead,
    StockConditionExecutionRead,
    StockConditionExecutionRequest,
    StockConditionRequest,
    StockConditionSourceRead,
)
from Services.inventory_condition_movement_service import transition_return_condition
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_read_service import case_metadata, case_page
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.stock_condition_service import (
    ACTION,
    SOURCE_TYPE,
    load_return_condition_binding,
    list_return_condition_sources,
    reload_return_condition_binding,
)
from Services.stock_runtime_service import StockRuntimeUnavailable, server_stock_runtime
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_current_user, get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission
from Routes.MasterData.CustomerRouter import private_response


StockConditionRouter = APIRouter(
    prefix="/inventory/stock-condition-cases",
    tags=["Inventory Stock Conditions"],
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
            raise PermissionError("Stock-condition permission required")
    return check


def scoped_cases(db, context):
    query = db.query(ManagerCase).filter(
        ManagerCase.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False),
        ManagerCase.action == ACTION,
        ManagerCase.source_type == SOURCE_TYPE,
    )
    return apply_org_filter(query, ManagerCase, context)


def source_access(policy):
    if not policy.has("View_Product") or not any(policy.has(permission) for permission in (
        "Request_StockCondition", "Review_StockCondition", "Execute_StockCondition",
    )):
        raise HTTPException(403, "Stock-condition source access required")


@StockConditionRouter.get(
    "/sources", response_model=LocationPage[StockConditionSourceRead],
    dependencies=[Depends(private_response)],
)
def list_condition_sources(page: int = Query(1, ge=1),
                           limit: int = Query(25, ge=1, le=100),
                           db: Session = Depends(get_db),
                           context: OrgContext = Depends(get_org_context),
                           policy: AccessPolicy = Depends(get_request_policy),
                           user=Depends(get_current_user)):
    source_access(policy)
    try:
        total, items = list_return_condition_sources(
            db, context, page=page, limit=limit)
        return {"items": items, "total": total, "page": page, "limit": limit,
                "pages": max(1, (total + limit - 1) // limit)}
    except Exception as error:
        raise translate(error) from error


@StockConditionRouter.post("", response_model=CaseActionRead)
def request_condition(payload: StockConditionRequest,
                      db: Session = Depends(get_db),
                      context: OrgContext = Depends(get_org_context),
                      policy: AccessPolicy = Depends(get_request_policy),
                      user=Depends(require_permission("Request_StockCondition"))):
    try:
        if not db.in_transaction():
            db.begin()
        binding = load_return_condition_binding(
            db, context, payload.credit_note_line_id, payload.quantity, lock=True)
        if binding.source_version != payload.expected_source_version:
            raise PostingConflict("Return stock changed; refresh before requesting review")
        result = request_case(
            db, context, user.id, payload.operation_key,
            binding=binding, reason=payload.reason,
            load_binding=lambda session: reload_return_condition_binding(
                session, context, binding),
            authorize=guard(policy, "Request_StockCondition"),
        )
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@StockConditionRouter.get("", response_model=LocationPage[StockConditionCaseRead])
def list_conditions(page: int = Query(1, ge=1),
                    limit: int = Query(25, ge=1, le=100),
                    credit_note_line_id: int | None = Query(None, ge=1),
                    view: Literal["ALL", "NEEDS_MY_REVIEW", "MY_REQUESTS"] = "ALL",
                    db: Session = Depends(get_db),
                    context: OrgContext = Depends(get_org_context),
                    policy: AccessPolicy = Depends(get_request_policy),
                    user=Depends(get_current_user)):
    permissions = {
        "Request_StockCondition", "Review_StockCondition", "Execute_StockCondition",
    }
    if not any(policy.has(permission) for permission in permissions):
        raise HTTPException(403, "Stock-condition access required")
    query = scoped_cases(db, context)
    if credit_note_line_id is not None:
        query = query.filter(ManagerCase.source_key == str(credit_note_line_id))
    if not policy.has("Review_StockCondition") and not policy.has("Execute_StockCondition"):
        query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    fields = (
        "credit_note_line_id", "credit_note_key", "credit_note_number", "return_key",
        "return_operation_key", "invoice_key", "invoice_line_key", "handover_allocation_key",
        "balance_id", "branch_id", "branch_name", "location_id", "location_name", "product_id",
        "product_name", "product_sku",
        "base_unit", "tracking_policy", "batch_key", "quantity", "source_return_quantity",
        "previously_transitioned", "pending_review_quantity", "from_condition", "to_condition", "before_on_hand",
        "before_reserved", "before_damaged", "before_quarantined", "target_damaged",
        "target_quarantined",
    )
    items = []
    for case, decision, used in rows:
        details = case.binding["details"]
        items.append(StockConditionCaseRead(
            **case_metadata(case, decision, used),
            **{key: details[key] for key in fields},
        ))
    return {"items": items, "total": total, "page": page, "limit": limit,
            "pages": max(1, (total + limit - 1) // limit)}


@StockConditionRouter.post("/{case_key}/review", response_model=CaseActionRead)
def review_condition(case_key: UUID, payload: PolicyCaseReview,
                     db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context),
                     policy: AccessPolicy = Depends(get_request_policy),
                     user=Depends(require_permission("Review_StockCondition"))):
    try:
        case = scoped_cases(db, context).filter(ManagerCase.case_key == case_key).one_or_none()
        if case is None:
            raise LookupError("Stock-condition case not found")
        binding = CaseBinding(**case.binding)
        result = review_case(
            db, context, user.id, payload.operation_key,
            case_key=case_key, binding=binding,
            expected_version=payload.expected_version, outcome=payload.outcome,
            reason=payload.reason,
            load_binding=lambda session: reload_return_condition_binding(
                session, context, binding, current_case_key=case_key),
            authorize=guard(policy, "Review_StockCondition"),
        )
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@StockConditionRouter.post("/{case_key}/execute", response_model=StockConditionExecutionRead)
def execute_condition(case_key: UUID, payload: StockConditionExecutionRequest,
                      db: Session = Depends(get_db),
                      context: OrgContext = Depends(get_org_context),
                      policy: AccessPolicy = Depends(get_request_policy),
                      user=Depends(require_permission("Execute_StockCondition"))):
    try:
        case = scoped_cases(db, context).filter(ManagerCase.case_key == case_key).one_or_none()
        if case is None:
            raise LookupError("Stock-condition case not found")
        binding = CaseBinding(**case.binding)
        authority = server_stock_runtime().claim_for(
            db, context, binding.details["branch_id"])
        result = transition_return_condition(
            db, context, user.id, payload.operation_key,
            case_key=case_key, binding=binding,
            reason=f"Approved return-stock condition transition {case_key}",
            authority=authority, authorize=guard(policy, "Execute_StockCondition"),
        )
        db.commit()
        return StockConditionExecutionRead(
            operation_key=result.operation_key, case_key=case_key,
            status="CONSUMED", replayed=result.replayed, **result.result)
    except StockRuntimeUnavailable as error:
        db.rollback()
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback()
        raise translate(error) from error
