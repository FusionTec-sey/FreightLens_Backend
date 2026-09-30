import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("containerMgmt.search")

MEILI_URL = os.getenv("MEILISEARCH_URL", "http://meilisearch:7700")
MEILI_KEY = os.getenv("MEILISEARCH_MASTER_KEY") or os.getenv("MEILI_MASTER_KEY")

_client = None

def get_meili_client():
    global _client
    if _client is None:
        try:
            import meilisearch
            _client = meilisearch.Client(MEILI_URL, MEILI_KEY)
        except Exception as e:
            logger.warning("Could not initialize Meilisearch client: %s", e)
            return None
    return _client

def init_products_index():
    """Ensure the products index exists with proper searchable and filterable settings."""
    client = get_meili_client()
    if not client:
        return False
    try:
        try:
            client.create_index("products", {"primaryKey": "id"})
        except Exception:
            pass
        index = client.index("products")
        try:
            index.update(primary_key="id")
        except Exception:
            pass
        # Configure searchable attributes for optimized typo tolerance & prefix matching
        index.update_searchable_attributes([
            "name",
            "sku",
            "code",
            "factory_code",
            "factory_codes",
            "brand",
            "category_name",
            "description",
        ])
        index.update_filterable_attributes([
            "status",
            "is_deleted",
            "category_id",
            "default_supplier_id",
            "org_id"
        ])
        logger.info("Meilisearch 'products' index initialized successfully.")
        return True
    except Exception as e:
        logger.exception("Failed to initialize Meilisearch 'products' index: %s", e)
        return False

def format_product_doc(p) -> Dict[str, Any]:
    """Formats a Product model or dictionary into a Meilisearch document."""
    if isinstance(p, dict):
        images = p.get("images") or []
        first_img = images[0] if (images and len(images) > 0 and isinstance(images[0], dict)) else {}
        img_url = first_img.get("file_url") or first_img.get("url")
        suppliers = p.get("suppliers") or []
        default_supp = next((s for s in suppliers if s.get("is_default")), (suppliers[0] if suppliers else {}))
        factory_codes = [s.get("factory_code") for s in suppliers if s.get("factory_code")]
        return {
            "id": p.get("id"),
            "name": p.get("name") or "",
            "sku": p.get("sku") or "",
            "code": p.get("code") or "",
            "brand": p.get("brand") or "",
            "description": p.get("description") or "",
            "unit": p.get("unit") or "PCS",
            "category_id": p.get("category_id"),
            "category_name": p.get("category_name") or "",
            "default_supplier_id": p.get("default_supplier_id"),
            "supplier_name": p.get("supplier_name") or default_supp.get("supplier_name") or "",
            "factory_code": default_supp.get("factory_code") or "",
            "factory_codes": factory_codes,
            "image_url": img_url,
            "images": images,
            "suppliers": suppliers,
            "current_stock": float(p.get("current_stock") or 0.0),
            "min_stock_quantity": float(p.get("min_stock_quantity") or 0.0),
            "unit_cost": float(p["unit_cost"]) if p.get("unit_cost") is not None else None,
            "currency": p.get("currency") or "USD",
            "tags": p.get("tags") or [],
            "status": p.get("status") or "active",
            "is_deleted": bool(p.get("is_deleted", False)),
            "org_id": p.get("org_id")
        }
    
    # SQLAlchemy Product object
    images = getattr(p, "images", None) or []
    first_img = images[0] if (images and len(images) > 0 and isinstance(images[0], dict)) else {}
    img_url = first_img.get("file_url") or first_img.get("url")

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
            "unit_cost": float(ps.unit_cost) if ps.unit_cost is not None else None,
            "currency": ps.currency or "USD",
            "min_order_qty": float(ps.min_order_qty) if ps.min_order_qty is not None else None,
            "lead_time_days": ps.lead_time_days,
            "is_default": bool(ps.is_default),
            "notes": ps.notes or ""
        })
    if not default_factory_code and suppliers_data:
        default_factory_code = suppliers_data[0].get("factory_code") or ""

    factory_codes = [s["factory_code"] for s in suppliers_data if s.get("factory_code")]

    return {
        "id": p.id,
        "name": p.name or "",
        "sku": p.sku or "",
        "code": p.code or "",
        "brand": p.brand or "",
        "description": p.description or "",
        "unit": p.unit or "PCS",
        "category_id": p.category_id,
        "category_name": p.category.name if getattr(p, "category", None) else "",
        "default_supplier_id": p.default_supplier_id,
        "supplier_name": p.supplier.name if getattr(p, "supplier", None) else "",
        "factory_code": default_factory_code,
        "factory_codes": factory_codes,
        "image_url": img_url,
        "images": images,
        "suppliers": suppliers_data,
        "current_stock": float(p.current_stock or 0.0),
        "min_stock_quantity": float(p.min_stock_quantity or 0.0),
        "unit_cost": float(p.unit_cost) if p.unit_cost is not None else None,
        "currency": p.currency or "USD",
        "tags": getattr(p, "tags", None) or [],
        "status": p.status or "active",
        "is_deleted": bool(getattr(p, "is_deleted", False)),
        "org_id": getattr(p, "org_id", None)
    }

