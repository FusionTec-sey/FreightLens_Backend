import logging
import csv
import io
from datetime import datetime
from typing import Optional, List, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func

from Model.db import get_db
from Model.containermgmt.Orders.Product import Product, ProductCategory, ProductLink
from Model.containermgmt.Orders.ProductSupplier import ProductSupplier
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import is_financial_user, has_permission
from Utils.org_filter import OrgContext, apply_org_filter
from Utils.blob_storage import blob_storage
from Services.search_service import sync_product_document, remove_product_document, search_products, search_products_with_total

logger = logging.getLogger("containerMgmt.inventory")

InventoryRouter = APIRouter(prefix="/inventory", tags=["Inventory & Product Master"])

PRODUCT_MEDIA_TTL = 24 * 60 * 60


def _signed_media_url(value: Optional[str]) -> Optional[str]:
    if not value or value.startswith(("http://", "https://", "blob:", "data:")):
        return value
    return blob_storage.signed_url(value, ttl=PRODUCT_MEDIA_TTL)


def _signed_media_items(items: list) -> list:
    signed_items = []
    for item in items or []:
        if not isinstance(item, dict):
            signed_items.append(item)
            continue
        signed_item = dict(item)
        media_key = item.get("file_url") or item.get("url")
        signed_item["file_signed_url"] = _signed_media_url(media_key)
        signed_items.append(signed_item)
    return signed_items

# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class ProductSupplierSchema(BaseModel):
    id: Optional[int] = None
    supplier_id: int
    factory_code: Optional[str] = None
    vendor_product_name: Optional[str] = None
    unit_cost: Optional[float] = None
    currency: Optional[str] = "USD"
    min_order_qty: Optional[float] = None
    lead_time_days: Optional[int] = None
    is_default: Optional[bool] = False
    notes: Optional[str] = None

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
    sku: Optional[str] = None
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
    # Retail / Primary Packaging
    retail_packaging_type: Optional[str] = None
    gross_weight_per_unit: Optional[float] = None
    # Wholesale / Inner Packaging
    wholesale_packaging_type: Optional[str] = None
    units_per_inner: Optional[float] = None
    inner_length: Optional[float] = None
    inner_width: Optional[float] = None
    inner_height: Optional[float] = None
    inner_weight: Optional[float] = None
    # Import / Master Shipping Packaging
    import_packaging_type: Optional[str] = None
    master_length: Optional[float] = None
    master_width: Optional[float] = None
    master_height: Optional[float] = None
    master_tare_weight: Optional[float] = None
    # Palletization & Container Loading
    pallet_type: Optional[str] = None
    cartons_per_layer: Optional[int] = None
    layers_per_pallet: Optional[int] = None
    total_cartons_per_pallet: Optional[int] = None
    max_stacking_layers: Optional[int] = None
    est_qty_20ft: Optional[float] = None
    est_qty_40hc: Optional[float] = None
    # Warehouse Coordinates
    warehouse_location: Optional[str] = None
    default_bin: Optional[str] = None
    packaging_specs: Optional[Dict[str, Any]] = None

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
    images: Optional[List[Any]] = None
    videos: Optional[List[Any]] = None
    attachment: Optional[List[Any]] = None
    factory_code: Optional[str] = None
    suppliers: Optional[List[ProductSupplierSchema]] = None

class ProductUpdateSchema(BaseModel):
    sku: Optional[str] = None
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
    # Retail / Primary Packaging
    retail_packaging_type: Optional[str] = None
    gross_weight_per_unit: Optional[float] = None
    # Wholesale / Inner Packaging
    wholesale_packaging_type: Optional[str] = None
    units_per_inner: Optional[float] = None
    inner_length: Optional[float] = None
    inner_width: Optional[float] = None
    inner_height: Optional[float] = None
    inner_weight: Optional[float] = None
    # Import / Master Shipping Packaging
    import_packaging_type: Optional[str] = None
    master_length: Optional[float] = None
    master_width: Optional[float] = None
    master_height: Optional[float] = None
    master_tare_weight: Optional[float] = None
    # Palletization & Container Loading
    pallet_type: Optional[str] = None
    cartons_per_layer: Optional[int] = None
    layers_per_pallet: Optional[int] = None
    total_cartons_per_pallet: Optional[int] = None
    max_stacking_layers: Optional[int] = None
    est_qty_20ft: Optional[float] = None
    est_qty_40hc: Optional[float] = None
    # Warehouse Coordinates
    warehouse_location: Optional[str] = None
    default_bin: Optional[str] = None
    packaging_specs: Optional[Dict[str, Any]] = None

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
    images: Optional[List[Any]] = None
    videos: Optional[List[Any]] = None
    attachment: Optional[List[Any]] = None
    factory_code: Optional[str] = None
    suppliers: Optional[List[ProductSupplierSchema]] = None

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

class StockAdjustSchema(BaseModel):
    quantity_delta: float
    reason: str
    notes: Optional[str] = None

class BulkCategorySchema(BaseModel):
    product_ids: List[int]
    category_id: int

class BulkDeleteSchema(BaseModel):
    product_ids: List[int]

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_accounts_user(user: User, org_context: OrgContext) -> bool:
    return is_financial_user(user, org_context)


