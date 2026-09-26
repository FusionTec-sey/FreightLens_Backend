# API Design Rules (FastAPI)

## Router Structure

Each domain area has its own router file under `Routes/`:

```
Routes/
├── Orders/
│   ├── OrderRouter.py        # PO CRUD, documents, payments
│   ├── StoreRequestRouter.py
│   ├── ReceivingRouter.py
│   └── ...
├── Inventory/
│   └── InventoryRouter.py
├── BillOfLanding/
├── Container/
└── __init__.py               # Exports all routers for containerMgmt.py
```

Never put business logic directly in `containerMgmt.py`.
Never mix unrelated domains in the same router file.

---

## Module Guards

Every business router must be guarded by `require_module`:

```python
from auth.module_guard import require_module

# Applied at registration in containerMgmt.py:
app.include_router(OrderRouter, dependencies=[Depends(require_module("ORDERS"))])
```

Do not add a new router without assigning it to a module.

---

## Permission Checks

Within a router, use the permission check helper to verify fine-grained permissions:

```python
from auth.permissions import require_permission

@router.get("/orders/{order_id}/payments")
async def get_payments(
    order_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Always check permission before querying
    if not current_user.has_permission("View_Payment"):
        raise HTTPException(403, "Insufficient permissions")
    ...
```

Permissions are checked server-side in every endpoint.
Frontend button visibility is not a substitute for backend permission checks.

---

## Request and Response Schemas

All request bodies and response shapes must be defined as Pydantic models in `Schema/`.

```python
# Schema/OrderSchema.py
from pydantic import BaseModel
from typing import Optional, List

class OrderCreateSchema(BaseModel):
    supplier_id: int
    po_number: str
    items: List[OrderItemSchema]

class OrderResponseSchema(BaseModel):
    id: int
    po_number: str
    status: str
    supplier_name: Optional[str]

    class Config:
        from_attributes = True
```

Never return raw SQLAlchemy model objects from endpoints.
Always serialize to a defined schema or a documented dict.

---

## Pagination Contract

Every list endpoint must accept and respect these parameters:

```python
@router.get("/orders")
async def list_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * limit
    ...
```

Every list response must return:
```json
{
  "items": [...],
  "total": 1250,
  "page": 1,
  "pages": 50,
  "limit": 25
}
```

See `pagination.md` for the complete pagination rules.

---

## Error Handling

Use FastAPI `HTTPException` with appropriate status codes:

| Situation | Status code |
|---|---|
| Record not found | 404 |
| Permission denied | 403 |
| Unauthenticated | 401 |
| Invalid input | 422 (FastAPI handles automatically via Pydantic) |
| Business rule violation | 400 with a descriptive message |
| Server error | 500 (log it, return generic message to client) |

```python
raise HTTPException(status_code=404, detail="Purchase order not found")
raise HTTPException(status_code=403, detail="Insufficient permissions to view vendor pricing")
```

Always use `detail=` with a human-readable message.

---

## Org Isolation in Queries

Every query must filter by the authenticated user's organisation:

```python
order = db.query(PurchaseOrder).filter(
    PurchaseOrder.id == order_id,
    PurchaseOrder.org_id == current_user.org_id,  # MANDATORY
    PurchaseOrder.is_deleted == False,
).first()

if not order:
    raise HTTPException(404, "Purchase order not found")
```

Never query by ID alone. Always combine with `org_id` filter.
A missing record and an unauthorised record should both return 404 — never leak existence information.

---

## File Upload Endpoints

File uploads go through `Utils/blob_storage.py`. Never save files to the local filesystem.

```python
from Utils.blob_storage import blob_storage

object_key = f"orders/{po_number}/documents/{filename}"
url = blob_storage.upload_file(file.file, object_key, content_type=file.content_type)
```

See `storage.md` for complete object key conventions.

---

## Logging

Use the module-level logger, not `print()`:

```python
import logging
logger = logging.getLogger("containerMgmt.orders")

logger.info("Created purchase order %s", order.po_number)
logger.error("Failed to upload document: %s", e)
```

Log at `INFO` for normal operations, `ERROR` for failures, `WARNING` for degraded states.

---

## Health Check

The `/health` endpoint at `containerMgmt.py` checks:
- PostgreSQL connectivity
- RustFS bucket availability

New infrastructure dependencies (e.g. Redis, Meilisearch) should be added to the health check.
