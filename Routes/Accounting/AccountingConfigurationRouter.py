"""Protected T20A account configuration API; it cannot post or export journals."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from Model.db import get_db
from Schema.AccountingConfigurationSchema import (
    AccountMappingLookupRead,
    AccountMappingRead,
    AccountMappingRevisionRead,
    AccountMappingSave,
    AccountMappingSaveResult,
    AccountRole,
)
from Schema.InventoryLocationSchema import LocationPage
from Services.accounting_configuration_service import (
    get_account_mapping,
    list_account_mapping_revisions,
    list_account_mappings,
    lookup_account_mapping,
    save_account_mapping,
)
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext
from auth.dependencies import get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission


def accounting_access(policy: AccessPolicy = Depends(get_request_policy)):
    if not policy.has("View_Financials"):
        raise HTTPException(403, "Accounting configuration access required")
    return policy


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


AccountingConfigurationRouter = APIRouter(
    prefix="/accounting/configuration",
    tags=["Accounting configuration"],
    dependencies=[
        Depends(require_module("SALES")),
        Depends(accounting_access),
        Depends(private_response),
    ],
)


def _guard(policy: AccessPolicy, manage: bool = False):
    def authorize(db):
        if not policy.has("View_Financials") or (
            manage and not policy.has("Manage_Financials")
        ):
            raise PermissionError("Accounting configuration access required")

    return authorize


def _error(error: Exception):
    if isinstance(error, LookupError):
        return HTTPException(404, str(error))
    if isinstance(error, PermissionError):
        return HTTPException(403, str(error))
    if isinstance(error, PostingConflict):
        return HTTPException(409, str(error))
    if isinstance(error, ValueError):
        return HTTPException(422, str(error))
    return error


def _call(db: Session, action, *, write: bool = False):
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


@AccountingConfigurationRouter.get(
    "/account-mappings", response_model=LocationPage[AccountMappingRead]
)
def account_mappings(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    branch_id: int | None = Query(None, gt=0),
    account_role: AccountRole | None = Query(None),
    db: Session = Depends(get_db),
    context: OrgContext = Depends(get_org_context),
    policy: AccessPolicy = Depends(accounting_access),
    user=Depends(require_permission("View_Financials")),
):
    return _call(
        db,
        lambda: list_account_mappings(
            db,
            context,
            page=page,
            limit=limit,
            branch_id=branch_id,
            account_role=account_role,
            authorize=_guard(policy),
        ),
    )


@AccountingConfigurationRouter.get(
    "/account-mappings/lookup", response_model=AccountMappingLookupRead
)
def account_mapping_lookup(
    branch_id: int = Query(..., gt=0),
    account_role: AccountRole = Query(...),
    db: Session = Depends(get_db),
    context: OrgContext = Depends(get_org_context),
    policy: AccessPolicy = Depends(accounting_access),
    user=Depends(require_permission("View_Financials")),
):
    return _call(
        db,
        lambda: lookup_account_mapping(
            db, context, branch_id, account_role, authorize=_guard(policy)
        ),
    )


@AccountingConfigurationRouter.get(
    "/account-mappings/{mapping_key}", response_model=AccountMappingRead
)
def account_mapping(
    mapping_key: UUID,
    db: Session = Depends(get_db),
    context: OrgContext = Depends(get_org_context),
    policy: AccessPolicy = Depends(accounting_access),
    user=Depends(require_permission("View_Financials")),
):
    return _call(
        db,
        lambda: get_account_mapping(
            db, context, mapping_key, authorize=_guard(policy)
        ),
    )


@AccountingConfigurationRouter.get(
    "/account-mappings/{mapping_key}/revisions",
    response_model=LocationPage[AccountMappingRevisionRead],
)
def account_mapping_revisions(
    mapping_key: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    context: OrgContext = Depends(get_org_context),
    policy: AccessPolicy = Depends(accounting_access),
    user=Depends(require_permission("View_Financials")),
):
    return _call(
        db,
        lambda: list_account_mapping_revisions(
            db,
            context,
            mapping_key,
            page=page,
            limit=limit,
            authorize=_guard(policy),
        ),
    )


@AccountingConfigurationRouter.put(
    "/account-mappings/{mapping_key}", response_model=AccountMappingSaveResult
)
def put_account_mapping(
    mapping_key: UUID,
    payload: AccountMappingSave,
    db: Session = Depends(get_db),
    context: OrgContext = Depends(get_org_context),
    policy: AccessPolicy = Depends(accounting_access),
    user=Depends(require_permission("Manage_Financials")),
):
    outcome = _call(
        db,
        lambda: save_account_mapping(
            db,
            context,
            user.id,
            mapping_key,
            payload,
            authorize=_guard(policy, manage=True),
        ),
        write=True,
    )
    return AccountMappingSaveResult(**outcome.result, replayed=outcome.replayed)
