"""Bounded selectors over existing source records; no sales-owned catalogue."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.Location import InventoryBranch
from Schema.InventoryLocationSchema import LocationPage
from Schema.SalesSourceSchema import SalesBranchChoice, SalesProductChoice
from Services.product_choice_service import product_choices
from Routes.Orders.SalesIntentRouter import draft_access
from Routes.MasterData.CustomerRouter import private_response
from auth.module_guard import require_module
from auth.dependencies import get_org_context
from Utils.org_filter import OrgContext, apply_org_filter

SalesSourceRouter = APIRouter(prefix='/sales/draft-sources', tags=['Sales drafts'], dependencies=[
    Depends(require_module('SALES')), Depends(draft_access), Depends(private_response)])


def page_result(items, total, page, limit):
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


def allowed(context):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Select an allowed company')


@SalesSourceRouter.get('/branches', response_model=LocationPage[SalesBranchChoice])
def branches(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
             db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context)):
    allowed(context)
    query = apply_org_filter(db.query(InventoryBranch).filter_by(org_id=context.org_id,
        is_deleted=False, is_active=True, kind='STORE'), InventoryBranch, context)
    total = query.count()
    rows = query.order_by(InventoryBranch.name, InventoryBranch.id).offset((page-1)*limit).limit(limit).all()
    return page_result([dict(id=row.id, code=row.code, name=row.name) for row in rows], total, page, limit)


@SalesSourceRouter.get('/products', response_model=LocationPage[SalesProductChoice])
def products(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
             search: str = Query('', max_length=160), db: Session = Depends(get_db),
             context: OrgContext = Depends(get_org_context), policy=Depends(draft_access)):
    allowed(context)
    return product_choices(db, context, page, limit, search, authorize=lambda session: draft_access(policy))
