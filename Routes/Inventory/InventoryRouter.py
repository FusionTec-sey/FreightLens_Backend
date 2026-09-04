import logging
from datetime import datetime
from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func

from Model.db import get_db
from Model.containermgmt.Orders.Product import Product, ProductCategory, ProductLink
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.inventory")

InventoryRouter = APIRouter(prefix="/inventory", tags=["Inventory & Product Master"])

# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class CategoryCreateSchema(BaseModel):
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    images: Optional[List[Any]] = None
    attachments: Optional[List[Any]] = None

class CategoryUpdateSchema(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None
    images: Optional[List[Any]] = None
    attachments: Optional[List[Any]] = None

class ProductCreateSchema(BaseModel):
    code: Optional[str] = None
    sku: str
    name: str
    description: Optional[str] = None
    description_quick: Optional[str] = None
    status: Optional[str] = "active"
    category_id: Optional[int] = None
    brand: Optional[str] = None
    model_number: Optional[str] = None
    series: Optional[str] = None
    country_of_origin: Optional[str] = None
    barcode: Optional[str] = None
    hs_code: Optional[str] = None
    duty_rate: Optional[float] = None
    tags: Optional[List[str]] = None
    unit: Optional[str] = "PCS"
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    weight_per_unit: Optional[float] = None
    dimension_unit: Optional[str] = "mm"
    weight_unit: Optional[str] = "kg"
    units_per_box: Optional[float] = None
    box_weight: Optional[float] = None
    unit_cost: Optional[float] = None
    currency: Optional[str] = "USD"
    current_stock: Optional[float] = 0.0
    min_stock_quantity: Optional[float] = 0.0
    max_stock_quantity: Optional[float] = None
    order_threshold_qty: Optional[float] = None
    threshold_qty: Optional[float] = None
    min_quantity_order: Optional[float] = None
    lead_time_days: Optional[int] = None
    default_supplier_id: Optional[int] = None
    is_consumable: Optional[bool] = False
    is_hazardous: Optional[bool] = False
    is_perishable: Optional[bool] = False
    expiry_days: Optional[int] = None
    is_returnable: Optional[bool] = True
    warranty_days: Optional[int] = None

class ProductUpdateSchema(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    description_quick: Optional[str] = None
    status: Optional[str] = None
    category_id: Optional[int] = None
    brand: Optional[str] = None
    model_number: Optional[str] = None
    series: Optional[str] = None
    country_of_origin: Optional[str] = None
    barcode: Optional[str] = None
    hs_code: Optional[str] = None
    duty_rate: Optional[float] = None
    tags: Optional[List[str]] = None
    unit: Optional[str] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    weight_per_unit: Optional[float] = None
    dimension_unit: Optional[str] = None
    weight_unit: Optional[str] = None
    units_per_box: Optional[float] = None
    box_weight: Optional[float] = None
    unit_cost: Optional[float] = None
    currency: Optional[str] = None
    current_stock: Optional[float] = None
    min_stock_quantity: Optional[float] = None
    max_stock_quantity: Optional[float] = None
    order_threshold_qty: Optional[float] = None
    threshold_qty: Optional[float] = None
    min_quantity_order: Optional[float] = None
    lead_time_days: Optional[int] = None
    default_supplier_id: Optional[int] = None
    is_consumable: Optional[bool] = None
    is_hazardous: Optional[bool] = None
    is_perishable: Optional[bool] = None
    expiry_days: Optional[int] = None
    is_returnable: Optional[bool] = None
    warranty_days: Optional[int] = None

class ProductLinkSchema(BaseModel):
    child_product_id: int
    is_variant: Optional[bool] = False
    is_related: Optional[bool] = False
    is_part: Optional[bool] = False
    qty: Optional[float] = None
    sort_order: Optional[int] = 0
    notes: Optional[str] = None

class ProductLinkUpdateSchema(BaseModel):
    is_variant: Optional[bool] = None
    is_related: Optional[bool] = None
    is_part: Optional[bool] = None
    qty: Optional[float] = None
    sort_order: Optional[int] = None
    notes: Optional[str] = None

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_accounts_user(user: User, org_context: OrgContext) -> bool:
    if org_context.is_root:
        return True
    user_roles = [r.name for r in getattr(user, "roles", [])]
    return any(r in ["Administrator", "Admin", "Account", "Accounts", "Accounts_Finance", "Finance"] for r in user_roles)


def _get_descendant_category_ids(db: Session, category_id: int) -> List[int]:
    """Recursively collect the category_id and all its descendant subcategory IDs."""
    ids = [category_id]
    to_check = [category_id]
    while to_check:
        curr = to_check.pop(0)
        children = db.query(ProductCategory.id).filter(
            ProductCategory.parent_id == curr,
            ProductCategory.is_deleted == False
        ).all()
        c_ids = [c[0] for c in children if c[0] not in ids]
        ids.extend(c_ids)
        to_check.extend(c_ids)
    return ids


def _seed_taxonomy_recursive(db: Session, org_id: int, user_id: int, parent_id: int, items: list):
    for item in items:
        existing = db.query(ProductCategory).filter(
            ProductCategory.org_id == org_id,
            ProductCategory.parent_id == parent_id,
            ProductCategory.name == item["name"],
            ProductCategory.is_deleted == False
        ).first()
        if not existing:
            existing = ProductCategory(
                org_id=org_id,
                name=item["name"],
                description=item.get("description"),
                parent_id=parent_id,
                is_subcategory=True,
                created_by=user_id,
                updated_by=user_id
            )
            db.add(existing)
            db.commit()
            db.refresh(existing)
        if item.get("children"):
            _seed_taxonomy_recursive(db, org_id, user_id, existing.id, item["children"])


def _ensure_root_category(db: Session, org_id: int, user_id: int) -> ProductCategory:
    """Ensure the org has a 'Products' root category and standard taxonomy branches."""
    root = db.query(ProductCategory).filter(
        ProductCategory.org_id == org_id,
        ProductCategory.parent_id == None,
        ProductCategory.is_deleted == False,
        ProductCategory.name == "Products"
    ).first()
    if not root:
        root = ProductCategory(
            org_id=org_id,
            name="Products",
            description="Default root category",
            parent_id=None,
            is_subcategory=False,
            created_by=user_id,
            updated_by=user_id
        )
        db.add(root)
        db.commit()
        db.refresh(root)
        logger.info(f"Seeded root 'Products' category for org_id={org_id}")

    # Re-parent any legacy orphan categories to root
    legacy_orphans = db.query(ProductCategory).filter(
        ProductCategory.org_id == org_id,
        ProductCategory.parent_id == None,
        ProductCategory.id != root.id,
        ProductCategory.is_deleted == False
    ).all()
    for orphan in legacy_orphans:
        orphan.parent_id = root.id
        orphan.is_subcategory = True
    if legacy_orphans:
        db.commit()

    # Seed standard catalog hierarchy if subcategories are empty
    standard_taxonomy = [
        {
            "name": "Ceramics & Tiles",
            "description": "Floor, wall, and decorative tiles",
            "children": [
                {
                    "name": "Floor Tiles",
                    "description": "Heavy-duty and decorative floor tiles",
                    "children": [
                        {"name": "Vitrified", "description": "Vitrified floor tiles"},
                        {"name": "Porcelain", "description": "Glazed & polished porcelain tiles"},
                    ]
                },
                {
                    "name": "Wall Tiles",
                    "description": "Ceramic and mosaic wall tiles",
                    "children": []
                }
            ]
        },
        {"name": "Electrical & Lighting", "description": "Cables, switches, fixtures, lighting", "children": []},
        {"name": "Sanitary Ware", "description": "Basins, toilets, faucets, showers", "children": []},
        {"name": "Hardware & Fittings", "description": "Hinges, locks, fasteners, brackets", "children": []},
        {"name": "Plumbing & Pipes", "description": "Pipes, valves, fittings, couplings", "children": []},
        {"name": "Structural Materials", "description": "Steel, cement, lumber, aggregates", "children": []},
    ]
    _seed_taxonomy_recursive(db, org_id, user_id, root.id, standard_taxonomy)

    return root


def _category_to_dict(c: ProductCategory, db: Session) -> dict:
    descendant_ids = _get_descendant_category_ids(db, c.id)
    total_count = db.query(Product).filter(
        Product.category_id.in_(descendant_ids),
        Product.is_deleted == False
    ).count()
    direct_count = db.query(Product).filter(
        Product.category_id == c.id,
        Product.is_deleted == False
    ).count()

    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "parent_id": c.parent_id,
        "is_subcategory": c.is_subcategory,
        "images": c.images or [],
        "attachments": c.attachments or [],
        "products_count": total_count,
        "direct_products_count": direct_count,
    }



def _build_category_tree(cats: list, parent_id=None) -> list:
    """Recursively build a nested category tree from a flat list."""
    tree = []
    for c in cats:
        if c["parent_id"] == parent_id:
            node = dict(c)
            node["children"] = _build_category_tree(cats, parent_id=c["id"])
            tree.append(node)
    return tree


def _link_summary(lnk: ProductLink) -> dict:
    child = lnk.child_product
    return {
        "link_id": lnk.id,
        "product_id": child.id,
        "code": child.code,
        "sku": child.sku,
        "name": child.name,
        "unit": child.unit or "PCS",
        "status": child.status,
        "is_variant": lnk.is_variant,
        "is_related": lnk.is_related,
        "is_part": lnk.is_part,
        "qty": float(lnk.qty) if lnk.qty is not None else None,
        "sort_order": lnk.sort_order,
        "notes": lnk.notes,
    }


def _get_product_links(product_id: int, db: Session) -> dict:
    links = (
        db.query(ProductLink)
        .options(joinedload(ProductLink.child_product))
        .filter(
            ProductLink.parent_product_id == product_id,
            ProductLink.is_deleted == False
        )
        .order_by(ProductLink.sort_order.asc(), ProductLink.id.asc())
        .all()
    )
    variants, related, parts = [], [], []
    for lnk in links:
        s = _link_summary(lnk)
        if lnk.is_variant:
            variants.append(s)
        if lnk.is_related:
            related.append(s)
        if lnk.is_part:
            parts.append(s)
    return {"variants": variants, "related": related, "parts": parts}


def product_to_dict(p: Product, is_accounts: bool = True, db: Session = None, include_links: bool = False) -> dict:
    cat_name = p.category.name if p.category else None
    supplier_name = p.supplier.name if p.supplier else None

    category_path = []
    base_category_name = None
    if p.category and db:
        curr = p.category
        visited = set()
        while curr and curr.id not in visited:
            visited.add(curr.id)
            category_path.insert(0, curr.name)
            if curr.parent_id:
                curr = db.query(ProductCategory).filter(ProductCategory.id == curr.parent_id).first()
            else:
                break
        if category_path:
            base_category_name = category_path[0]

    qty_on_order, qty_received, active_orders_count, recent_pos = 0.0, 0.0, 0, []
    if db:
        active_items = (
            db.query(POItem)
            .join(PurchaseOrder, POItem.po_id == PurchaseOrder.id)
            .filter(
                POItem.product_id == p.id,
                POItem.is_deleted == False,
                PurchaseOrder.is_deleted == False,
                PurchaseOrder.status.notin_(["COMPLETED", "CANCELLED"])
            ).all()
        )
        active_orders_count = len(active_items)
        for item in active_items:
            ordered = float(item.quantity_ordered or 0.0)
            received = float(item.quantity_received or 0.0)
            qty_on_order += max(0.0, ordered - received)
            qty_received += received
            po = item.purchase_order
            if po and len(recent_pos) < 5:
                recent_pos.append({
                    "po_id": po.id, "po_number": po.po_number, "status": po.status,
                    "quantity_ordered": ordered, "quantity_received": received,
                    "eta_date": po.eta_date.isoformat() if po.eta_date else None
                })

    result = {
        "id": p.id, "org_id": p.org_id,
        # Core Identity
        "code": p.code, "sku": p.sku, "name": p.name,
        "description": p.description, "description_quick": p.description_quick,
        "status": p.status or "active",
        "category_id": p.category_id, "category_name": cat_name,
        "base_category_name": base_category_name or cat_name,
        "category_path": " > ".join(category_path) if category_path else cat_name,
        "brand": p.brand, "model_number": p.model_number, "series": p.series,
        "country_of_origin": p.country_of_origin, "barcode": p.barcode,
        "hs_code": p.hs_code,
        "duty_rate": float(p.duty_rate) if p.duty_rate is not None else None,
        "tags": p.tags or [],
        # UOM
        "unit": p.unit or "PCS",
        # Dimensions
        "length": float(p.length) if p.length is not None else None,
        "width": float(p.width) if p.width is not None else None,
        "height": float(p.height) if p.height is not None else None,
        "weight_per_unit": float(p.weight_per_unit) if p.weight_per_unit is not None else None,
        "dimension_unit": p.dimension_unit or "mm",
        "weight_unit": p.weight_unit or "kg",
        "units_per_box": float(p.units_per_box) if p.units_per_box is not None else None,
        "box_weight": float(p.box_weight) if p.box_weight is not None else None,
        # Pricing (role-gated)
        "unit_cost": float(p.unit_cost) if p.unit_cost is not None and is_accounts else None,
        "currency": p.currency or "USD",
        # Stock
        "current_stock": float(p.current_stock or 0.0),
        "min_stock_quantity": float(p.min_stock_quantity or 0.0),
        "max_stock_quantity": float(p.max_stock_quantity) if p.max_stock_quantity is not None else None,
        "order_threshold_qty": float(p.order_threshold_qty) if p.order_threshold_qty is not None else None,
        "threshold_qty": float(p.threshold_qty) if p.threshold_qty is not None else None,
        "min_quantity_order": float(p.min_quantity_order) if p.min_quantity_order is not None else None,
        "lead_time_days": p.lead_time_days,
        "is_low_stock": (
            float(p.current_stock or 0.0) <= float(p.min_stock_quantity or 0.0)
            if p.min_stock_quantity and float(p.min_stock_quantity) > 0 else False
        ),
        # Supplier
        "default_supplier_id": p.default_supplier_id, "supplier_name": supplier_name,
        # Media
        "images": p.images or [], "attachment": p.attachment or [],
        # Flags
        "is_consumable": p.is_consumable, "is_hazardous": p.is_hazardous,
        "is_perishable": p.is_perishable, "expiry_days": p.expiry_days,
        "is_returnable": p.is_returnable, "warranty_days": p.warranty_days,
        # Pipeline
        "qty_on_order": round(qty_on_order, 2), "qty_received": round(qty_received, 2),
        "active_orders_count": active_orders_count, "recent_pos": recent_pos,
        # Audit
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None
    }
    if include_links and db:
        result["links"] = _get_product_links(p.id, db)
    return result


# ── Stats ─────────────────────────────────────────────────────────────────────

@InventoryRouter.get("/stats")
def get_inventory_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    q_prod = apply_org_filter(db.query(Product).filter(Product.is_deleted == False), Product, org_context)
    total_products = q_prod.count()
    q_cat = apply_org_filter(db.query(ProductCategory).filter(ProductCategory.is_deleted == False), ProductCategory, org_context)
    total_categories = q_cat.count()
    low_stock_count = q_prod.filter(
        Product.min_stock_quantity > 0,
        Product.current_stock <= Product.min_stock_quantity
    ).count()
    q_items = (
        db.query(func.coalesce(func.sum(POItem.quantity_ordered - POItem.quantity_received), 0))
        .join(PurchaseOrder, POItem.po_id == PurchaseOrder.id)
        .filter(POItem.product_id.isnot(None), POItem.is_deleted == False,
                PurchaseOrder.is_deleted == False, PurchaseOrder.status.notin_(["COMPLETED", "CANCELLED"]))
    )
    if not org_context.is_root:
        q_items = q_items.filter(PurchaseOrder.org_id == org_context.org_id)
    return {
        "total_products": total_products, "total_categories": total_categories,
        "low_stock_count": low_stock_count,
        "total_on_order": round(float(q_items.scalar() or 0.0), 2)
    }


# ── Product Lookup ────────────────────────────────────────────────────────────

@InventoryRouter.get("/lookup")
def lookup_products(
    q: Optional[str] = Query(None),
    supplier_id: Optional[int] = Query(None),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """Autocomplete for PO / form creation. Returns active products only."""
    query = db.query(Product).filter(Product.is_deleted == False, Product.status == "active")
    query = apply_org_filter(query, Product, org_context)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(
            Product.sku.ilike(term), Product.code.ilike(term),
            Product.name.ilike(term), Product.brand.ilike(term), Product.barcode.ilike(term)
        ))
    if supplier_id:
        query = query.filter(Product.default_supplier_id == supplier_id)
    prods = query.order_by(Product.name.asc()).limit(limit).all()
    is_acc = is_accounts_user(current_user, org_context)
    return [{
        "id": p.id, "code": p.code, "sku": p.sku, "name": p.name,
        "description_quick": p.description_quick, "unit": p.unit or "PCS",
        "brand": p.brand, "category_id": p.category_id,
        "default_supplier_id": p.default_supplier_id,
        "current_stock": float(p.current_stock or 0.0),
        "unit_cost": float(p.unit_cost) if p.unit_cost is not None and is_acc else None,
        "currency": p.currency or "USD"
    } for p in prods]


# ── Products CRUD ─────────────────────────────────────────────────────────────

@InventoryRouter.get("/products")
def list_products(
    search: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    supplier_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="active | inactive"),
    low_stock_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    query = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.supplier))
        .filter(Product.is_deleted == False)
    )
    query = apply_org_filter(query, Product, org_context)
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(or_(
            Product.sku.ilike(s), Product.code.ilike(s), Product.name.ilike(s),
            Product.brand.ilike(s), Product.description.ilike(s),
            Product.barcode.ilike(s), Product.hs_code.ilike(s)
        ))
    if category_id:
        descendant_ids = _get_descendant_category_ids(db, category_id)
        query = query.filter(Product.category_id.in_(descendant_ids))
    if supplier_id:
        query = query.filter(Product.default_supplier_id == supplier_id)
    if status:
        query = query.filter(Product.status == status)
    if low_stock_only:
        query = query.filter(Product.min_stock_quantity > 0, Product.current_stock <= Product.min_stock_quantity)
    total_count = query.count()
    items = query.order_by(Product.name.asc()).offset((page - 1) * limit).limit(limit).all()
    is_acc = is_accounts_user(current_user, org_context)
    return {
        "items": [product_to_dict(p, is_accounts=is_acc, db=db) for p in items],
        "total": total_count, "page": page, "limit": limit,
        "pages": (total_count + limit - 1) // limit
    }


