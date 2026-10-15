import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("containerMgmt.search")

MEILI_URL = os.getenv("MEILISEARCH_URL", "http://meilisearch:7700")
MEILI_KEY = os.getenv("MEILISEARCH_MASTER_KEY") or os.getenv("MEILI_MASTER_KEY")

_client = None


def org_filter_clause(org_context) -> Optional[str]:
    """The same tenant rule the SQL queries use, written as a Meilisearch filter.

    apply_org_filter narrows to selected_org_id when a company is picked, and to
    every allowed company otherwise. The search filters used to read
    org_context.org_id, which collapses to the user's own company when nothing
    is selected -- so searching in "All companies" mode quietly returned only
    the root company's rows while clearing the search box returned them all.
    One helper so the two paths cannot drift apart again.
    """
    if org_context is None:
        return None
    selected = getattr(org_context, "selected_org_id", None)
    if selected:
        return f"org_id = {int(selected)}"
    allowed = [int(i) for i in (getattr(org_context, "allowed_org_ids", None) or [])]
    if allowed:
        return "(" + " OR ".join(f"org_id = {i}" for i in allowed) + ")"
    own = getattr(org_context, "current_org_id", None)
    return f"org_id = {int(own)}" if own else None

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

def _prune_index(index, live_ids) -> int:
    """Delete indexed documents whose database row is gone.

    The bulk reindex only adds, so a hard-deleted row stayed searchable for
    ever. The stale hits do not reach the screen -- both routers rebuild their
    results from Postgres by id -- but they are counted in totalHits, so
    pagination reported pages that render empty. Found with 333 documents
    indexed against 121 orders, after purchase orders were hard-deleted and
    duplicate vendors merged.
    """
    live = {int(i) for i in live_ids}
    stale, offset = [], 0
    try:
        while True:
            res = index.get_documents({"limit": 1000, "offset": offset, "fields": ["id"]})
            rows = getattr(res, "results", None) or []
            if not rows:
                break
            for row in rows:
                doc_id = row.get("id") if isinstance(row, dict) else getattr(row, "id", None)
                if doc_id is not None and int(doc_id) not in live:
                    stale.append(doc_id)
            offset += len(rows)
            total = getattr(res, "total", None)
            if total is not None and offset >= int(total):
                break
        for start in range(0, len(stale), 1000):
            index.delete_documents(stale[start:start + 1000])
    except Exception as e:
        # Never let housekeeping break startup; a stale document is a wrong
        # count, an exception here is no search at all.
        logger.warning("Could not prune stale search documents: %s", e)
        return 0
    if stale:
        logger.info("Pruned %d search document(s) with no row behind them.", len(stale))
    return len(stale)


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
            "definition_id",
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
            "definition_id": p.get("definition_id"),
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
        "definition_id": getattr(p, "definition_id", None),
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
            # Still prune: an empty table with a populated index is the worst
            # case, not a reason to skip the cleanup.
            _prune_index(client.index("products"), [])
            return 0
        docs = [format_product_doc(p) for p in products]
        client.index("products").add_documents(docs, primary_key="id")
        _prune_index(client.index("products"), [d["id"] for d in docs])
        logger.info("Successfully bulk indexed %d products to Meilisearch", len(docs))
        return len(docs)
    except Exception as e:
        logger.exception("Failed to bulk index products to Meilisearch: %s", e)
        return 0


# ── Suppliers Meilisearch Index ──────────────────────────────────────────────
#
# The directory was asked to search name, code, contact, email, phone and
# country. Seven ILIKE clauses is not a search: it cannot cope with a typo, a
# partial word or a vendor entered as "FOSHAN GENTLE" and asked for as "gentle
# foshan". Products and orders are already indexed; suppliers are the same
# problem with the same answer.
#
# A supplier is a group-level record -- shared vendors are visible to every
# company -- so the filter is not simply org_id: it is "shared, or mine".

def init_suppliers_index():
    """Ensure the suppliers index exists with the right searchable fields."""
    client = get_meili_client()
    if not client:
        return False
    try:
        try:
            client.create_index("suppliers", {"primaryKey": "id"})
        except Exception:
            pass
        index = client.index("suppliers")
        try:
            index.update(primary_key="id")
        except Exception:
            pass
        index.update_searchable_attributes([
            "name",
            "code",
            "contact_person",
            "email",
            "phone",
            "country",
            "identifier_values",
        ])
        index.update_filterable_attributes([
            "is_active",
            "is_deleted",
            "is_shared",
            "org_id",
            "default_currency",
            "country",
        ])
        logger.info("Meilisearch 'suppliers' index initialized successfully.")
        return True
    except Exception as e:
        logger.exception("Failed to initialize Meilisearch 'suppliers' index: %s", e)
        return False


