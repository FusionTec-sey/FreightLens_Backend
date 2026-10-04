"""Permission-scoped retail collection and partial physical handover."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from Model.db import get_db
from Model.containermgmt.Inventory.CostPool import BranchCostPool
from Schema.SalesCollectionSchema import (
    SalesCollectionCreate,
    SalesCollectionCreateResult,
    SalesCollectionOptionsRead,
    SalesCollectionRead,
)
from Services.cost_runtime_service import CostRuntimeUnavailable, server_cost_runtime
from Services.inventory_posting_service import PostingConflict
from Services.sales_collection_service import (
    list_invoice_collections,
    post_collection,
    read_collection,
    read_collection_options,
)
from Services.stock_runtime_service import StockRuntimeUnavailable, server_stock_runtime
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission


def collection_access(policy: AccessPolicy = Depends(get_request_policy)):
    required = ("View_Sale", "View_Product", "View_Customer",
                "View_Personal_Data")
    if (any(not policy.has(name) for name in required)
            or not policy.allows_field_class("PERSONAL")):
        raise HTTPException(403, "Sale, product and customer access required")
    return policy


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


SalesCollectionRouter = APIRouter(prefix="/sales", tags=["Sales collection"],
    dependencies=[Depends(require_module("SALES")), Depends(collection_access),
                  Depends(private_response)])


def _authorize(policy, *, write=False):
    def authorize(db):
        required = ("View_Sale", "View_Product", "View_Customer",
                    "View_Personal_Data")
        if (any(not policy.has(name) for name in required)
                or not policy.allows_field_class("PERSONAL")
                or (write and not policy.has("Collect_Sale"))):
            raise PermissionError("Sales collection access required")
    return authorize


def _error(error):
    if isinstance(error, LookupError):
        return HTTPException(404, str(error))
    if isinstance(error, PermissionError):
        return HTTPException(403, str(error))
    if isinstance(error, (PostingConflict, IntegrityError)):
        return HTTPException(409,
            "Collection state changed; reload before retrying")
    if (isinstance(error, DBAPIError)
            and getattr(error.orig, "pgcode", None) == "P0001"):
        return HTTPException(409,
            "Collection state changed; reload before retrying")
    if isinstance(error, ValueError):
        return HTTPException(422, str(error))
    return error


def _call(db, action):
    try:
        return action()
    except Exception as error:
        db.rollback()
        raise _error(error) from error


@SalesCollectionRouter.get(
    "/invoices/{invoice_key}/collection-options",
    response_model=SalesCollectionOptionsRead,
)
def collection_options(invoice_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(collection_access),
        user=Depends(require_permission("Collect_Sale"))):
    return _call(db, lambda: read_collection_options(
        db, context, user.id, invoice_key,
        authorize=_authorize(policy, write=True)))


@SalesCollectionRouter.put(
    "/collections/{collection_key}",
    response_model=SalesCollectionCreateResult,
)
def put_collection(collection_key: UUID, payload: SalesCollectionCreate,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(collection_access),
        user=Depends(require_permission("Collect_Sale"))):
    if collection_key != payload.collection_key:
        raise HTTPException(422, "Path and collection identities must match")
    try:
        if not db.in_transaction():
            db.begin()
        authorize = _authorize(policy, write=True)
        authorize(db)
        mapping = apply_org_filter(db.query(BranchCostPool).filter_by(
            org_id=context.org_id, branch_id=payload.branch_id,
            is_deleted=False), BranchCostPool, context).one_or_none()
        if mapping is None:
            raise ValueError("An exact collection-store cost pool is required")
        cost_pool_id = mapping.cost_pool_id
        stock_runtime = server_stock_runtime()
        cost_runtime = server_cost_runtime()
        stock_claim = stock_runtime.claim_for(db, context, payload.branch_id)
        cost_claim = cost_runtime.claim_for(db, context, cost_pool_id)
        factory = sessionmaker(bind=db.get_bind())
        actor_id = user.id
        db.rollback()

        def current_access(session):
            authorize(session)
            if stock_runtime.claim_for(
                    session, context, payload.branch_id) != stock_claim:
                raise PermissionError("Collection-store authority changed")
            if cost_runtime.claim_for(
                    session, context, cost_pool_id) != cost_claim:
                raise PermissionError("Collection cost authority changed")

        outcome = post_collection(factory, context, actor_id, payload,
            stock_authority=stock_claim, cost_authority=cost_claim,
            authorize=current_access)
        return SalesCollectionCreateResult(
            collection=outcome.result, replayed=outcome.replayed)
    except (StockRuntimeUnavailable, CostRuntimeUnavailable) as error:
        db.rollback()
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback()
        raise _error(error) from error


@SalesCollectionRouter.get(
    "/collections/{collection_key}", response_model=SalesCollectionRead)
def get_collection(collection_key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(collection_access),
        user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: read_collection(db, context, collection_key,
        authorize=_authorize(policy)))


@SalesCollectionRouter.get(
    "/invoices/{invoice_key}/collections",
    response_model=list[SalesCollectionRead],
)
def get_invoice_collections(invoice_key: UUID,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(collection_access),
        user=Depends(require_permission("View_Sale"))):
    return _call(db, lambda: list_invoice_collections(
        db, context, invoice_key, authorize=_authorize(policy)))
