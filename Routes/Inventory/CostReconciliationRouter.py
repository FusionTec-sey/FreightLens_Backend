"""Reviewed immutable cost reconciliation; not an accounting-period close."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Model.db import get_db
from Model.containermgmt.Inventory.CostReconciliation import InventoryCostReconciliation
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Model.containermgmt.Orders.Product import Product
from Schema.CostReconciliationSchema import (
    CostReconciliationCaseRead, CostReconciliationExecutionRead,
    CostReconciliationExecute, CostReconciliationRead, CostReconciliationRequest)
from Schema.InventoryLocationSchema import LocationPage
from Schema.ManagerCaseSchema import CaseActionRead, PolicyCaseReview
from Services.cost_reconciliation_checkpoint_service import (
    ACTION, close_reconciliation, reconciliation_binding)
from Services.cost_runtime_service import CostRuntimeUnavailable, server_cost_runtime
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_read_service import case_metadata, case_page
from Services.manager_case_service import CaseBinding, request_case, review_case
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_current_user, get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission, is_financial_user


CostReconciliationRouter = APIRouter(prefix="/inventory/cost-reconciliation",
    tags=["Inventory Cost Reconciliation"], dependencies=[Depends(require_module("INVENTORY"))])


def translate(error):
    if isinstance(error, LookupError): return HTTPException(404, str(error))
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


def access(context, user, policy, permission):
    if not policy.has(permission) or not policy.has("View_Product") \
            or not policy.has("View_Financials") or not is_financial_user(user, context):
        raise PermissionError("Financial inventory reconciliation access required")


def scoped_cases(db, context):
    return apply_org_filter(db.query(ManagerCase).filter(
        ManagerCase.org_id == context.org_id, ManagerCase.is_deleted.is_(False),
        ManagerCase.action == ACTION,
        ManagerCase.source_type == "inventory.cost-pool-product"), ManagerCase, context)


@CostReconciliationRouter.post("/cases", response_model=CaseActionRead)
def request_reconciliation(payload: CostReconciliationRequest,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        user=Depends(require_permission("Request_CostReconciliation"))):
    try:
        access(context, user, policy, "Request_CostReconciliation")
        binding = reconciliation_binding(db, context, payload.cost_pool_id,
                                         payload.product_id, lock=True)
        result = request_case(db, context, user.id, payload.operation_key,
            binding=binding, reason=payload.reason,
            load_binding=lambda session: reconciliation_binding(session, context,
                payload.cost_pool_id, payload.product_id, lock=True),
            authorize=lambda session: access(context, user, policy,
                "Request_CostReconciliation"))
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@CostReconciliationRouter.get("/cases", response_model=LocationPage[CostReconciliationCaseRead])
def list_reconciliation_cases(page: int = Query(1, ge=1),
        limit: int = Query(25, ge=1, le=100),
        cost_pool_id: int | None = Query(None, gt=0),
        product_id: int | None = Query(None, gt=0),
        view: Literal["ALL", "NEEDS_MY_REVIEW", "MY_REQUESTS"] = "ALL",
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy), user=Depends(get_current_user)):
    permissions = {"Request_CostReconciliation", "Review_CostReconciliation", "Execute_CostReconciliation"}
    if not any(policy.has(name) for name in permissions):
        raise HTTPException(403, "Cost reconciliation access required")
    access(context, user, policy, next(name for name in permissions if policy.has(name)))
    query = scoped_cases(db, context)
    if cost_pool_id is not None:
        query = query.filter(ManagerCase.binding["details"]["cost_pool_id"].as_integer() == cost_pool_id)
    if product_id is not None:
        query = query.filter(ManagerCase.binding["details"]["product_id"].as_integer() == product_id)
    if not policy.has("Review_CostReconciliation") and not policy.has("Execute_CostReconciliation"):
        query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = []
    for case, decision, used in rows:
        details = case.binding["details"]
        items.append(CostReconciliationCaseRead(**case_metadata(case, decision, used),
            **{name: details[name] for name in ("cost_pool_id", "product_id", "product_name",
                "valuation_id", "valuation_version", "base_unit", "pool_quantity", "pool_value_scr")},
            balance_count=len(details["balances"])))
    return {"items": items, "total": total, "page": page, "limit": limit,
            "pages": max(1, (total + limit - 1) // limit)}


@CostReconciliationRouter.post("/cases/{case_key}/review", response_model=CaseActionRead)
def review_reconciliation(case_key: UUID, payload: PolicyCaseReview,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        user=Depends(require_permission("Review_CostReconciliation"))):
    try:
        access(context, user, policy, "Review_CostReconciliation")
        case = scoped_cases(db, context).filter(ManagerCase.case_key == case_key).one_or_none()
        if case is None: raise LookupError("Cost reconciliation case not found")
        binding = CaseBinding(**case.binding); details = binding.details
        result = review_case(db, context, user.id, payload.operation_key,
            case_key=case_key, binding=binding, expected_version=payload.expected_version,
            outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: reconciliation_binding(session, context,
                details["cost_pool_id"], details["product_id"], lock=True),
            authorize=lambda session: access(context, user, policy,
                "Review_CostReconciliation"))
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@CostReconciliationRouter.post("/cases/{case_key}/close", response_model=CostReconciliationExecutionRead)
def close_reconciliation_case(case_key: UUID, payload: CostReconciliationExecute,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        user=Depends(require_permission("Execute_CostReconciliation"))):
    try:
        access(context, user, policy, "Execute_CostReconciliation")
        case = scoped_cases(db, context).filter(ManagerCase.case_key == case_key).one_or_none()
        if case is None: raise LookupError("Cost reconciliation case not found")
        binding = CaseBinding(**case.binding)
        claim = server_cost_runtime().claim_for(db, context, binding.details["cost_pool_id"])
        result = close_reconciliation(db, context, user.id, payload.operation_key,
            case_key=case_key, binding=binding, authority_claim=claim,
            authorize=lambda session: access(context, user, policy,
                "Execute_CostReconciliation"))
        db.commit()
        return CostReconciliationExecutionRead(operation_key=result.operation_key,
            case_key=case_key, replayed=result.replayed, **result.result)
    except CostRuntimeUnavailable as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise translate(error) from error


@CostReconciliationRouter.get("/checkpoints", response_model=LocationPage[CostReconciliationRead])
def list_checkpoints(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        cost_pool_id: int | None = Query(None, gt=0), product_id: int | None = Query(None, gt=0),
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        user=Depends(require_permission("View_Financials"))):
    try:
        access(context, user, policy, "View_Financials")
    except Exception as error:
        raise translate(error) from error
    query = apply_org_filter(db.query(InventoryCostReconciliation, Product.name).join(Product,
        (Product.id == InventoryCostReconciliation.product_id) &
        (Product.org_id == InventoryCostReconciliation.org_id)).filter(
            InventoryCostReconciliation.org_id == context.org_id,
            InventoryCostReconciliation.is_deleted.is_(False)), InventoryCostReconciliation, context)
    if cost_pool_id is not None: query = query.filter(InventoryCostReconciliation.cost_pool_id == cost_pool_id)
    if product_id is not None: query = query.filter(InventoryCostReconciliation.product_id == product_id)
    total = query.count()
    rows = query.order_by(InventoryCostReconciliation.created_at.desc(),
        InventoryCostReconciliation.id.desc()).offset((page - 1) * limit).limit(limit).all()
    items = [CostReconciliationRead(product_name=name,
        **{field: getattr(row, field) for field in ("checkpoint_key", "cost_pool_id", "product_id",
            "valuation_id", "valuation_version", "base_unit", "line_count", "status", "created_at", "created_by")},
        pool_quantity=format(row.pool_quantity, ".6f"), pool_value_scr=format(row.pool_value_scr, ".6f"))
        for row, name in rows]
    return {"items": items, "total": total, "page": page, "limit": limit,
            "pages": max(1, (total + limit - 1) // limit)}