def check_can_view_supplier(user: User, org_context: OrgContext) -> bool:
    """
    Zero-trust supplier permission check.
    Only allows viewing vendor/supplier identities if:
    - Root tenant super admins or users with role Administrator
    - User explicitly holds View_Supplier, Supplier, Edit_Supplier, or Add_Supplier permission
    Does NOT infer view access from financial clearance or unrelated roles.
    """
    if not user:
        return False
    if org_context and org_context.is_root:
        return True

    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "administrator", "root"] for r in user_roles):
        return True

    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["View_Supplier", "Supplier", "Edit_Supplier", "Add_Supplier"]:
                return True
    return False



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


def _sync_product_suppliers(db: Session, prod: Product, suppliers_payload: Optional[List[ProductSupplierSchema]], org_id: int, user_id: int):
    if suppliers_payload is None:
        return

    existing_records = db.query(ProductSupplier).filter(
        ProductSupplier.product_id == prod.id,
        ProductSupplier.is_deleted == False
    ).all()
    
    incoming_supplier_ids = {s.supplier_id for s in suppliers_payload if s.supplier_id}
    
    for ex in existing_records:
        if ex.supplier_id not in incoming_supplier_ids:
            ex.is_deleted = True
            ex.deleted_at = datetime.utcnow()
            ex.deleted_by = user_id

    has_default = any(bool(s.is_default) for s in suppliers_payload)
    if not has_default and suppliers_payload:
        suppliers_payload[0].is_default = True

    default_supplier_id = None
    for item in suppliers_payload:
        if not item.supplier_id:
            continue
        supplier = db.query(Supplier).filter(
            Supplier.supplier_id == item.supplier_id,
            Supplier.is_deleted != True,
            or_(Supplier.is_shared == True, Supplier.org_id == org_id),
        ).first()
        if not supplier:
            raise HTTPException(status_code=400, detail="Supplier is not available to this organisation")
        existing = db.query(ProductSupplier).filter(
            ProductSupplier.product_id == prod.id,
            ProductSupplier.supplier_id == item.supplier_id
        ).first()

        if item.is_default:
            default_supplier_id = item.supplier_id

        if existing:
            existing.factory_code = item.factory_code.strip() if item.factory_code else None
            existing.vendor_product_name = item.vendor_product_name.strip() if item.vendor_product_name else None
            existing.unit_cost = item.unit_cost
            existing.currency = item.currency or "USD"
            existing.min_order_qty = item.min_order_qty
            existing.lead_time_days = item.lead_time_days
            existing.is_default = bool(item.is_default)
            existing.notes = item.notes
            existing.is_deleted = False
            existing.deleted_at = None
            existing.updated_at = datetime.utcnow()
            existing.updated_by = user_id
        else:
            new_ps = ProductSupplier(
                org_id=org_id,
                product_id=prod.id,
                supplier_id=item.supplier_id,
                factory_code=item.factory_code.strip() if item.factory_code else None,
                vendor_product_name=item.vendor_product_name.strip() if item.vendor_product_name else None,
                unit_cost=item.unit_cost,
                currency=item.currency or "USD",
                min_order_qty=item.min_order_qty,
                lead_time_days=item.lead_time_days,
                is_default=bool(item.is_default),
                notes=item.notes,
                created_by=user_id,
                updated_by=user_id
            )
            db.add(new_ps)

    if default_supplier_id:
        prod.default_supplier_id = default_supplier_id
    elif not incoming_supplier_ids:
        prod.default_supplier_id = None