def sync_product_document(product):
    """Adds or updates a single product in Meilisearch."""
    client = get_meili_client()
    if not client:
        return
    try:
        doc = format_product_doc(product)
        client.index("products").add_documents([doc], primary_key="id")
        logger.info("Synced product %s to Meilisearch", doc.get("id"))
    except Exception as e:
        logger.error("Failed to sync product to Meilisearch: %s", e)

def remove_product_document(product_id: int):
    """Removes a product from Meilisearch."""
    client = get_meili_client()
    if not client:
        return
    try:
        client.index("products").delete_document(str(product_id))
        logger.info("Removed product %s from Meilisearch", product_id)
    except Exception as e:
        logger.error("Failed to remove product from Meilisearch: %s", e)

def search_products(
    query_str: str,
    filters: Optional[List[str]] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Search products using Meilisearch with typo tolerance and prefix matching."""
    client = get_meili_client()
    if not client:
        return []
    try:
        search_params = {
            "limit": limit,
            "offset": offset,
        }
        if filters:
            search_params["filter"] = " AND ".join(filters)

        res = client.index("products").search(query_str or "", search_params)
        return res.get("hits", [])
    except Exception as e:
        logger.error("Meilisearch product search error: %s", e)
        return []

def search_products_with_total(
    query_str: str,
    filters: Optional[List[str]] = None,
    limit: int = 50,
    offset: int = 0
):
    """Search products using Meilisearch returning both hits and total hits."""
    client = get_meili_client()
    if not client:
        return [], 0
    try:
        search_params = {
            "limit": limit,
            "offset": offset,
        }
        if filters:
            search_params["filter"] = " AND ".join(filters)

        res = client.index("products").search(query_str or "", search_params)
        hits = res.get("hits", [])
        total = res.get("totalHits") or res.get("estimatedTotalHits") or len(hits)
        return hits, total
    except Exception as e:
        logger.error("Meilisearch search_products_with_total error: %s", e)
        return [], 0

def bulk_index_all_products(db):
    """Bulk sync all active products from DB to Meilisearch."""
    client = get_meili_client()
    if not client:
        return 0
    try:
        init_products_index()
        from Model.containermgmt.Orders.Product import Product
        products = db.query(Product).filter(Product.is_deleted == False).all()
        if not products:
            return 0
        docs = [format_product_doc(p) for p in products]
        client.index("products").add_documents(docs, primary_key="id")
        logger.info("Successfully bulk indexed %d products to Meilisearch", len(docs))
        return len(docs)
    except Exception as e:
        logger.exception("Failed to bulk index products to Meilisearch: %s", e)
        return 0


# ── Orders & RFQs Meilisearch Index ──────────────────────────────────────────

def init_orders_index():
    """Ensure the purchase_orders index exists with proper searchable and filterable settings."""
    client = get_meili_client()
    if not client:
        return False
    try:
        try:
            client.create_index("purchase_orders", {"primaryKey": "id"})
        except Exception:
            pass
        index = client.index("purchase_orders")
        try:
            index.update(primary_key="id")
        except Exception:
            pass
        index.update_searchable_attributes([
            "po_number",
            "po_nce",
            "company",
            "goods_description",
            "origin_rfq_number",
            "consignee",
            "item_descriptions",
        ])
        index.update_filterable_attributes([
            "doc_type",
            "status",
            "status_label",
            "lifecycle_stage",
            "urgent_action",
            "supplier_id",
            "is_deleted",
            "org_id",
        ])
        logger.info("Meilisearch 'purchase_orders' index initialized successfully.")
        return True
    except Exception as e:
        logger.exception("Failed to initialize Meilisearch 'purchase_orders' index: %s", e)
        return False

def format_order_doc(o) -> Dict[str, Any]:
    """Formats a PurchaseOrder model or dictionary into a Meilisearch document."""
    if isinstance(o, dict):
        return {
            "id": o.get("id"),
            "po_number": o.get("po_number") or "",
            "po_nce": o.get("po_nce") or "",
            "company": o.get("company") or "",
            "goods_description": o.get("goods_description") or "",
            "origin_rfq_number": o.get("origin_rfq_number") or "",
            "consignee": o.get("consignee") or "",
            "doc_type": o.get("doc_type") or "PO",
            "status": o.get("status") or "DRAFT",
            "status_label": o.get("status_label") or "",
            "lifecycle_stage": o.get("lifecycle_stage") or "DRAFT",
            "urgent_action": bool(o.get("urgent_action", False)),
            "supplier_id": o.get("supplier_id"),
            "total_amount": float(o["total_amount"]) if o.get("total_amount") is not None else None,
            "currency": o.get("currency") or "USD",
            "item_descriptions": [item.get("description", "") for item in (o.get("items") or []) if isinstance(item, dict)],
            "is_deleted": bool(o.get("is_deleted", False)),
            "org_id": o.get("org_id")
        }

    item_descs = []
    items = getattr(o, "items", None) or []
    for item in items:
        desc = getattr(item, "description", None)
        if desc:
            item_descs.append(desc)

    supp_name = ""
    if getattr(o, "supplier_rel", None) and getattr(o.supplier_rel, "name", None):
        supp_name = o.supplier_rel.name
    elif getattr(o, "company", None):
        supp_name = o.company

    return {
        "id": o.id,
        "po_number": o.po_number or "",
        "po_nce": getattr(o, "po_nce", None) or "",
        "company": supp_name or "",
        "goods_description": getattr(o, "goods_description", None) or "",
        "origin_rfq_number": getattr(o, "origin_rfq_number", None) or "",
        "consignee": getattr(o, "consignee", None) or "",
        "doc_type": getattr(o, "doc_type", None) or "PO",
        "status": getattr(o, "status", None) or "DRAFT",
        "status_label": getattr(o, "status_label", None) or "",
        "lifecycle_stage": getattr(o, "lifecycle_stage", None) or "DRAFT",
        "urgent_action": bool(getattr(o, "urgent_action", False)),
        "supplier_id": getattr(o, "supplier_id", None),
        "total_amount": float(o.total_amount) if getattr(o, "total_amount", None) is not None else None,
        "currency": getattr(o, "currency", None) or "USD",
        "item_descriptions": item_descs,
        "is_deleted": bool(getattr(o, "is_deleted", False)),
        "org_id": getattr(o, "org_id", None)
    }

def sync_order_document(order):
    """Adds or updates a single order/RFQ in Meilisearch."""
    client = get_meili_client()
    if not client:
        return
    try:
        doc = format_order_doc(order)
        client.index("purchase_orders").add_documents([doc], primary_key="id")
        logger.info("Synced order/RFQ %s to Meilisearch", doc.get("id"))
    except Exception as e:
        logger.error("Failed to sync order/RFQ to Meilisearch: %s", e)

def remove_order_document(order_id: int):
    """Removes an order/RFQ from Meilisearch."""
    client = get_meili_client()
    if not client:
        return
    try:
        client.index("purchase_orders").delete_document(str(order_id))
        logger.info("Removed order/RFQ %s from Meilisearch", order_id)
    except Exception as e:
        logger.error("Failed to remove order/RFQ from Meilisearch: %s", e)

def search_orders_with_total(
    query_str: str,
    filters: Optional[List[str]] = None,
    limit: int = 25,
    offset: int = 0
):
    """Search purchase_orders using Meilisearch returning both hits and total hits."""
    client = get_meili_client()
    if not client:
        return [], 0
    try:
        search_params = {
            "limit": limit,
            "offset": offset,
        }
        if filters:
            search_params["filter"] = " AND ".join(filters)

        res = client.index("purchase_orders").search(query_str or "", search_params)
        hits = res.get("hits", [])
        total = res.get("totalHits") or res.get("estimatedTotalHits") or len(hits)
        return hits, total
    except Exception as e:
        logger.error("Meilisearch search_orders_with_total error: %s", e)
        return [], 0

def bulk_index_all_orders(db):
    """Bulk sync all active orders from DB to Meilisearch."""
    client = get_meili_client()
    if not client:
        return 0
    try:
        init_orders_index()
        from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
        from sqlalchemy.orm import selectinload, joinedload
        orders = (
            db.query(PurchaseOrder)
            .options(
                joinedload(PurchaseOrder.supplier_rel),
                selectinload(PurchaseOrder.items)
            )
            .filter(PurchaseOrder.is_deleted == False)
            .all()
        )
        if not orders:
            return 0
        docs = [format_order_doc(o) for o in orders]
        client.index("purchase_orders").add_documents(docs, primary_key="id")
        logger.info("Successfully bulk indexed %d orders to Meilisearch", len(docs))
        return len(docs)
    except Exception as e:
        logger.exception("Failed to bulk index orders to Meilisearch: %s", e)
        return 0


