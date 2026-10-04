"""Shared bounded catalogue choices; callers supply module-specific authorization."""
from fastapi import HTTPException
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.search_service import search_products_with_total
from Services.sales_product_media import sales_thumbnail
from Utils.org_filter import apply_org_filter


def product_choices(db, context, page, limit, search, *, authorize):
    if not callable(authorize):
        raise ValueError('Product choice authorization required')
    authorize(db)
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Select an allowed company')
    query = apply_org_filter(db.query(Product.id, Product.sku, Product.name, Product.images).filter(
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
        items.append(dict(id=row.id, sku=row.sku, name=row.name, image_signed_url=sales_thumbnail(row.images), policy_version=policy.version if policy else 0,
            base_unit=config.base_unit if config else None, quantity_step=config.quantity_step if config else None,
            units=[config.base_unit] + [unit.unit for unit in config.conversions] if config else []))
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))
