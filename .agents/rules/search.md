# Meilisearch Search Rules

## When to Use Meilisearch

Use Meilisearch for any user-facing search where:
- The user types a search term into a search box.
- The entity dataset can grow to thousands or more records.
- Typo tolerance, prefix matching, or fuzzy matching is desirable.

**Currently indexed entities:** Products (index name: `products`)

---

## The Search Service

All Meilisearch operations go through `Services/search_service.py`.

Never import `meilisearch` directly in a route or model.
Never create a new Meilisearch client outside the service.

### Available functions

| Function | Purpose |
|---|---|
| `get_meili_client()` | Returns singleton client, handles unavailability gracefully |
| `init_products_index()` | Configures searchable/filterable attributes |
| `format_product_doc(p)` | Serializes Product model or dict to Meilisearch document |
| `sync_product_document(product)` | Adds/updates one product in the index |
| `remove_product_document(product_id)` | Removes a product from the index |
| `search_products(query, filters, limit, offset)` | Returns hits list |
| `search_products_with_total(query, filters, limit, offset)` | Returns (hits, total) |
| `bulk_index_all_products(db)` | Full re-index from database |

---

## Keeping the Index in Sync

The Meilisearch index must be kept in sync with the database at all times.

### On product create
```python
from Services.search_service import sync_product_document
# After db.commit()
sync_product_document(product)
```

### On product update
```python
# After db.commit()
db.refresh(product)
sync_product_document(product)
```

### On product delete (soft delete)
```python
from Services.search_service import remove_product_document
# After marking is_deleted = True and db.commit()
remove_product_document(product.id)
```

If you add a new field to the product that should be searchable:
1. Add it to `format_product_doc()` in `search_service.py`.
2. Add it to `update_searchable_attributes()` in `init_products_index()`.
3. Trigger a `bulk_index_all_products()` to re-index existing records.

---

## Searchable Attributes (Current)

```python
index.update_searchable_attributes([
    "name",
    "sku",
    "code",
    "factory_code",      # Default vendor SKU
    "factory_codes",     # All vendor SKUs (array)
    "brand",
    "category_name",
    "description",
])
```

## Filterable Attributes (Current)

```python
index.update_filterable_attributes([
    "status",
    "is_deleted",
    "category_id",
    "default_supplier_id",
    "org_id",            # ALWAYS filter by org_id for multi-tenant isolation
])
```

---

## Authorization in Search

Meilisearch must never bypass authorization.

Every search call must apply `org_id` filter to restrict results to the current tenant:

```python
filters = [f"org_id = {current_user.org_id}", "is_deleted = false", "status = active"]
hits = search_products(query, filters=filters)
```

If the user does not have permission to view supplier/vendor information,
filter supplier-related fields out of the response before returning to the frontend.
Do not rely on the frontend to hide fields that were returned in the response.

---

## SQL Fallback

If Meilisearch is unavailable, fall back to a basic PostgreSQL ILIKE query for critical paths only.
The fallback must:
- Apply all the same `org_id` and `is_deleted` filters.
- Support pagination.
- Log a warning when the fallback is used.

Do not use SQL ILIKE as the primary search path.

---

## Adding a New Searchable Entity

1. Create a new index in `search_service.py` (e.g. `init_suppliers_index()`).
2. Create `format_{entity}_doc()`, `sync_{entity}_document()`, `remove_{entity}_document()`.
3. Register index init in `startup_event` in `containerMgmt.py`.
4. Call sync functions on every create/update/delete in the router.
5. Always include `org_id` as a filterable attribute.
6. Always apply `org_id` filter on every search call.