def product_to_dict(
    p: Product,
    is_accounts: bool = True,
    can_view_supplier: bool = True,
    db: Session = None,
    include_links: bool = False
) -> dict:
    cat_name = p.category.name if p.category else None
    supplier_name = p.supplier.name if (p.supplier and can_view_supplier) else None

    # Primary image thumbnail
    images = p.images or []
    first_img = images[0] if (images and len(images) > 0 and isinstance(images[0], dict)) else {}
    img_url = first_img.get("file_url") or first_img.get("url")

    # Multi-vendor suppliers & factory codes
    prod_supps = getattr(p, "product_suppliers", None) or []
    suppliers_data = []
    default_factory_code = ""
    for ps in prod_supps:
        if getattr(ps, "is_deleted", False):
            continue
        supp_name = ps.supplier.name if getattr(ps, "supplier", None) else ""
        if ps.is_default:
            default_factory_code = ps.factory_code or ""
        suppliers_data.append({
            "id": ps.id,
            "supplier_id": ps.supplier_id,
            "supplier_name": supp_name,
            "factory_code": ps.factory_code or "",
            "vendor_product_name": ps.vendor_product_name or "",
            "unit_cost": float(ps.unit_cost) if ps.unit_cost is not None and is_accounts else None,
            "currency": ps.currency or "USD",
            "min_order_qty": float(ps.min_order_qty) if ps.min_order_qty is not None else None,
            "lead_time_days": ps.lead_time_days,
            "is_default": bool(ps.is_default),
            "notes": ps.notes or ""
        })
    if not default_factory_code and suppliers_data:
        default_factory_code = suppliers_data[0].get("factory_code") or ""

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
        # Multi-Tier Packaging Specs
        "retail_packaging_type": getattr(p, "retail_packaging_type", None),
        "gross_weight_per_unit": float(p.gross_weight_per_unit) if getattr(p, "gross_weight_per_unit", None) is not None else None,
        "wholesale_packaging_type": getattr(p, "wholesale_packaging_type", None),
        "units_per_inner": float(p.units_per_inner) if getattr(p, "units_per_inner", None) is not None else None,
        "inner_length": float(p.inner_length) if getattr(p, "inner_length", None) is not None else None,
        "inner_width": float(p.inner_width) if getattr(p, "inner_width", None) is not None else None,
        "inner_height": float(p.inner_height) if getattr(p, "inner_height", None) is not None else None,
        "inner_weight": float(p.inner_weight) if getattr(p, "inner_weight", None) is not None else None,
        "import_packaging_type": getattr(p, "import_packaging_type", None),
        "master_length": float(p.master_length) if getattr(p, "master_length", None) is not None else None,
        "master_width": float(p.master_width) if getattr(p, "master_width", None) is not None else None,
        "master_height": float(p.master_height) if getattr(p, "master_height", None) is not None else None,
        "master_tare_weight": float(p.master_tare_weight) if getattr(p, "master_tare_weight", None) is not None else None,
        "pallet_type": getattr(p, "pallet_type", None),
        "cartons_per_layer": getattr(p, "cartons_per_layer", None),
        "layers_per_pallet": getattr(p, "layers_per_pallet", None),
        "total_cartons_per_pallet": getattr(p, "total_cartons_per_pallet", None),
        "max_stacking_layers": getattr(p, "max_stacking_layers", None),
        "est_qty_20ft": float(p.est_qty_20ft) if getattr(p, "est_qty_20ft", None) is not None else None,
        "est_qty_40hc": float(p.est_qty_40hc) if getattr(p, "est_qty_40hc", None) is not None else None,
        "warehouse_location": getattr(p, "warehouse_location", None),
        "default_bin": getattr(p, "default_bin", None),
        "packaging_specs": getattr(p, "packaging_specs", None) or {},
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
        # Suppliers & Factory Codes
        "default_supplier_id": p.default_supplier_id if can_view_supplier else None,
        "supplier_name": supplier_name if can_view_supplier else None,
        "suppliers": suppliers_data if can_view_supplier else [],
        "factory_code": default_factory_code if can_view_supplier else None,
        "default_factory_code": default_factory_code if can_view_supplier else None,
        # Media
        "image_url": img_url,
        "image_signed_url": _signed_media_url(img_url),
        "images": _signed_media_items(images),
        "videos": _signed_media_items(getattr(p, "videos", None) or []),
        "attachment": p.attachment or [],
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
    doc_type: Optional[str] = Query(None),
    is_rfq: Optional[bool] = Query(False),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """Autocomplete for PO / form creation powered by Meilisearch with Postgres fallback."""
    is_acc = is_accounts_user(current_user, org_context)
    can_view_supplier = check_can_view_supplier(current_user, org_context)
    hide_fin = bool(is_rfq or (doc_type and doc_type.upper() == "RFQ") or not is_acc)
    hide_supplier = bool(is_rfq or (doc_type and doc_type.upper() == "RFQ") or not can_view_supplier)
    if not can_view_supplier:
        supplier_id = None

    # Try fast typo-tolerant Meilisearch first
    filters = ["status = 'active'", "is_deleted = false"]
    if org_context and getattr(org_context, "org_id", None):
        filters.append(f"org_id = {org_context.org_id}")
    if supplier_id:
        filters.append(f"default_supplier_id = {supplier_id}")

    try:
        meili_hits = search_products(q or "", filters=filters, limit=limit)
        if meili_hits:
            return [{
                "id": p["id"],
                "code": p.get("code") or "",
                "sku": p.get("sku") or "",
                "factory_code": p.get("factory_code") or "",
                "name": p.get("name") or "",
                "description": p.get("description") or "",
                "description_quick": p.get("description_quick") or "",
                "unit": p.get("unit") or "PCS",
                "image_url": p.get("image_url"),
                "image_signed_url": _signed_media_url(p.get("image_url")),
                "images": _signed_media_items(p.get("images") or []),
                "suppliers": [] if hide_supplier else (p.get("suppliers") or []),
                "brand": p.get("brand") if not hide_supplier else None,
                "category_id": p.get("category_id"),
                "category_name": p.get("category_name"),
                "default_supplier_id": None if hide_supplier else p.get("default_supplier_id"),
                "supplier_name": None if hide_supplier else p.get("supplier_name"),
                "current_stock": float(p.get("current_stock") or 0.0),
                "min_stock_quantity": float(p.get("min_stock_quantity") or 0.0),
                "unit_cost": None if hide_fin else (float(p["unit_cost"]) if p.get("unit_cost") is not None else None),
                "currency": p.get("currency") or "USD"
            } for p in meili_hits]
    except Exception as e:
        logger.warning("Meilisearch lookup failed, falling back to PostgreSQL: %s", e)

    # PostgreSQL fallback
    query = (
        db.query(Product)
        .options(
            joinedload(Product.category),
            joinedload(Product.supplier),
            joinedload(Product.product_suppliers).joinedload(ProductSupplier.supplier)
        )
        .filter(Product.is_deleted == False, Product.status == "active")
    )
    query = apply_org_filter(query, Product, org_context)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(or_(
            Product.sku.ilike(term), Product.code.ilike(term),
            Product.name.ilike(term), Product.brand.ilike(term), Product.barcode.ilike(term),
            Product.description.ilike(term),
            Product.product_suppliers.any(
                (ProductSupplier.factory_code.ilike(term)) & (ProductSupplier.is_deleted == False)
            )
        ))
    if supplier_id:
        query = query.filter(Product.default_supplier_id == supplier_id)
    prods = query.order_by(Product.name.asc()).limit(limit).all()

    results = []
    for p in prods:
        imgs = p.images or []
        first_img = imgs[0] if (imgs and len(imgs) > 0 and isinstance(imgs[0], dict)) else {}
        img_url = first_img.get("file_url") or first_img.get("url")

        prod_supps = getattr(p, "product_suppliers", None) or []
        supps_data = []
        default_factory = ""
        for ps in prod_supps:
            if getattr(ps, "is_deleted", False):
                continue
            s_name = ps.supplier.name if getattr(ps, "supplier", None) else ""
            if ps.is_default:
                default_factory = ps.factory_code or ""
            supps_data.append({
                "id": ps.id,
                "supplier_id": ps.supplier_id,
                "supplier_name": s_name,
                "factory_code": ps.factory_code or "",
                "vendor_product_name": ps.vendor_product_name or "",
                "unit_cost": float(ps.unit_cost) if ps.unit_cost is not None and not hide_fin else None,
                "currency": ps.currency or "USD",
                "min_order_qty": float(ps.min_order_qty) if ps.min_order_qty is not None else None,
                "lead_time_days": ps.lead_time_days,
                "is_default": bool(ps.is_default),
                "notes": ps.notes or ""
            })
        if not default_factory and supps_data:
            default_factory = supps_data[0].get("factory_code") or ""

        results.append({
            "id": p.id,
            "code": p.code,
            "sku": p.sku,
            "factory_code": default_factory,
            "name": p.name,
            "description": p.description,
            "description_quick": p.description_quick,
            "unit": p.unit or "PCS",
            "image_url": img_url,
            "image_signed_url": _signed_media_url(img_url),
            "images": _signed_media_items(imgs),
            "suppliers": [] if hide_supplier else supps_data,
            "brand": p.brand if not hide_supplier else None,
            "category_id": p.category_id,
            "category_name": p.category.name if p.category else None,
            "default_supplier_id": None if hide_supplier else p.default_supplier_id,
            "supplier_name": None if hide_supplier else (p.supplier.name if p.supplier else None),
            "current_stock": float(p.current_stock or 0.0),
            "min_stock_quantity": float(p.min_stock_quantity or 0.0),
            "unit_cost": None if hide_fin else (float(p.unit_cost) if p.unit_cost is not None else None),
            "currency": p.currency or "USD"
        })
    return results


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
    if not has_permission(current_user, "View_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to view products.")

    can_view_supplier = check_can_view_supplier(current_user, org_context)
    if not can_view_supplier:
        supplier_id = None

    is_acc = is_accounts_user(current_user, org_context)
    offset = (page - 1) * limit

    # ── High-Performance Meilisearch Integration ──────────────────────────
    if search and search.strip():
        meili_filters = ["is_deleted = false"]
        if org_context and getattr(org_context, "org_id", None):
            meili_filters.append(f"org_id = {org_context.org_id}")
        if status:
            meili_filters.append(f"status = '{status}'")
        if category_id:
            descendant_ids = _get_descendant_category_ids(db, category_id)
            if len(descendant_ids) == 1:
                meili_filters.append(f"category_id = {descendant_ids[0]}")
            elif descendant_ids:
                or_clause = " OR ".join([f"category_id = {cid}" for cid in descendant_ids])
                meili_filters.append(f"({or_clause})")
        if supplier_id and can_view_supplier:
            meili_filters.append(f"default_supplier_id = {supplier_id}")

        hits, total_count = search_products_with_total(
            query_str=search.strip(),
            filters=meili_filters,
            limit=limit,
            offset=offset
        )

        if hits:
            hit_ids = [h["id"] for h in hits]
            prods = (
                db.query(Product)
                .options(joinedload(Product.category), joinedload(Product.supplier), joinedload(Product.product_suppliers))
                .filter(Product.id.in_(hit_ids))
                .all()
            )
            prod_map = {p.id: p for p in prods}
            sorted_prods = [prod_map[hid] for hid in hit_ids if hid in prod_map]

            if low_stock_only:
                sorted_prods = [
                    p for p in sorted_prods
                    if p.min_stock_quantity and float(p.min_stock_quantity) > 0 and float(p.current_stock or 0.0) <= float(p.min_stock_quantity)
                ]

            return {
                "items": [product_to_dict(p, is_accounts=is_acc, can_view_supplier=can_view_supplier, db=db) for p in sorted_prods],
                "total": total_count,
                "page": page,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit if total_count > 0 else 1
            }

    # ── Fallback SQL Query for Filtering / Non-Meili Search ───────────────
    query = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.supplier), joinedload(Product.product_suppliers))
        .filter(Product.is_deleted == False)
    )
    query = apply_org_filter(query, Product, org_context)
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(or_(
            Product.sku.ilike(s), Product.code.ilike(s), Product.name.ilike(s),
            Product.brand.ilike(s), Product.description.ilike(s),
            Product.barcode.ilike(s), Product.hs_code.ilike(s),
            Product.product_suppliers.any(
                (ProductSupplier.factory_code.ilike(s)) & (ProductSupplier.is_deleted == False)
            )
        ))
    if category_id:
        descendant_ids = _get_descendant_category_ids(db, category_id)
        query = query.filter(Product.category_id.in_(descendant_ids))
    if supplier_id and can_view_supplier:
        query = query.filter(Product.default_supplier_id == supplier_id)
    if status:
        query = query.filter(Product.status == status)
    if low_stock_only:
        query = query.filter(Product.min_stock_quantity > 0, Product.current_stock <= Product.min_stock_quantity)

    total_count = query.count()
    items = query.order_by(Product.name.asc()).offset(offset).limit(limit).all()

    return {
        "items": [product_to_dict(p, is_accounts=is_acc, can_view_supplier=can_view_supplier, db=db) for p in items],
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": (total_count + limit - 1) // limit if total_count > 0 else 1
    }


