"""Private sales-invoice artifact and physical print queue endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from Model.db import get_db
from Schema.SalesInvoicePrintSchema import (
    SalesInvoicePrintHandoff, SalesInvoicePrintJobPage, SalesInvoicePrintJobRead,
    SalesInvoicePrintOptions, SalesInvoicePrintRequest, SalesInvoicePrintResult,
    SalesInvoicePrintTransition,
)
from Services.inventory_posting_service import PostingConflict
from Services.sales_invoice_print_service import (
    create_invoice_print_job, handoff_print_job, list_invoice_print_jobs,
    read_artifact_bytes, read_print_job, read_print_options, resolve_print_job,
)
from Utils.org_filter import OrgContext
from auth.dependencies import get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission


def print_access(policy: AccessPolicy = Depends(get_request_policy)):
    required = ("View_Sale", "View_Product", "View_Customer",
                "View_Personal_Data", "Print_SaleInvoice")
    if (any(not policy.has(name) for name in required)
            or not policy.allows_field_class("PERSONAL")):
        raise HTTPException(403, "Sales invoice print access required")
    return policy


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


SalesInvoicePrintRouter = APIRouter(
    prefix="/sales", tags=["Sales invoice printing"],
    dependencies=[Depends(require_module("SALES")), Depends(print_access),
                  Depends(private_response)],
)


def _authorize(policy, *, resolve=False):
    def authorize(db):
        required = ("View_Sale", "View_Product", "View_Customer",
                    "View_Personal_Data", "Print_SaleInvoice")
        if (any(not policy.has(name) for name in required)
                or not policy.allows_field_class("PERSONAL")
                or (resolve and not policy.has("Resolve_SalePrint"))):
            raise PermissionError("Sales invoice print access required")
    return authorize


def _error(error):
    if isinstance(error, LookupError):
        return HTTPException(404, str(error))
    if isinstance(error, PermissionError):
        return HTTPException(403, str(error))
    if isinstance(error, (PostingConflict, IntegrityError)):
        return HTTPException(409, str(error))
    if isinstance(error, DBAPIError) and getattr(error.orig, "pgcode", None) == "P0001":
        return HTTPException(409, "Invoice print state changed; reload and retry")
    if isinstance(error, ValueError):
        return HTTPException(422, str(error))
    return error


def _call(db, action):
    try:
        return action()
    except Exception as error:
        db.rollback()
        raise _error(error) from error


@SalesInvoicePrintRouter.get(
    "/invoices/{invoice_key}/print-options", response_model=SalesInvoicePrintOptions)
def get_print_options(invoice_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(print_access),
        user=Depends(require_permission("Print_SaleInvoice"))):
    return _call(db, lambda: read_print_options(
        db, context, invoice_key, authorize=_authorize(policy)))


@SalesInvoicePrintRouter.put(
    "/invoices/{invoice_key}/print-jobs/{job_key}", response_model=SalesInvoicePrintResult)
def put_print_job(invoice_key: UUID, job_key: UUID, payload: SalesInvoicePrintRequest,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(print_access),
        user=Depends(require_permission("Print_SaleInvoice"))):
    if invoice_key != payload.invoice_key or job_key != payload.job_key:
        raise HTTPException(422, "Path and invoice print identities must match")
    try:
        factory = sessionmaker(bind=db.get_bind())
        db.rollback()
        outcome = create_invoice_print_job(factory, context, user.id, payload,
            authorize=_authorize(policy))
        return {"job": outcome.result, "replayed": outcome.replayed}
    except Exception as error:
        db.rollback()
        raise _error(error) from error


@SalesInvoicePrintRouter.get(
    "/print-jobs/{job_key}", response_model=SalesInvoicePrintJobRead)
def get_print_job(job_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(print_access),
        user=Depends(require_permission("Print_SaleInvoice"))):
    return _call(db, lambda: read_print_job(
        db, context, job_key, authorize=_authorize(policy)))


@SalesInvoicePrintRouter.get(
    "/invoices/{invoice_key}/print-jobs", response_model=SalesInvoicePrintJobPage)
def get_print_jobs(invoice_key: UUID, page: int = Query(1, ge=1),
        limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(print_access),
        user=Depends(require_permission("Print_SaleInvoice"))):
    return _call(db, lambda: list_invoice_print_jobs(
        db, context, invoice_key, page, limit, authorize=_authorize(policy)))


@SalesInvoicePrintRouter.get("/invoice-artifacts/{artifact_key}/download")
def download_invoice_artifact(artifact_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(print_access),
        user=Depends(require_permission("Print_SaleInvoice"))):
    row, content = _call(db, lambda: read_artifact_bytes(
        db, context, artifact_key, authorize=_authorize(policy)))
    return Response(content, media_type="application/pdf", headers={
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'inline; filename="invoice-{row.artifact_kind.lower()}-{row.copy_number}.pdf"',
        "X-Content-Type-Options": "nosniff",
    })


@SalesInvoicePrintRouter.post("/print-jobs/{job_key}/handoff")
def handoff_invoice_print(job_key: UUID, payload: SalesInvoicePrintHandoff,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(print_access),
        user=Depends(require_permission("Print_SaleInvoice"))):
    try:
        factory = sessionmaker(bind=db.get_bind())
        db.rollback()
        outcome = handoff_print_job(factory, context, user.id, job_key, payload,
            authorize=_authorize(policy))
        if outcome.replayed:
            raise PostingConflict(
                "This print handoff is already uncertain; resolve it before creating a COPY")
        artifact_key = outcome.result["artifact"]["artifact_key"]
        row, content = read_artifact_bytes(db, context, artifact_key,
            authorize=_authorize(policy))
        return Response(content, media_type="application/pdf", headers={
            "Cache-Control": "private, no-store", "X-Print-State": "UNCERTAIN",
            "X-Print-Job-Version": str(outcome.result["version"]),
            "Content-Disposition": f'inline; filename="invoice-{row.artifact_kind.lower()}-{row.copy_number}.pdf"',
            "X-Content-Type-Options": "nosniff",
        })
    except Exception as error:
        db.rollback()
        raise _error(error) from error


@SalesInvoicePrintRouter.post(
    "/print-jobs/{job_key}/resolve", response_model=SalesInvoicePrintResult)
def resolve_invoice_print(job_key: UUID, payload: SalesInvoicePrintTransition,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(print_access),
        user=Depends(require_permission("Resolve_SalePrint"))):
    try:
        factory = sessionmaker(bind=db.get_bind())
        db.rollback()
        outcome = resolve_print_job(factory, context, user.id, job_key, payload,
            authorize=_authorize(policy, resolve=True))
        return {"job": outcome.result, "replayed": outcome.replayed}
    except Exception as error:
        db.rollback()
        raise _error(error) from error
