"""Recoverable payment confirmation and atomic retail invoice posting."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from Model.db import get_db
from Schema.SalesPostingSchema import (
    SalesPostingAttemptCreate, SalesPostingCreateResult,
    SalesCardConfirmationAppend, SalesPostingAttemptRead,
    SalesPostingFinalize, SalesPostingFinalizeResult, SalesInvoiceRead,
)
from Services.inventory_posting_service import PostingConflict
from Services.sales_posting_service import (
    append_card_confirmation, create_posting_attempt,
    finalize_posting_attempt, read_invoice, read_posting_attempt,
)
from Utils.org_filter import OrgContext
from auth.dependencies import get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission


def posting_access(policy: AccessPolicy = Depends(get_request_policy)):
    required = ("View_Sale", "View_SalesDraft", "View_Product",
                "View_Customer", "View_Personal_Data")
    if (any(not policy.has(name) for name in required)
            or not policy.allows_field_class("PERSONAL")):
        raise HTTPException(403, "Sale, product and customer access required")
    return policy


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


SalesPostingRouter = APIRouter(prefix="/sales", tags=["Sales posting"],
    dependencies=[Depends(require_module("SALES")), Depends(posting_access),
                  Depends(private_response)])


def _authorize(policy, *, write=False, card_confirmation=False):
    def authorize(db):
        required = ("View_Sale", "View_SalesDraft", "View_Product",
                    "View_Customer", "View_Personal_Data")
        if (any(not policy.has(name) for name in required)
                or not policy.allows_field_class("PERSONAL")
                or (write and not policy.has("Post_Sale"))
                or (card_confirmation
                    and not policy.has("Record_ExternalCardConfirmation"))):
            raise PermissionError("Sale posting access required")
    return authorize


def _error(error):
    if isinstance(error, LookupError):
        return HTTPException(404, str(error))
    if isinstance(error, PermissionError):
        return HTTPException(403, str(error))
    if isinstance(error, PostingConflict):
        return HTTPException(409, str(error))
    if isinstance(error, IntegrityError):
        return HTTPException(409,
            "Concurrent sales-posting state changed; reload before retrying")
    if (isinstance(error, DBAPIError)
            and getattr(error.orig, "pgcode", None) == "P0001"):
        return HTTPException(409,
            "Concurrent sales-posting state changed; reload before retrying")
    if isinstance(error, ValueError):
        return HTTPException(422, str(error))
    return error


def _call(db, action, *, write=False):
    try:
        if write and not db.in_transaction():
            db.begin()
        result = action()
        if write:
            db.commit()
        return result
    except Exception as error:
        db.rollback()
        raise _error(error) from error


@SalesPostingRouter.put("/posting-attempts/{attempt_key}",
    response_model=SalesPostingCreateResult)
def put_attempt(attempt_key: UUID, payload: SalesPostingAttemptCreate,
                db: Session = Depends(get_db),
                context: OrgContext = Depends(get_org_context),
                policy: AccessPolicy = Depends(posting_access),
                user=Depends(require_permission("Post_Sale"))):
    if attempt_key != payload.attempt_key:
        raise HTTPException(422, "Path and posting-attempt identities must match")
    return _call(db, lambda: create_posting_attempt(db, context, user.id,
        payload, authorize=_authorize(policy, write=True)), write=True)


@SalesPostingRouter.get("/posting-attempts/{attempt_key}",
    response_model=SalesPostingAttemptRead)
def get_attempt(attempt_key: UUID, db: Session = Depends(get_db),
                context: OrgContext = Depends(get_org_context),
                policy: AccessPolicy = Depends(posting_access),
                user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: read_posting_attempt(db, context, attempt_key,
        authorize=_authorize(policy)))


@SalesPostingRouter.post(
    "/posting-attempts/{attempt_key}/card-confirmations/{confirmation_key}",
    response_model=SalesPostingAttemptRead)
def record_card_confirmation(attempt_key: UUID, confirmation_key: UUID,
                             payload: SalesCardConfirmationAppend,
                             db: Session = Depends(get_db),
                             context: OrgContext = Depends(get_org_context),
                             policy: AccessPolicy = Depends(posting_access),
                             user=Depends(require_permission(
                                 "Record_ExternalCardConfirmation"))):
    if (attempt_key != payload.attempt_key
            or confirmation_key != payload.confirmation_key):
        raise HTTPException(422, "Path and card-confirmation identities must match")
    return _call(db, lambda: append_card_confirmation(db, context, user.id,
        payload, authorize=_authorize(policy, write=True,
            card_confirmation=True)), write=True)


@SalesPostingRouter.post("/posting-attempts/{attempt_key}/finalize",
    response_model=SalesPostingFinalizeResult)
def finalize_attempt(attempt_key: UUID, payload: SalesPostingFinalize,
                     db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context),
                     policy: AccessPolicy = Depends(posting_access),
                     user=Depends(require_permission("Post_Sale"))):
    if attempt_key != payload.attempt_key:
        raise HTTPException(422, "Path and posting-attempt identities must match")
    return _call(db, lambda: finalize_posting_attempt(db, context, user.id,
        payload, authorize=_authorize(policy, write=True)), write=True)


@SalesPostingRouter.get("/invoices/{invoice_key}", response_model=SalesInvoiceRead)
def get_invoice(invoice_key: UUID, db: Session = Depends(get_db),
                context: OrgContext = Depends(get_org_context),
                policy: AccessPolicy = Depends(posting_access),
                user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: read_invoice(db, context, invoice_key,
        authorize=_authorize(policy)))
