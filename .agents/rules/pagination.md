# Pagination Rules

## Fundamental Rule

Any database-backed list that can grow significantly must be paginated server-side.

Never:
- Return all records of a table to paginate them in the frontend.
- Use `.all()` on a query that could return thousands of rows and then slice in Python.
- Use `len(results)` for total count after fetching all records.

Always:
- Apply `.offset()` and `.limit()` at the database level.
- Return total count from a separate `COUNT(*)` query.

---

## Standard Pagination Parameters

Every list endpoint must accept:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | int | 1 | Current page (1-indexed) |
| `limit` | int | 25 | Records per page (max 200) |
| `search` | str | None | Search query (routes to Meilisearch) |
| `sort_by` | str | None | Column to sort by |
| `sort_dir` | str | `asc` | Sort direction: `asc` or `desc` |
| Domain-specific filters | varies | None | e.g. `status`, `supplier_id`, `category_id` |

```python
@router.get("/inventory/products")
async def list_products(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * limit
    ...
```

---

## Standard Pagination Response

Every list endpoint must return:

```json
{
  "items": [ ...page of records... ],
  "total": 1250,
  "page": 3,
  "pages": 50,
  "limit": 25
}
```

Python helper:
```python
import math

total = db.query(func.count(Product.id)).filter(*filters).scalar()
items = db.query(Product).filter(*filters).offset(offset).limit(limit).all()

return {
    "items": [serialize(p) for p in items],
    "total": total,
    "page": page,
    "pages": math.ceil(total / limit) if total > 0 else 1,
    "limit": limit,
}
```

---

## Filtering

Filters are applied before pagination:

```python
query = db.query(Product).filter(Product.org_id == org_id, Product.is_deleted == False)

if status:
    query = query.filter(Product.status == status)
if category_id:
    query = query.filter(Product.category_id == category_id)
if low_stock_only:
    query = query.filter(Product.current_stock <= Product.min_stock_quantity)

total = query.with_entities(func.count(Product.id)).scalar()
items = query.offset(offset).limit(limit).all()
```

---

## Search Integration with Pagination

When a search query is provided, route through Meilisearch:

```python
if search and search.strip():
    meili_filters = [f"org_id = {org_id}", "is_deleted = false"]
    if status:
        meili_filters.append(f"status = {status}")

    hits, total = search_products_with_total(
        query_str=search,
        filters=meili_filters,
        limit=limit,
        offset=offset,
    )
    # hits are already paginated by Meilisearch
    return {"items": hits, "total": total, "page": page, "pages": ..., "limit": limit}
else:
    # Fall back to database query with filters
    ...
```

---

## Sorting

Support sorting via `sort_by` and `sort_dir` parameters.
Whitelist allowed sort columns — never pass user input directly to `.order_by()`:

```python
ALLOWED_SORT_COLUMNS = {
    "name": Product.name,
    "sku": Product.sku,
    "current_stock": Product.current_stock,
    "created_at": Product.created_at,
}

sort_column = ALLOWED_SORT_COLUMNS.get(sort_by, Product.created_at)
if sort_dir == "desc":
    query = query.order_by(sort_column.desc())
else:
    query = query.order_by(sort_column.asc())
```

---

## Frontend Pagination Requirements

The frontend pagination control must:
- Reset to page 1 whenever a filter or search changes.
- Show current page and total pages.
- Provide Previous/Next buttons.
- Provide First/Last page buttons.
- Provide a rows-per-page selector (options: 10, 25, 50, 100).
- Provide a jump-to-page input when total pages > 2.
- Show "Showing X to Y of Z records" count.
- Disable Previous at page 1, disable Next at last page.

Standard state variables (React):
```javascript
const [page, setPage] = useState(1);
const [pageSize, setPageSize] = useState(25);
const [totalPages, setTotalPages] = useState(1);
const [totalCount, setTotalCount] = useState(0);
const [jumpPageInput, setJumpPageInput] = useState("");
```

Changing any filter or search must call `setPage(1)` before re-fetching.

---

## Entities That Must Be Paginated

Any list view containing these entities must implement server-side pagination:

| Entity | Notes |
|---|---|
| Products | Use Meilisearch for search |
| Purchase Orders | Filter by status, supplier, date range |
| Store Requests | Filter by status, requester |
| Goods Receipts | Filter by status, date |
| Audit Logs | Date range mandatory |
| Containers | Filter by status, vessel |
| Bill of Lading | Filter by date, status |
| Suppliers | Search by name, filter by type |
| Order Documents | Filter by document type |
| Defect Reports | Filter by status |