def format_supplier_doc(s, identifier_values: Optional[List[str]] = None) -> Dict[str, Any]:
    """A supplier as the index sees it.

    Identifiers are included because a buyer looking for a vendor by its tax or
    registration number is looking for the vendor, and that is exactly the
    search that stops a duplicate being created.
    """
    return {
        "id": str(getattr(s, "supplier_id", None) or getattr(s, "id", "")),
        "supplier_id": getattr(s, "supplier_id", None),
        "name": getattr(s, "name", None),
        "code": getattr(s, "code", None),
        "contact_person": getattr(s, "contact_person", None),
        "email": getattr(s, "email", None),
        "phone": getattr(s, "phone", None),
        "country": getattr(s, "country", None),
        "address": getattr(s, "address", None),
        "default_currency": getattr(s, "default_currency", None) or "USD",
        "is_active": bool(getattr(s, "is_active", True)),
        "is_shared": bool(getattr(s, "is_shared", False)),
        "is_deleted": bool(getattr(s, "is_deleted", False)),
        "org_id": getattr(s, "org_id", None),
        "identifier_values": identifier_values or [],
    }


def supplier_scope_filter(org_context) -> Optional[str]:
    """Shared vendors, plus the ones this user's companies own.

    The same rule as apply_shared_or_org_filter. Written here so a search can
    never widen what a list query would narrow.
    """
    if org_context is None:
        return None
    selected = getattr(org_context, "selected_org_id", None)
    if selected:
        return f"(is_shared = true OR org_id = {int(selected)})"
    allowed = [int(i) for i in (getattr(org_context, "allowed_org_ids", None) or [])]
    if allowed:
        owned = " OR ".join(f"org_id = {i}" for i in allowed)
        return f"(is_shared = true OR {owned})"
    own = getattr(org_context, "current_org_id", None)
    return f"(is_shared = true OR org_id = {int(own)})" if own else "is_shared = true"


def sync_supplier_document(supplier, identifier_values: Optional[List[str]] = None):
    """Adds or updates a single supplier in Meilisearch."""
    client = get_meili_client()
    if not client:
        return
    try:
        doc = format_supplier_doc(supplier, identifier_values)
        client.index("suppliers").add_documents([doc], primary_key="id")
        logger.info("Synced supplier %s to Meilisearch", doc.get("id"))
    except Exception as e:
        logger.error("Failed to sync supplier to Meilisearch: %s", e)


def remove_supplier_document(supplier_id: int):
    """Removes a supplier from Meilisearch."""
    client = get_meili_client()
    if not client:
        return
    try:
        client.index("suppliers").delete_document(str(supplier_id))
        logger.info("Removed supplier %s from Meilisearch", supplier_id)
    except Exception as e:
        logger.error("Failed to remove supplier from Meilisearch: %s", e)


def search_suppliers_with_total(
    query_str: str,
    filters: Optional[List[str]] = None,
    limit: int = 25,
    offset: int = 0
):
    """Search suppliers, returning the page and the true total.

    Returns (None, 0) when there is no search engine, which the caller reads as
    "fall back to SQL" -- never as "no suppliers".
    """
    client = get_meili_client()
    if not client:
        return None, 0
    try:
        search_params = {
            "limit": limit,
            "offset": offset,
            # Every word must match. On the default strategy a search for the
            # code VEND-0181 drops a term and matches all 136 vendors, because
            # they all contain "VEND" -- the right row ranked first and the
            # count said 136.
            "matchingStrategy": "all",
        }
        if filters:
            search_params["filter"] = " AND ".join(f for f in filters if f)
        res = client.index("suppliers").search(query_str or "", search_params)
        hits = res.get("hits", [])
        total = res.get("totalHits") or res.get("estimatedTotalHits") or len(hits)
        return hits, total
    except Exception as e:
        logger.error("Meilisearch search_suppliers_with_total error: %s", e)
        return None, 0


