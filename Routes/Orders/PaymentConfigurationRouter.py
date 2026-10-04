"""Protected payment configuration API. It cannot post or confirm payments."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from Model.db import get_db
from Schema.PaymentConfigurationSchema import (
    BranchOption, LookupRead, MappingRead, MappingSave, MethodRead, MethodSave, SaveResult)
from Schema.InventoryLocationSchema import LocationPage
from Services.inventory_posting_service import PostingConflict
from Services.payment_configuration_service import (
    list_branch_options, list_mappings, list_methods, lookup_receiving_account,
    save_mapping, save_method)
from Utils.org_filter import OrgContext
from auth.dependencies import get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission


def payment_access(policy: AccessPolicy = Depends(get_request_policy)):
    if not policy.has("View_Financials"):
        raise HTTPException(403, "Financial configuration access required")
    return policy


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


PaymentConfigurationRouter = APIRouter(prefix="/sales/payment-configuration",
    tags=["Payment configuration"], dependencies=[Depends(require_module("SALES")),
    Depends(payment_access), Depends(private_response)])


def _guard(policy, manage=False):
    def authorize(db):
        if not policy.has("View_Financials") or (manage and not policy.has("Manage_Financials")):
            raise PermissionError("Financial configuration access required")
    return authorize


def _error(error):
    if isinstance(error, LookupError):
        return HTTPException(404, str(error))
    if isinstance(error, PermissionError):
        return HTTPException(403, str(error))
    if isinstance(error, PostingConflict):
        return HTTPException(409, str(error))
    if isinstance(error, ValueError):
        return HTTPException(422, str(error))
    return error


def _call(db, action, write=False):
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


@PaymentConfigurationRouter.get("/methods", response_model=LocationPage[MethodRead])
def methods(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
            db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
            policy: AccessPolicy = Depends(payment_access),
            user=Depends(require_permission("View_Financials"))):
    return _call(db, lambda: list_methods(db, context, page=page, limit=limit,
                                          authorize=_guard(policy)))


@PaymentConfigurationRouter.get("/branches", response_model=LocationPage[BranchOption])
def branch_options(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                   db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context),
                   policy: AccessPolicy = Depends(payment_access),
                   user=Depends(require_permission("View_Financials"))):
    return _call(db, lambda: list_branch_options(db, context, page=page,
        limit=limit, authorize=_guard(policy)))


@PaymentConfigurationRouter.put("/methods/{method_key}", response_model=SaveResult)
def put_method(method_key: UUID, payload: MethodSave,
               db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
               policy: AccessPolicy = Depends(payment_access),
               user=Depends(require_permission("Manage_Financials"))):
    outcome = _call(db, lambda: save_method(db, context, user.id, method_key,
        payload, authorize=_guard(policy, manage=True)), write=True)
    return SaveResult(**outcome.result, replayed=outcome.replayed)


@PaymentConfigurationRouter.get("/receiving-accounts",
    response_model=LocationPage[MappingRead])
def mappings(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
             branch_id: int | None = Query(None, gt=0),
             db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
             policy: AccessPolicy = Depends(payment_access),
             user=Depends(require_permission("View_Financials"))):
    return _call(db, lambda: list_mappings(db, context, page=page, limit=limit,
        branch_id=branch_id, authorize=_guard(policy)))


@PaymentConfigurationRouter.put("/receiving-accounts/{mapping_key}",
    response_model=SaveResult)
def put_mapping(mapping_key: UUID, payload: MappingSave,
                db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                policy: AccessPolicy = Depends(payment_access),
                user=Depends(require_permission("Manage_Financials"))):
    outcome = _call(db, lambda: save_mapping(db, context, user.id, mapping_key,
        payload, authorize=_guard(policy, manage=True)), write=True)
    return SaveResult(**outcome.result, replayed=outcome.replayed)


@PaymentConfigurationRouter.get("/receiving-account-lookup", response_model=LookupRead)
def receiving_lookup(branch_id: int = Query(..., gt=0), method_key: UUID = Query(...),
                     db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context),
                     policy: AccessPolicy = Depends(payment_access),
                     user=Depends(require_permission("View_Financials"))):
    return _call(db, lambda: lookup_receiving_account(db, context, branch_id,
        method_key, authorize=_guard(policy)))
