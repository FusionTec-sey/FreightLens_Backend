from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Schema.BarcodeRetirementSchema import BarcodeRetirementRequest, BarcodeRetirementApply, BarcodeRetirementRead, BarcodeRetirementCaseRead
from Schema.InventoryLocationSchema import LocationPage
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page, case_metadata
from Services.barcode_retirement_service import load_retirement_binding, retire_barcode
from Services.unit_barcode_service import BarcodeSourceUnavailable
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission

BarcodeRetirementRouter = APIRouter(prefix="/inventory/barcode-retirement-cases", tags=["Inventory Barcode Reviews"])


def cases(db, context):
    return apply_org_filter(db.query(ManagerCase).filter(ManagerCase.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False), ManagerCase.action == "inventory.barcode.retire",
        ManagerCase.source_type == "product.barcode"), ManagerCase, context)


def source_case(db, context, key):
    case = cases(db, context).filter_by(case_key=key).one_or_none()
    if case is None: raise HTTPException(404, "Barcode retirement case not found")
    return case


def failure(db, exc):
    db.rollback()
    if isinstance(exc, BarcodeSourceUnavailable): return HTTPException(404, str(exc))
    if isinstance(exc, PostingConflict): return HTTPException(409, str(exc))
    if isinstance(exc, PermissionError): return HTTPException(403, str(exc))
    if isinstance(exc, ValueError): return HTTPException(422, str(exc))
    if isinstance(exc, IntegrityError): return HTTPException(409, "Barcode retirement conflicts with existing history")
    return exc


@BarcodeRetirementRouter.post("", response_model=CaseActionRead)
def request_retirement(payload: BarcodeRetirementRequest, db: Session = Depends(get_db),
                       context: OrgContext = Depends(get_org_context),
                       user=Depends(require_permission("Request_BarcodeRetirement"))):
    try:
        binding = load_retirement_binding(db, context, payload.barcode_id, lock=False)
        outcome = request_case(db, context, user.id, payload.operation_key, binding=binding, reason=payload.reason,
            load_binding=lambda session: load_retirement_binding(session, context, payload.barcode_id), authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as exc: raise failure(db, exc) from exc


@BarcodeRetirementRouter.get("", response_model=LocationPage[BarcodeRetirementCaseRead])
def list_retirements(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                     view: Literal["ALL", "NEEDS_MY_REVIEW", "MY_REQUESTS"] = Query("ALL"),
                     db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                     user=Depends(require_permission("Review_BarcodeRetirement"))):
    total, rows = case_page(db, cases(db, context), user.id, view, page, limit)
    items = [BarcodeRetirementCaseRead(**case_metadata(case, decision, used),
        product_id=case.binding["details"]["product_id"],
        product_name="Barcode " + case.binding["details"]["barcode"], config=case.binding["details"])
        for case, decision, used in rows]
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@BarcodeRetirementRouter.post("/{case_key}/review", response_model=CaseActionRead)
def review_retirement(case_key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db),
                      context: OrgContext = Depends(get_org_context),
                      user=Depends(require_permission("Review_BarcodeRetirement"))):
    try:
        case = source_case(db, context, case_key)
        outcome = review_case(db, context, user.id, payload.operation_key, case_key=case_key,
            binding=CaseBinding(**case.binding), expected_version=payload.expected_version, outcome=payload.outcome,
            reason=payload.reason, load_binding=lambda session: load_retirement_binding(session, context, int(case.source_key)),
            authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as exc: raise failure(db, exc) from exc


@BarcodeRetirementRouter.post("/{case_key}/retire", response_model=BarcodeRetirementRead)
def apply_retirement(case_key: UUID, payload: BarcodeRetirementApply, db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context),
                     user=Depends(require_permission("Retire_InventoryBarcode"))):
    try:
        case = source_case(db, context, case_key)
        outcome = retire_barcode(db, context, user.id, payload.operation_key, case_key=case_key,
            binding=CaseBinding(**case.binding), authorize=lambda session: None)
        db.commit()
        return BarcodeRetirementRead(**outcome.result, replayed=outcome.replayed)
    except Exception as exc: raise failure(db, exc) from exc