def bulk_index_all_suppliers(db):
    """Bulk sync every live supplier, with its identifiers, to Meilisearch."""
    client = get_meili_client()
    if not client:
        return 0
    try:
        init_suppliers_index()
        from sqlalchemy import text as _text
        from Model.containermgmt.Cinfo.Supplier import Supplier

        suppliers = db.query(Supplier).filter(Supplier.is_deleted == False).all()
        if not suppliers:
            _prune_index(client.index("suppliers"), [])
            return 0

        values = {}
        try:
            for row in db.execute(_text("""
                SELECT supplier_id, value FROM containermgmt.supplier_identifiers
                WHERE is_deleted IS NOT TRUE
            """)):
                values.setdefault(row[0], []).append(row[1])
        except Exception:
            # The identifiers table may not exist yet on an older database.
            values = {}

        docs = [
            format_supplier_doc(s, values.get(s.supplier_id, []))
            for s in suppliers
        ]
        client.index("suppliers").add_documents(docs, primary_key="id")
        _prune_index(client.index("suppliers"), [d["id"] for d in docs])
        logger.info("Successfully bulk indexed %d suppliers to Meilisearch", len(docs))
        return len(docs)
    except Exception as e:
        logger.exception("Failed to bulk index suppliers to Meilisearch: %s", e)
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
            "supplier_name_current",
            "item_descriptions",
        ])
        index.update_filterable_attributes([
            "doc_type",
            "status",
            "status_label",
            "lifecycle_stage",
            "urgent_action",
            # A reopened document is filterable in its own right: it is locked to
            # everyone else, and the lists are where anyone would look for it.
            "revision_open",
            "supplier_id",
            "is_deleted",
            "org_id",
        ])
        logger.info("Meilisearch 'purchase_orders' index initialized successfully.")
        return True
    except Exception as e:
        logger.exception("Failed to initialize Meilisearch 'purchase_orders' index: %s", e)
        return False

def _revision_open_for_index(o) -> bool:
    """Read from the document's own audit trail, the one source for this.

    A stale value here would show the lists a lock that is not there, or hide one
    that is, so it is derived at sync time rather than carried on the row.
    """
    # Only CONFIRMED can hold an open window, and this walks the document's
    # snapshots, so everything else answers without a query.
    if (getattr(o, "lifecycle_stage", None) or "DRAFT").upper() != "CONFIRMED":
        return False
    try:
        from Routes.Orders.OrderRouter import _revision_is_open
        return bool(_revision_is_open(o))
    except Exception:
        return False


def format_order_doc(o) -> Dict[str, Any]:
    """Formats a PurchaseOrder model or dictionary into a Meilisearch document."""
    if isinstance(o, dict):
        return {
            "id": o.get("id"),
            "po_number": o.get("po_number") or "",
            "po_nce": o.get("po_nce") or "",
            "company": o.get("supplier_name_at_issue") or o.get("company") or "",
            "supplier_name_current": o.get("supplier_name_current") or o.get("company") or "",
            "goods_description": o.get("goods_description") or "",
            "origin_rfq_number": o.get("origin_rfq_number") or "",
            "consignee": o.get("consignee") or "",
            "doc_type": o.get("doc_type") or "PO",
            "status": o.get("status") or "DRAFT",
            "status_label": o.get("status_label") or "",
            "lifecycle_stage": o.get("lifecycle_stage") or "DRAFT",
            "urgent_action": bool(o.get("urgent_action", False)),
            "revision_open": bool(o.get("revision_open", False)),
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

    # The vendor name as the document was raised. Vendors are shared and
    # editable, so resolving live would make search disagree with the printed
    # order -- the same bug the snapshot column was added to close.
    live_name = ""
    if getattr(o, "supplier_rel", None) and getattr(o.supplier_rel, "name", None):
        live_name = o.supplier_rel.name
    supp_name = (
        getattr(o, "supplier_name_at_issue", None)
        or getattr(o, "company", None)
        or live_name
        or ""
    )

    return {
        "id": o.id,
        "po_number": o.po_number or "",
        "po_nce": getattr(o, "po_nce", None) or "",
        "company": supp_name or "",
        # Indexed as well, so correcting a vendor's name still finds its older
        # documents -- the snapshot alone would hide them.
        "supplier_name_current": live_name or supp_name or "",
        "goods_description": getattr(o, "goods_description", None) or "",
        "origin_rfq_number": getattr(o, "origin_rfq_number", None) or "",
        "consignee": getattr(o, "consignee", None) or "",
        "doc_type": getattr(o, "doc_type", None) or "PO",
        "status": getattr(o, "status", None) or "DRAFT",
        "status_label": getattr(o, "status_label", None) or "",
        "lifecycle_stage": getattr(o, "lifecycle_stage", None) or "DRAFT",
        "urgent_action": bool(getattr(o, "urgent_action", False)),
        "revision_open": _revision_open_for_index(o),
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
            _prune_index(client.index("purchase_orders"), [])
            return 0
        docs = [format_order_doc(o) for o in orders]
        client.index("purchase_orders").add_documents(docs, primary_key="id")
        _prune_index(client.index("purchase_orders"), [d["id"] for d in docs])
        logger.info("Successfully bulk indexed %d orders to Meilisearch", len(docs))
        return len(docs)
    except Exception as e:
        logger.exception("Failed to bulk index orders to Meilisearch: %s", e)
        return 0