@InventoryRouter.get("/products/{product_id}")
def get_product_detail(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    prod = apply_org_filter(
        db.query(Product).options(joinedload(Product.category), joinedload(Product.supplier))
        .filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    is_acc = is_accounts_user(current_user, org_context)
    return product_to_dict(prod, is_accounts=is_acc, db=db, include_links=True)


@InventoryRouter.post("/products")
def create_product(
    payload: ProductCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    target_org_id = org_context.org_id or 1
    existing = db.query(Product).filter(
        Product.org_id == target_org_id, Product.sku == payload.sku.strip().upper(), Product.is_deleted == False
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"A product with SKU '{payload.sku}' already exists.")

    new_prod = Product(
        org_id=target_org_id,
        code=payload.code.strip().upper() if payload.code else None,
        sku=payload.sku.strip().upper(),
        name=payload.name.strip(),
        description=payload.description,
        description_quick=payload.description_quick,
        status=payload.status or "active",
        category_id=payload.category_id,
        brand=payload.brand.strip() if payload.brand else None,
        model_number=payload.model_number,
        series=payload.series,
        country_of_origin=payload.country_of_origin.upper() if payload.country_of_origin else None,
        barcode=payload.barcode,
        hs_code=payload.hs_code,
        duty_rate=payload.duty_rate,
        tags=payload.tags or [],
        unit=payload.unit.strip().upper() if payload.unit else "PCS",
        length=payload.length, width=payload.width, height=payload.height,
        weight_per_unit=payload.weight_per_unit,
        dimension_unit=payload.dimension_unit or "mm",
        weight_unit=payload.weight_unit or "kg",
        units_per_box=payload.units_per_box, box_weight=payload.box_weight,
        unit_cost=payload.unit_cost, currency=payload.currency or "USD",
        current_stock=payload.current_stock or 0.0,
        min_stock_quantity=payload.min_stock_quantity or 0.0,
        max_stock_quantity=payload.max_stock_quantity,
        order_threshold_qty=payload.order_threshold_qty,
        threshold_qty=payload.threshold_qty,
        min_quantity_order=payload.min_quantity_order,
        lead_time_days=payload.lead_time_days,
        default_supplier_id=payload.default_supplier_id,
        is_consumable=payload.is_consumable or False,
        is_hazardous=payload.is_hazardous or False,
        is_perishable=payload.is_perishable or False,
        expiry_days=payload.expiry_days,
        is_returnable=payload.is_returnable if payload.is_returnable is not None else True,
        warranty_days=payload.warranty_days,
        created_by=current_user.id, updated_by=current_user.id
    )
    db.add(new_prod)
    db.commit()
    db.refresh(new_prod)
    is_acc = is_accounts_user(current_user, org_context)
    return product_to_dict(new_prod, is_accounts=is_acc, db=db)


@InventoryRouter.put("/products/{product_id}")
def update_product(
    product_id: int,
    payload: ProductUpdateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    prod = apply_org_filter(
        db.query(Product).filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    updatable = [
        "code", "name", "description", "description_quick", "status",
        "category_id", "brand", "model_number", "series", "country_of_origin",
        "barcode", "hs_code", "duty_rate", "tags", "unit",
        "length", "width", "height", "weight_per_unit", "dimension_unit", "weight_unit",
        "units_per_box", "box_weight", "currency",
        "current_stock", "min_stock_quantity", "max_stock_quantity",
        "order_threshold_qty", "threshold_qty", "min_quantity_order", "lead_time_days",
        "default_supplier_id",
        "is_consumable", "is_hazardous", "is_perishable", "expiry_days",
        "is_returnable", "warranty_days"
    ]
    for field in updatable:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(prod, field, val)
    if payload.unit_cost is not None and is_accounts_user(current_user, org_context):
        prod.unit_cost = payload.unit_cost

    prod.updated_by = current_user.id
    prod.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prod)
    is_acc = is_accounts_user(current_user, org_context)
    return product_to_dict(prod, is_accounts=is_acc, db=db)


@InventoryRouter.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    prod = apply_org_filter(
        db.query(Product).filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    prod.is_deleted = True
    prod.updated_by = current_user.id
    prod.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Product deleted successfully"}


# ── Product Links CRUD ────────────────────────────────────────────────────────

@InventoryRouter.get("/products/{product_id}/links")
def get_product_links_endpoint(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """Get all links for a product grouped into variants, related items, and BOM parts."""
    prod = apply_org_filter(
        db.query(Product).filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    return _get_product_links(product_id, db)


@InventoryRouter.post("/products/{product_id}/links")
def add_product_link(
    product_id: int,
    payload: ProductLinkSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Add a variant, related item, or BOM part link.
    If a link already exists for this (parent, child) pair, flags are merged (OR'd together).
    """
    target_org_id = org_context.org_id or 1
    if payload.child_product_id == product_id:
        raise HTTPException(status_code=400, detail="Cannot link a product to itself")

    parent = apply_org_filter(
        db.query(Product).filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent product not found")

    child = apply_org_filter(
        db.query(Product).filter(Product.id == payload.child_product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child product not found")

    existing = db.query(ProductLink).filter(
        ProductLink.parent_product_id == product_id,
        ProductLink.child_product_id == payload.child_product_id,
        ProductLink.is_deleted == False
    ).first()

    if existing:
        if payload.is_variant:
            existing.is_variant = True
        if payload.is_related:
            existing.is_related = True
        if payload.is_part:
            existing.is_part = True
        if payload.qty is not None:
            existing.qty = payload.qty
        if payload.notes is not None:
            existing.notes = payload.notes
        existing.sort_order = payload.sort_order or 0
        existing.updated_by = current_user.id
        existing.updated_at = datetime.utcnow()
        db.commit()
        return {"message": "Link updated", "link_id": existing.id}

    new_link = ProductLink(
        org_id=target_org_id,
        parent_product_id=product_id,
        child_product_id=payload.child_product_id,
        is_variant=payload.is_variant or False,
        is_related=payload.is_related or False,
        is_part=payload.is_part or False,
        qty=payload.qty,
        sort_order=payload.sort_order or 0,
        notes=payload.notes,
        created_by=current_user.id, updated_by=current_user.id
    )
    db.add(new_link)
    db.commit()
    db.refresh(new_link)
    return {"message": "Link created", "link_id": new_link.id}


@InventoryRouter.put("/products/{product_id}/links/{link_id}")
def update_product_link(
    product_id: int, link_id: int,
    payload: ProductLinkUpdateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    link = db.query(ProductLink).filter(
        ProductLink.id == link_id, ProductLink.parent_product_id == product_id,
        ProductLink.is_deleted == False
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    for field in ["is_variant", "is_related", "is_part", "qty", "sort_order", "notes"]:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(link, field, val)
    link.updated_by = current_user.id
    link.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Link updated"}


@InventoryRouter.delete("/products/{product_id}/links/{link_id}")
def delete_product_link(
    product_id: int, link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    link = db.query(ProductLink).filter(
        ProductLink.id == link_id, ProductLink.parent_product_id == product_id,
        ProductLink.is_deleted == False
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    link.is_deleted = True
    link.updated_by = current_user.id
    link.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Link removed"}


# ── Categories CRUD ───────────────────────────────────────────────────────────

@InventoryRouter.get("/categories")
def list_categories(
    flat: bool = Query(False, description="Return flat list instead of nested tree"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Returns category tree (default) or flat list.
    Auto-seeds the 'Products' root category per org if missing.
    """
    target_org_id = org_context.org_id or 1
    _ensure_root_category(db, target_org_id, current_user.id)
    query = apply_org_filter(
        db.query(ProductCategory).filter(ProductCategory.is_deleted == False),
        ProductCategory, org_context
    )
    cats = query.order_by(ProductCategory.name.asc()).all()
    flat_list = [_category_to_dict(c, db) for c in cats]
    return flat_list if flat else _build_category_tree(flat_list, parent_id=None)


@InventoryRouter.post("/categories")
def create_category(
    payload: CategoryCreateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    target_org_id = org_context.org_id or 1
    parent_id = payload.parent_id
    if parent_id is None:
        root = _ensure_root_category(db, target_org_id, current_user.id)
        parent_id = root.id

    new_cat = ProductCategory(
        org_id=target_org_id, name=payload.name.strip(),
        description=payload.description, parent_id=parent_id, is_subcategory=True,
        images=payload.images or [], attachments=payload.attachments or [],
        created_by=current_user.id, updated_by=current_user.id
    )
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    return _category_to_dict(new_cat, db)


@InventoryRouter.put("/categories/{category_id}")
def update_category(
    category_id: int, payload: CategoryUpdateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    cat = apply_org_filter(
        db.query(ProductCategory).filter(ProductCategory.id == category_id, ProductCategory.is_deleted == False),
        ProductCategory, org_context
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    # Protect root
    if cat.parent_id is None and cat.name == "Products":
        if payload.name and payload.name.strip() != "Products":
            raise HTTPException(status_code=400, detail="Cannot rename the root 'Products' category")
        if payload.parent_id is not None:
            raise HTTPException(status_code=400, detail="Cannot move the root 'Products' category")

    if payload.name is not None:
        cat.name = payload.name.strip()
    if payload.description is not None:
        cat.description = payload.description
    if payload.parent_id is not None:
        cat.parent_id = payload.parent_id
        cat.is_subcategory = True
    if payload.images is not None:
        cat.images = payload.images
    if payload.attachments is not None:
        cat.attachments = payload.attachments

    cat.updated_by = current_user.id
    cat.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cat)
    return _category_to_dict(cat, db)


@InventoryRouter.delete("/categories/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    cat = apply_org_filter(
        db.query(ProductCategory).filter(ProductCategory.id == category_id, ProductCategory.is_deleted == False),
        ProductCategory, org_context
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    if cat.parent_id is None and cat.name == "Products":
        raise HTTPException(status_code=400, detail="Cannot delete the root 'Products' category")

    target_org_id = getattr(org_context, "selected_org_id", None) or getattr(org_context, "current_org_id", None) or getattr(org_context, "org_id", 1) or 1
    root = _ensure_root_category(db, target_org_id, current_user.id)

    # Move all products in this category to default 'Products' category
    reparented_count = db.query(Product).filter(
        Product.category_id == category_id,
        Product.is_deleted == False
    ).update({Product.category_id: root.id}, synchronize_session=False)

    # If category has subcategories, re-parent them to this category's parent (or root)
    new_parent_id = cat.parent_id or root.id
    db.query(ProductCategory).filter(
        ProductCategory.parent_id == category_id,
        ProductCategory.is_deleted == False
    ).update({ProductCategory.parent_id: new_parent_id}, synchronize_session=False)

    cat.is_deleted = True
    cat.updated_by = current_user.id
    cat.updated_at = datetime.utcnow()
    db.commit()
    return {
        "message": f"Category '{cat.name}' deleted. {reparented_count} product(s) moved to default '{root.name}' category."
    }

