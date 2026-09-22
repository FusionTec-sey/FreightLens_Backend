import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("containerMgmt.search")

MEILI_URL = os.getenv("MEILISEARCH_URL", "http://meilisearch:7700")
MEILI_KEY = os.getenv("MEILISEARCH_MASTER_KEY", "sahaj_meili_secret_key_123")

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
            "supplier_name": p.get("supplier_name") or "",
            "current_stock": float(p.get("current_stock") or 0.0),
            "min_stock_quantity": float(p.get("min_stock_quantity") or 0.0),
            "unit_cost": float(p["unit_cost"]) if p.get("unit_cost") is not None else None,
            "currency": p.get("currency") or "USD",
            "status": p.get("status") or "active",
            "is_deleted": bool(p.get("is_deleted", False)),
            "org_id": p.get("org_id")
        }
    
    # SQLAlchemy Product object
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
        "current_stock": float(p.current_stock or 0.0),
        "min_stock_quantity": float(p.min_stock_quantity or 0.0),
        "unit_cost": float(p.unit_cost) if p.unit_cost is not None else None,
        "currency": p.currency or "USD",
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
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Search products using Meilisearch with typo tolerance and prefix matching."""
    client = get_meili_client()
    if not client:
        return []
    try:
        search_params = {
            "limit": limit,
        }
        if filters:
            search_params["filter"] = " AND ".join(filters)

        res = client.index("products").search(query_str or "", search_params)
        return res.get("hits", [])
    except Exception as e:
        logger.error("Meilisearch product search error: %s", e)
        return []
