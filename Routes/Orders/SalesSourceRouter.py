"""Bounded selectors over existing source records; no sales-owned catalogue."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Schema.InventoryLocationSchema import LocationPage
from Schema.SalesSourceSchema import SalesBranchChoice, SalesProductChoice
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.search_service import search_products_with_total
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
             context: OrgContext = Depends(get_org_context)):
    allowed(context)
    query = apply_org_filter(db.query(Product.id, Product.sku, Product.name).filter(
        Product.org_id == context.org_id, Product.is_deleted.is_(False),
        Product.is_shared.is_(False), Product.status == 'active'), Product, context)
    if search.strip():
        try:
            hits, total = search_products_with_total(search.strip(),
                filters=[f'org_id = {context.org_id}', 'is_deleted = false', 'status = active'],
                limit=limit, offset=(page-1)*limit, strict_public=True)
            if len(hits) > limit or any(type(hit.get('id')) is not int or hit.get('org_id') != context.org_id for hit in hits):
                raise RuntimeError('Invalid search scope')
            keys = [hit['id'] for hit in hits]
            found = {row.id: row for row in query.filter(Product.id.in_(keys)).all()} if keys else {}
            if len(found) != len(keys): raise RuntimeError('Stale product search')
            rows = [found[key] for key in keys]
        except RuntimeError as error:
            raise HTTPException(503, 'Product search unavailable or stale. Clear search to browse, or retry.') from error
    else:
        total = query.count()
        rows = query.order_by(Product.name, Product.id).offset((page-1)*limit).limit(limit).all()
    model = ProductPolicyActivation
    policies = db.query(model).filter(model.org_id == context.org_id, model.is_deleted.is_(False),
        model.product_id.in_([row.id for row in rows])).distinct(model.product_id).order_by(model.product_id, model.version.desc()).all() if rows else []
    by_product = {row.product_id: row for row in policies}
    items = []
    for row in rows:
        policy = by_product.get(row.id)
        config = InventoryPolicyConfig.model_validate(policy.config) if policy else None
        items.append(dict(id=row.id, sku=row.sku, name=row.name, policy_version=policy.version if policy else 0,
            base_unit=config.base_unit if config else None, quantity_step=config.quantity_step if config else None,
            units=[config.base_unit] + [unit.unit for unit in config.conversions] if config else []))
    return page_result(items, total, page, limit)
