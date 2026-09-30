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

Every module-owned business router must be guarded by `require_module`:

```python
from auth.module_guard import require_module

# Applied at registration in containerMgmt.py:
app.include_router(OrderRouter, dependencies=[Depends(require_module("ORDERS"))])
```

Do not add a new module-owned router without assigning it to a module. Authentication,
administration, organisation management, and genuinely cross-module routers may be
exceptions, but the exception must be documented in `docs/ARCHITECTURE.md` and every
endpoint must still enforce authentication and its fine-grained authorization.

---

## Permission Checks

Within a router, use the permission check helper to verify fine-grained permissions:

```python
from auth.security_guards import require_permission

@router.get(
    "/orders/{order_id}/payments",
    dependencies=[Depends(require_permission("View_Payment"))],
)
async def get_payments(
    order_id: int,
    org_context: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db)
):
    query = db.query(Payment).filter(Payment.order_id == order_id)
    return apply_org_filter(query, Payment, org_context).all()
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

## Organisation Isolation in Queries

Resolve the request's organisation scope with `get_org_context`; do not derive tenant
scope directly from `current_user.org_id`. Use the shared query helpers:

```python
base_query = db.query(PurchaseOrder).filter(
    PurchaseOrder.id == order_id,
    PurchaseOrder.is_deleted.is_(False),
)
order = apply_org_filter(base_query, PurchaseOrder, org_context).first()

if not order:
    raise HTTPException(404, "Purchase order not found")
```

For models that explicitly support shared records, such as `Supplier`, use
`apply_shared_or_org_filter`; never emulate shared scope with nullable-org conditions.
Never query a tenant-owned record by ID alone.
A missing record and an unauthorised record should both return 404 — never leak existence information.

---

## File Upload Endpoints

File uploads go through `Utils/blob_storage.py`. Never save files to the local filesystem.

```python
from Utils.blob_storage import blob_storage

folder = f"orders/{po_number}/documents"
object_key = blob_storage.upload_file(
    file_obj=file,
    folder=folder,
    original_filename=file.filename,
)
```

See `storage.md` for complete object key conventions.

All object keys and folders are validated by `Utils.blob_storage._safe_key`. Do not
concatenate user-controlled path segments without validating or normalising them.

---

## Endpoint Test Minimum

For every new or changed protected endpoint, cover at least:
- unauthenticated request rejection;
- a user without the required permission;
- an allowed user in the owning tenant;
- a user from another tenant receiving no data (normally 404 for record endpoints).

Shared/tenant resources also require one shared-row and one tenant-only visibility case.

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
