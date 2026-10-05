"""Permission-scoped customer return, review and credit-note endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from Model.db import get_db
from Model.containermgmt.Inventory.CostPool import BranchCostPool
from Model.containermgmt.Orders.SalesReturn import SalesReturnClaim
from Schema.SalesReturnSchema import (
    SalesCreditNotePage,
    SalesCreditNoteRead,
    SalesReturnClaimCreate,
    SalesReturnClaimCreateResult,
    SalesReturnClaimPage,
    SalesReturnClaimRead,
    SalesReturnCreditNoteCreate,
    SalesReturnCreditNoteResult,
    SalesReturnOptionsRead,
    SalesReturnProcessingOptionsRead,
    SalesReturnReview,
    SalesReturnReviewResult,
)
from Schema.SalesPostingSchema import SalesInvoiceRead
from Services.cost_runtime_service import CostRuntimeUnavailable, server_cost_runtime
from Services.inventory_posting_service import PostingConflict
from Services.sales_return_service import (
    list_invoice_credit_notes,
    list_invoice_returns,
    process_return_credit,
    read_credit_note,
    read_posted_invoice_for_draft,
    read_return_claim,
    read_return_options,
    read_return_processing_options,
    request_return_claim,
    review_return_claim,
)
from Services.stock_runtime_service import StockRuntimeUnavailable, server_stock_runtime
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission


def return_access(policy: AccessPolicy = Depends(get_request_policy)):
    required = ("View_Sale", "View_Product", "View_Customer",
                "View_Personal_Data", "View_Financial_Data")
    if (any(not policy.has(name) for name in required)
            or not policy.allows_field_class("PERSONAL")
            or not policy.allows_field_class("FINANCIAL")):
        raise HTTPException(403, "Sale return, customer and financial access required")
    return policy


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


SalesReturnRouter = APIRouter(
    prefix="/sales",
    tags=["Sales returns"],
    dependencies=[Depends(require_module("SALES")), Depends(return_access),
                  Depends(private_response)],
)


def _authorize(policy, action_permission=None):
    def authorize(db):
        required = ("View_Sale", "View_Product", "View_Customer",
                    "View_Personal_Data", "View_Financial_Data")
        if (any(not policy.has(name) for name in required)
                or not policy.allows_field_class("PERSONAL")
                or not policy.allows_field_class("FINANCIAL")
                or (action_permission and not policy.has(action_permission))):
            raise PermissionError("Sales return access required")
    return authorize


def _http(status, code, message):
    return HTTPException(status, detail={"code": code, "message": message})


def _error(error):
    if isinstance(error, LookupError):
        return _http(404, "RETURN_NOT_FOUND", str(error))
    if isinstance(error, PermissionError):
        return _http(403, "RETURN_ACCESS_DENIED", str(error))
    if isinstance(error, (PostingConflict, IntegrityError)):
        return _http(409, "RETURN_STATE_CHANGED",
                     "Return state changed; reload before retrying")
    if (isinstance(error, DBAPIError)
            and getattr(error.orig, "pgcode", None) == "P0001"):
        return _http(409, "RETURN_STATE_CHANGED",
                     "Return state changed; reload before retrying")
    if isinstance(error, ValueError):
        return _http(422, "RETURN_REQUEST_INVALID", str(error))
    return error


def _call(db, action, *, commit=False):
    try:
        result = action()
        if commit:
            db.commit()
        return result
    except Exception as error:
        db.rollback()
        raise _error(error) from error


@SalesReturnRouter.get(
    "/invoices/{invoice_key}/return-options",
    response_model=SalesReturnOptionsRead,
)
def return_options(invoice_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: read_return_options(
        db, context, invoice_key, authorize=_authorize(policy)))


@SalesReturnRouter.get(
    "/drafts/{document_key}/posted-invoice", response_model=SalesInvoiceRead,
)
def posted_invoice_for_draft(document_key: UUID,
        draft_version: int = Query(..., ge=1), db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: read_posted_invoice_for_draft(
        db, context, document_key, draft_version,
        authorize=_authorize(policy)))


@SalesReturnRouter.put(
    "/returns/{return_key}",
    response_model=SalesReturnClaimCreateResult,
)
def put_return_claim(return_key: UUID, payload: SalesReturnClaimCreate,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("Request_SaleReturn"))):
    if return_key != payload.return_key:
        raise _http(422, "RETURN_IDENTITY_MISMATCH",
                    "Path and return identities must match")
    authorize = _authorize(policy, "Request_SaleReturn")
    outcome = _call(db, lambda: request_return_claim(
        db, context, user.id, payload, authorize=authorize), commit=True)
    return SalesReturnClaimCreateResult(
        claim=outcome.result, replayed=outcome.replayed)


@SalesReturnRouter.get(
    "/returns/{return_key}", response_model=SalesReturnClaimRead,
)
def get_return_claim(return_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: read_return_claim(
        db, context, return_key, authorize=_authorize(policy)))


@SalesReturnRouter.post(
    "/returns/{return_key}/review", response_model=SalesReturnReviewResult,
)
def review_return(return_key: UUID, payload: SalesReturnReview,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("Review_SaleReturn"))):
    return _call(db, lambda: review_return_claim(
        db, context, user.id, return_key, payload,
        authorize=_authorize(policy, "Review_SaleReturn")), commit=True)


@SalesReturnRouter.get(
    "/returns/{return_key}/processing-options",
    response_model=SalesReturnProcessingOptionsRead,
)
def processing_options(return_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("Process_SaleReturn"))):
    return _call(db, lambda: read_return_processing_options(
        db, context, return_key,
        authorize=_authorize(policy, "Process_SaleReturn")))


@SalesReturnRouter.put(
    "/returns/{return_key}/credit-note",
    response_model=SalesReturnCreditNoteResult,
)
def put_return_credit_note(return_key: UUID, payload: SalesReturnCreditNoteCreate,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("Process_SaleReturn"))):
    authorize = _authorize(policy, "Process_SaleReturn")
    try:
        if not db.in_transaction():
            db.begin()
        authorize(db)
        claim = apply_org_filter(db.query(SalesReturnClaim).filter_by(
            org_id=context.org_id, return_key=return_key, is_deleted=False),
            SalesReturnClaim, context).one_or_none()
        if claim is None:
            raise LookupError("Return claim not found")
        mapping = apply_org_filter(db.query(BranchCostPool).filter_by(
            org_id=context.org_id, branch_id=claim.branch_id, is_deleted=False),
            BranchCostPool, context).one_or_none()
        if mapping is None:
            raise PostingConflict("Return store has no exact cost pool")
        stock_runtime = server_stock_runtime()
        cost_runtime = server_cost_runtime()
        stock_claim = stock_runtime.claim_for(db, context, claim.branch_id)
        cost_claim = cost_runtime.claim_for(db, context, mapping.cost_pool_id)
        factory = sessionmaker(bind=db.get_bind())
        branch_id = claim.branch_id
        cost_pool_id = mapping.cost_pool_id
        actor_id = user.id
        db.rollback()

        def current_access(session):
            authorize(session)
            if stock_runtime.claim_for(session, context, branch_id) != stock_claim:
                raise PermissionError("Return-store authority changed")
            if cost_runtime.claim_for(session, context, cost_pool_id) != cost_claim:
                raise PermissionError("Return cost authority changed")

        result = process_return_credit(
            factory, context, actor_id, return_key, payload,
            stock_authority=stock_claim,
            cost_authority=cost_claim,
            authorize=current_access,
        )
        return SalesReturnCreditNoteResult(**result)
    except (StockRuntimeUnavailable, CostRuntimeUnavailable) as error:
        db.rollback()
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback()
        raise _error(error) from error


@SalesReturnRouter.get(
    "/invoices/{invoice_key}/returns", response_model=SalesReturnClaimPage,
)
def invoice_returns(invoice_key: UUID,
        page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: list_invoice_returns(
        db, context, invoice_key, page=page, limit=limit,
        authorize=_authorize(policy)))


@SalesReturnRouter.get(
    "/invoices/{invoice_key}/credit-notes", response_model=SalesCreditNotePage,
)
def invoice_credit_notes(invoice_key: UUID,
        page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: list_invoice_credit_notes(
        db, context, invoice_key, page=page, limit=limit,
        authorize=_authorize(policy)))


@SalesReturnRouter.get(
    "/credit-notes/{credit_note_key}", response_model=SalesCreditNoteRead,
)
def get_credit_note(credit_note_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(return_access),
        user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: read_credit_note(
        db, context, credit_note_key, authorize=_authorize(policy)))