# ── Bulk & Quick Operations ───────────────────────────────────────────────────

@InventoryRouter.get("/products/export")
def export_products(
    search: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    supplier_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """Export product catalog to CSV with permission-aware field redaction."""
    if not has_permission(current_user, "Export_Inventory"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to export inventory.")

    can_view_supplier = check_can_view_supplier(current_user, org_context)
    if not can_view_supplier:
        supplier_id = None
    is_acc = is_accounts_user(current_user, org_context)

    query = (
        db.query(Product)
        .options(joinedload(Product.category), joinedload(Product.supplier), joinedload(Product.product_suppliers))
        .filter(Product.is_deleted == False)
    )
    query = apply_org_filter(query, Product, org_context)

    if search and search.strip():
        s = f"%{search.strip()}%"
        query = query.filter(or_(
            Product.sku.ilike(s), Product.code.ilike(s), Product.name.ilike(s),
            Product.brand.ilike(s), Product.description.ilike(s), Product.barcode.ilike(s)
        ))
    if category_id:
        descendant_ids = _get_descendant_category_ids(db, category_id)
        query = query.filter(Product.category_id.in_(descendant_ids))
    if supplier_id and can_view_supplier:
        query = query.filter(Product.default_supplier_id == supplier_id)
    if status:
        query = query.filter(Product.status == status)

    prods = query.order_by(Product.name.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    headers = ["SKU", "Code", "Name", "Category", "Brand", "Unit", "Current Stock", "Min Stock", "Max Stock", "Status"]
    if can_view_supplier:
        headers.extend(["Default Supplier", "Factory Code"])
    if is_acc:
        headers.extend(["Unit Cost", "Currency"])

    writer.writerow(headers)
    for p in prods:
        cat_name = p.category.name if p.category else ""
        row = [
            p.sku or "", p.code or "", p.name or "", cat_name, p.brand or "",
            p.unit or "PCS", float(p.current_stock or 0.0), float(p.min_stock_quantity or 0.0),
            float(p.max_stock_quantity) if p.max_stock_quantity is not None else "",
            p.status or "active"
        ]
        if can_view_supplier:
            supp_name = p.supplier.name if p.supplier else ""
            prod_supps = getattr(p, "product_suppliers", None) or []
            f_code = ""
            for ps in prod_supps:
                if ps.is_default and not getattr(ps, "is_deleted", False):
                    f_code = ps.factory_code or ""
                    break
            row.extend([supp_name, f_code])
        if is_acc:
            row.extend([float(p.unit_cost) if p.unit_cost is not None else "", p.currency or "USD"])
        writer.writerow(row)

    output.seek(0)
    filename = f"inventory_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@InventoryRouter.post("/products/bulk-category")
def bulk_category(
    payload: BulkCategorySchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """Bulk reassign product category."""
    if not has_permission(current_user, "Edit_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to modify products.")

    cat = apply_org_filter(
        db.query(ProductCategory).filter(ProductCategory.id == payload.category_id, ProductCategory.is_deleted == False),
        ProductCategory, org_context
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Target category not found.")

    prods = apply_org_filter(
        db.query(Product).filter(Product.id.in_(payload.product_ids), Product.is_deleted == False),
        Product, org_context
    ).all()

    for p in prods:
        p.category_id = payload.category_id
        p.updated_by = current_user.id
        p.updated_at = datetime.utcnow()
        background_tasks.add_task(sync_product_document, p)

    db.commit()
    return {"success": True, "count": len(prods), "message": f"Successfully updated category for {len(prods)} product(s)."}


@InventoryRouter.post("/products/bulk-delete")
def bulk_delete(
    payload: BulkDeleteSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """Bulk soft-delete products."""
    if not has_permission(current_user, "Delete_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to delete products.")

    prods = apply_org_filter(
        db.query(Product).filter(Product.id.in_(payload.product_ids), Product.is_deleted == False),
        Product, org_context
    ).all()

    for p in prods:
        p.is_deleted = True
        p.updated_by = current_user.id
        p.updated_at = datetime.utcnow()
        background_tasks.add_task(remove_product_document, p.id)

    db.commit()
    return {"success": True, "count": len(prods), "message": f"Successfully deleted {len(prods)} product(s)."}


@InventoryRouter.post("/products/{product_id}/adjust-stock")
def adjust_stock(
    product_id: int,
    payload: StockAdjustSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """Adjust product stock quantity with reason logging."""
    if not has_permission(current_user, "Adjust_Stock"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to adjust stock.")

    prod = apply_org_filter(
        db.query(Product).options(joinedload(Product.category), joinedload(Product.supplier), joinedload(Product.product_suppliers))
        .filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    prev_stock = float(prod.current_stock or 0.0)
    new_stock = max(0.0, prev_stock + payload.quantity_delta)
    prod.current_stock = new_stock
    prod.updated_by = current_user.id
    prod.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prod)
    background_tasks.add_task(sync_product_document, prod)

    logger.info(
        f"Stock adjusted for product {prod.id} ({prod.sku}): {prev_stock} -> {new_stock} "
        f"(delta: {payload.quantity_delta}, reason: {payload.reason}, user: {current_user.id})"
    )

    is_acc = is_accounts_user(current_user, org_context)
    can_view_supplier = check_can_view_supplier(current_user, org_context)
    return {
        "success": True,
        "message": f"Stock adjusted from {prev_stock} to {new_stock}",
        "product": product_to_dict(prod, is_accounts=is_acc, can_view_supplier=can_view_supplier, db=db)
    }


@InventoryRouter.post("/products/{product_id}/duplicate")
def duplicate_product(
    product_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """Clone an existing product with a unique SKU and copied specifications."""
    if not has_permission(current_user, "Add_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to duplicate products.")

    orig = apply_org_filter(
        db.query(Product).options(joinedload(Product.product_suppliers))
        .filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not orig:
        raise HTTPException(status_code=404, detail="Product not found")

    target_org_id = orig.org_id
    base_sku = f"{orig.sku}-COPY"
    candidate_sku = base_sku
    suffix = 1
    while db.query(Product).filter(Product.org_id == target_org_id, Product.sku == candidate_sku, Product.is_deleted == False).first():
        suffix += 1
        candidate_sku = f"{base_sku}-{suffix}"

    new_prod = Product(
        org_id=target_org_id,
        code=f"{orig.code}-COPY" if orig.code else None,
        sku=candidate_sku,
        name=f"{orig.name} (Copy)",
        description=orig.description,
        description_quick=orig.description_quick,
        status="active",
        category_id=orig.category_id,
        brand=orig.brand,
        model_number=orig.model_number,
        series=orig.series,
        country_of_origin=orig.country_of_origin,
        barcode=None,
        hs_code=orig.hs_code,
        duty_rate=orig.duty_rate,
        tags=list(orig.tags or []),
        unit=orig.unit or "PCS",
        length=orig.length, width=orig.width, height=orig.height,
        weight_per_unit=orig.weight_per_unit,
        dimension_unit=orig.dimension_unit or "mm",
        weight_unit=orig.weight_unit or "kg",
        units_per_box=orig.units_per_box, box_weight=orig.box_weight,
        retail_packaging_type=getattr(orig, "retail_packaging_type", None),
        gross_weight_per_unit=getattr(orig, "gross_weight_per_unit", None),
        wholesale_packaging_type=getattr(orig, "wholesale_packaging_type", None),
        units_per_inner=getattr(orig, "units_per_inner", None),
        inner_length=getattr(orig, "inner_length", None),
        inner_width=getattr(orig, "inner_width", None),
        inner_height=getattr(orig, "inner_height", None),
        inner_weight=getattr(orig, "inner_weight", None),
        import_packaging_type=getattr(orig, "import_packaging_type", None),
        master_length=getattr(orig, "master_length", None),
        master_width=getattr(orig, "master_width", None),
        master_height=getattr(orig, "master_height", None),
        master_tare_weight=getattr(orig, "master_tare_weight", None),
        pallet_type=getattr(orig, "pallet_type", None),
        cartons_per_layer=getattr(orig, "cartons_per_layer", None),
        layers_per_pallet=getattr(orig, "layers_per_pallet", None),
        total_cartons_per_pallet=getattr(orig, "total_cartons_per_pallet", None),
        max_stacking_layers=getattr(orig, "max_stacking_layers", None),
        est_qty_20ft=getattr(orig, "est_qty_20ft", None),
        est_qty_40hc=getattr(orig, "est_qty_40hc", None),
        warehouse_location=getattr(orig, "warehouse_location", None),
        default_bin=getattr(orig, "default_bin", None),
        packaging_specs=dict(getattr(orig, "packaging_specs", None) or {}),
        unit_cost=orig.unit_cost, currency=orig.currency or "USD",
        current_stock=0.0,
        min_stock_quantity=orig.min_stock_quantity or 0.0,
        max_stock_quantity=orig.max_stock_quantity,
        order_threshold_qty=orig.order_threshold_qty,
        threshold_qty=orig.threshold_qty,
        min_quantity_order=orig.min_quantity_order,
        lead_time_days=orig.lead_time_days,
        default_supplier_id=orig.default_supplier_id,
        images=list(orig.images or []),
        videos=list(orig.videos or []),
        attachment=list(orig.attachment or []),
        is_consumable=orig.is_consumable,
        is_hazardous=orig.is_hazardous,
        is_perishable=orig.is_perishable,
        expiry_days=orig.expiry_days,
        is_returnable=orig.is_returnable,
        warranty_days=orig.warranty_days,
        created_by=current_user.id, updated_by=current_user.id
    )
    db.add(new_prod)
    db.commit()
    db.refresh(new_prod)

    # Duplicate supplier relationships
    for ps in (orig.product_suppliers or []):
        if not getattr(ps, "is_deleted", False):
            new_ps = ProductSupplier(
                org_id=new_prod.org_id,
                product_id=new_prod.id,
                supplier_id=ps.supplier_id,
                factory_code=f"{ps.factory_code}-COPY" if ps.factory_code else None,
                vendor_product_name=ps.vendor_product_name,
                unit_cost=ps.unit_cost,
                currency=ps.currency,
                min_order_qty=ps.min_order_qty,
                lead_time_days=ps.lead_time_days,
                is_default=ps.is_default,
                notes=ps.notes,
                created_by=current_user.id,
                updated_by=current_user.id
            )
            db.add(new_ps)
    db.commit()
    db.refresh(new_prod)

    background_tasks.add_task(sync_product_document, new_prod)
    is_acc = is_accounts_user(current_user, org_context)
    can_view_supplier = check_can_view_supplier(current_user, org_context)
    return product_to_dict(new_prod, is_accounts=is_acc, can_view_supplier=can_view_supplier, db=db)


@InventoryRouter.get("/products/{product_id}")
def get_product_detail(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    if not has_permission(current_user, "View_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to view products.")

    prod = apply_org_filter(
        db.query(Product).options(joinedload(Product.category), joinedload(Product.supplier), joinedload(Product.product_suppliers))
        .filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    is_acc = is_accounts_user(current_user, org_context)
    can_view_supplier = check_can_view_supplier(current_user, org_context)
    return product_to_dict(prod, is_accounts=is_acc, can_view_supplier=can_view_supplier, db=db, include_links=True)


@InventoryRouter.post("/products")
def create_product(
    payload: ProductCreateSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    if not has_permission(current_user, "Add_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to register products.")

    target_org_id = org_context.org_id
    sku_val = payload.sku.strip().upper() if payload.sku and payload.sku.strip() else f"SKU-{datetime.utcnow().strftime('%y%m%d%H%M%S')}"
    existing = db.query(Product).filter(
        Product.org_id == target_org_id, Product.sku == sku_val, Product.is_deleted == False
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"A product with SKU '{sku_val}' already exists.")

    new_prod = Product(
        org_id=target_org_id,
        code=payload.code.strip().upper() if payload.code else None,
        sku=sku_val,
        name=payload.name.strip(),
        description=payload.description or payload.name.strip(),
        description_quick=payload.description_quick,
        status=payload.status or "active",
        category_id=payload.category_id,
        brand=payload.brand.strip() if payload.brand else None,
        model_number=payload.model_number,
        series=payload.series,
        country_of_origin=payload.country_of_origin.strip() if payload.country_of_origin else None,
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
        retail_packaging_type=payload.retail_packaging_type,
        gross_weight_per_unit=payload.gross_weight_per_unit,
        wholesale_packaging_type=payload.wholesale_packaging_type,
        units_per_inner=payload.units_per_inner,
        inner_length=payload.inner_length,
        inner_width=payload.inner_width,
        inner_height=payload.inner_height,
        inner_weight=payload.inner_weight,
        import_packaging_type=payload.import_packaging_type,
        master_length=payload.master_length,
        master_width=payload.master_width,
        master_height=payload.master_height,
        master_tare_weight=payload.master_tare_weight,
        pallet_type=payload.pallet_type,
        cartons_per_layer=payload.cartons_per_layer,
        layers_per_pallet=payload.layers_per_pallet,
        total_cartons_per_pallet=payload.total_cartons_per_pallet,
        max_stacking_layers=payload.max_stacking_layers,
        est_qty_20ft=payload.est_qty_20ft,
        est_qty_40hc=payload.est_qty_40hc,
        warehouse_location=payload.warehouse_location,
        default_bin=payload.default_bin,
        packaging_specs=payload.packaging_specs or {},
        unit_cost=payload.unit_cost, currency=payload.currency or "USD",
        current_stock=payload.current_stock or 0.0,
        min_stock_quantity=payload.min_stock_quantity or 0.0,
        max_stock_quantity=payload.max_stock_quantity,
        order_threshold_qty=payload.order_threshold_qty,
        threshold_qty=payload.threshold_qty,
        min_quantity_order=payload.min_quantity_order,
        lead_time_days=payload.lead_time_days,
        default_supplier_id=payload.default_supplier_id,
        images=payload.images or [],
        videos=payload.videos or [],
        attachment=payload.attachment or [],
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

    if payload.suppliers is not None:
        _sync_product_suppliers(db, new_prod, payload.suppliers, target_org_id, current_user.id)
        db.commit()
        db.refresh(new_prod)
    elif payload.default_supplier_id:
        _sync_product_suppliers(db, new_prod, [ProductSupplierSchema(
            supplier_id=payload.default_supplier_id,
            factory_code=payload.factory_code or new_prod.sku,
            unit_cost=payload.unit_cost,
            currency=payload.currency or "USD",
            lead_time_days=payload.lead_time_days,
            is_default=True
        )], target_org_id, current_user.id)
        db.commit()
        db.refresh(new_prod)

    background_tasks.add_task(sync_product_document, new_prod)
    is_acc = is_accounts_user(current_user, org_context)
    return product_to_dict(new_prod, is_accounts=is_acc, db=db)


@InventoryRouter.put("/products/{product_id}")
def update_product(
    product_id: int,
    payload: ProductUpdateSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    if not has_permission(current_user, "Edit_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to edit products.")

    prod = apply_org_filter(
        db.query(Product).filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    if payload.sku is not None:
        new_sku = payload.sku.strip().upper()
        if not new_sku:
            raise HTTPException(status_code=400, detail="Trading SKU cannot be empty.")
        if new_sku != prod.sku:
            conflict = db.query(Product).filter(
                Product.org_id == prod.org_id,
                Product.sku == new_sku,
                Product.id != prod.id,
                Product.is_deleted == False
            ).first()
            if conflict:
                raise HTTPException(status_code=400, detail=f"A product with SKU '{new_sku}' already exists.")
            prod.sku = new_sku

    updatable = [
        "code", "name", "description", "description_quick", "status",
        "category_id", "brand", "model_number", "series", "country_of_origin",
        "barcode", "hs_code", "duty_rate", "tags", "unit",
        "length", "width", "height", "weight_per_unit", "dimension_unit", "weight_unit",
        "units_per_box", "box_weight", "currency",
        "retail_packaging_type", "gross_weight_per_unit",
        "wholesale_packaging_type", "units_per_inner", "inner_length", "inner_width", "inner_height", "inner_weight",
        "import_packaging_type", "master_length", "master_width", "master_height", "master_tare_weight",
        "pallet_type", "cartons_per_layer", "layers_per_pallet", "total_cartons_per_pallet", "max_stacking_layers",
        "est_qty_20ft", "est_qty_40hc",
        "warehouse_location", "default_bin", "packaging_specs",
        "current_stock", "min_stock_quantity", "max_stock_quantity",
        "order_threshold_qty", "threshold_qty", "min_quantity_order", "lead_time_days",
        "default_supplier_id",
        "images", "videos", "attachment",
        "is_consumable", "is_hazardous", "is_perishable", "expiry_days",
        "is_returnable", "warranty_days"
    ]
    for field in updatable:
        val = getattr(payload, field, None)
        if val is not None:
            setattr(prod, field, val)
    if payload.unit_cost is not None and is_accounts_user(current_user, org_context):
        prod.unit_cost = payload.unit_cost

    if payload.suppliers is not None:
        _sync_product_suppliers(db, prod, payload.suppliers, prod.org_id, current_user.id)
    elif payload.default_supplier_id is not None and payload.default_supplier_id != prod.default_supplier_id:
        _sync_product_suppliers(db, prod, [ProductSupplierSchema(
            supplier_id=payload.default_supplier_id,
            factory_code=payload.factory_code or prod.sku,
            unit_cost=payload.unit_cost if payload.unit_cost is not None else float(prod.unit_cost or 0),
            currency=payload.currency or prod.currency or "USD",
            is_default=True
        )], prod.org_id, current_user.id)

    prod.updated_by = current_user.id
    prod.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prod)
    background_tasks.add_task(sync_product_document, prod)
    is_acc = is_accounts_user(current_user, org_context)
    return product_to_dict(prod, is_accounts=is_acc, db=db)


@InventoryRouter.post("/products/{product_id}/media")
def upload_product_media(
    product_id: int,
    file: UploadFile = File(...),
    media_type: str = Query("image", description="'image' or 'video'"),
    title: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    prod = apply_org_filter(
        db.query(Product).filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context
    ).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    folder = "products/videos" if media_type == "video" else "products/images"
    key = blob_storage.upload_file(file_obj=file, folder=folder, original_filename=file.filename)

    media_obj = {
        "id": f"media-{int(datetime.utcnow().timestamp() * 1000)}",
        "file_name": file.filename,
        "file_url": key,
        "media_type": media_type,
        "title": title or file.filename,
        "uploaded_at": datetime.utcnow().isoformat()
    }

    if media_type == "video":
        cur_videos = list(prod.videos or [])
        cur_videos.append(media_obj)
        prod.videos = cur_videos
    else:
        cur_images = list(prod.images or [])
        cur_images.append(media_obj)
        prod.images = cur_images

    db.commit()
    return {"success": True, "media": media_obj, "message": f"{media_type.capitalize()} uploaded successfully."}


@InventoryRouter.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    if not has_permission(current_user, "Delete_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to delete products.")

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
    background_tasks.add_task(remove_product_document, product_id)
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
    target_org_id = org_context.org_id
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
    if not has_permission(current_user, "View_ProductCategory"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to view product categories.")

    target_org_id = org_context.org_id
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
    if not has_permission(current_user, "Manage_ProductCategory"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to manage product categories.")

    target_org_id = org_context.org_id
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
    if not has_permission(current_user, "Manage_ProductCategory"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to manage product categories.")

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
    if not has_permission(current_user, "Manage_ProductCategory"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to manage product categories.")

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

