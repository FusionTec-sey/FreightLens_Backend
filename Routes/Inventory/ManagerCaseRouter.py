from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseDecision, ManagerCaseUse
from Schema.ManagerCaseSchema import PolicyCaseRequest, PolicyCaseReview, PolicyCaseRead, CaseActionRead
from Schema.InventoryLocationSchema import LocationPage
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.inventory_posting_service import PostingConflict
from Services.policy_case_binding_service import load_policy_case_binding, PolicySourceUnavailable
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission
from Schema.PolicyActivationSchema import PolicyActivationRequest, PolicyActivationRead
from Services.policy_activation_service import activate_initial_policy
from Services.manager_case_read_service import case_page

ManagerCaseRouter = APIRouter(prefix="/inventory/manager-cases", tags=["Inventory Manager Cases"])


@ManagerCaseRouter.post("/{case_key}/activate-policy", response_model=PolicyActivationRead)
def activate_policy_case(case_key: UUID, payload: PolicyActivationRequest, db: Session = Depends(get_db),
                         context: OrgContext = Depends(get_org_context),
                         user=Depends(require_permission("Activate_InventoryPolicy"))):
    try:
        case = scoped_cases(db, context).filter_by(case_key=case_key).one_or_none()
        if case is None:
            raise HTTPException(404, "Manager case not found")
        outcome = activate_initial_policy(db, context, user.id, payload.operation_key, case_key=case_key,
            binding=CaseBinding(**case.binding), authorize=lambda session: None,
            expected_active_version=payload.expected_active_version)
        db.commit()
        return PolicyActivationRead(**outcome.result, replayed=outcome.replayed)
    except Exception as exc:
        db.rollback()
        raise translate(exc) from exc


def scoped_cases(db, context):
    return apply_org_filter(db.query(ManagerCase).filter(ManagerCase.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False), ManagerCase.action == "inventory.policy.activate",
        ManagerCase.source_type == "product.policy"), ManagerCase, context)


def translate(error):
    if isinstance(error, PolicySourceUnavailable): return HTTPException(404, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


@ManagerCaseRouter.post("/policy-activation", response_model=CaseActionRead)
def request_policy_case(payload: PolicyCaseRequest, db: Session = Depends(get_db),
                        context: OrgContext = Depends(get_org_context),
                        user=Depends(require_permission("Request_InventoryReview"))):
    try:
        binding = load_policy_case_binding(db, context, payload.product_id, lock=False)
        if binding.source_version != payload.expected_source_version:
            raise PostingConflict("Draft changed; reopen and review the saved version first")
        outcome = request_case(db, context, user.id, payload.operation_key, binding=binding, reason=payload.reason,
            load_binding=lambda session: load_policy_case_binding(session, context, payload.product_id),
            authorize=lambda session: None)  # authenticated action permission checked by dependency on EVERY request
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as exc:
        db.rollback()
        raise translate(exc) from exc


@ManagerCaseRouter.get("", response_model=LocationPage[PolicyCaseRead])
def list_policy_cases(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                      view: Literal["ALL", "NEEDS_MY_REVIEW", "MY_REQUESTS"] = Query("ALL"),
                      db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                      user=Depends(require_permission("Review_InventoryPolicy"))):
    query = scoped_cases(db, context)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = []
    for case, decision, used in rows:
        details = case.binding["details"]
        items.append(PolicyCaseRead(case_key=case.case_key, version=3 if used else 2 if decision else 1,
            status="CONSUMED" if used else decision.outcome if decision else "REQUESTED",
            product_id=details["product_id"], product_name=details["product_name"], source_version=case.source_version,
            expected_active_version=details.get("expected_active_version", 0),
            transition=details.get("transition", "STANDARD"),
            config=details["config"], reason=case.reason, requestor_id=case.created_by,
            reviewer_id=decision.created_by if decision else None, review_reason=decision.reason if decision else None,
            requested_at=case.created_at))
    return {"items": items, "total": total, "page": page, "pages": max(1, (total + limit - 1) // limit), "limit": limit}


@ManagerCaseRouter.post("/{case_key}/review", response_model=CaseActionRead)
def review_policy_case(case_key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db),
                       context: OrgContext = Depends(get_org_context),
                       user=Depends(require_permission("Review_InventoryPolicy"))):
    try:
        case = scoped_cases(db, context).filter_by(case_key=case_key).one_or_none()
        if case is None:
            raise HTTPException(404, "Manager case not found")
        binding = CaseBinding(**case.binding)
        outcome = review_case(db, context, user.id, payload.operation_key, case_key=case_key, binding=binding,
            expected_version=payload.expected_version, outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: load_policy_case_binding(session, context, int(case.source_key)),
            authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as exc:
        db.rollback()
        raise translate(exc) from exc
