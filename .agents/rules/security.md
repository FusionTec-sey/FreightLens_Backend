# Security & RBAC Rules

## Threat Model

FreightLens handles commercially sensitive data:
- Supplier identities, pricing, and contracts
- Payment records and Swift/bank proofs
- Purchase order values and negotiation history
- Factory codes (vendor SKUs) and sourcing relationships

A breach of this data can cause direct financial and competitive harm.

---

## Role-Based Access Control (RBAC)

### Current roles and permission areas

| Role | Typical permissions |
|---|---|
| Admin | Full access to all modules and data |
| Manager | Full order/procurement visibility including vendor pricing |
| Buyer | Purchase orders, RFQs, vendor data, payments |
| Accounts | Financial data, unit costs, payment proofs |
| Site Engineer | Create store requests, view orders assigned to them — no vendor/pricing data |
| Warehouse | Goods receiving, stock management — no vendor/pricing data |

### Permission checks in code

```python
# Server-side helpers in auth/security_guards.py:
can_view_cost = is_financial_user(current_user, org_context)
can_view_vendor = can_view_supplier_user(current_user, org_context)
```

Always check permissions server-side before returning sensitive data.

---

## Vendor / Supplier Data Protection

Vendor and supplier information is permission-controlled.

Protected data includes:
- Vendor name, address, contact, email, phone
- Vendor bank and payment information
- Vendor tax identifiers
- Vendor pricing (unit cost, quoted cost)
- Purchase history and order volumes
- Vendor quotations and submitted prices
- Vendor contracts and commercial agreements
- Vendor-related documents
- Factory codes / vendor SKUs
- Supplier IDs embedded in URLs

### Enforcement rules

1. Do NOT fetch vendor data from the database unless the user has permission.
2. Do NOT include vendor data in API responses for unauthorised users.
3. Do NOT return vendor data and then hide it in the frontend with CSS or React conditionals.
4. Do NOT expose vendor data through search results.
5. Do NOT expose vendor data through autocomplete, dropdowns, or exports.

### Query-level filtering (preferred pattern)

```python
# Incorrect — fetches all then filters
all_vendors = db.query(Supplier).all()
if not can_view_vendor:
    all_vendors = []

# Correct — never fetches unauthorized data
if can_view_vendor:
    vendors = apply_shared_or_org_filter(
        db.query(Supplier).filter(Supplier.is_deleted.is_(False)),
        Supplier,
        org_context,
    ).all()
else:
    vendors = []
```

### Related data — check at each access level

Authorization applies through the full relationship chain:

```
Purchase Order -> Vendor -> Vendor Pricing -> Vendor Bank Details
```

A user permitted to view Purchase Orders does NOT automatically get Vendor Pricing.
Check the appropriate permission at each level before including the data.

---

## IDOR Prevention — UUID on Document Primary Keys

Document download URLs must not be predictable or enumerable.

### The problem with integer IDs
- `/orders/documents/1042/download` — an attacker can try 1041, 1043, 1044...
- Exposes commercial contracts, proformas, Swift payment slips

### The solution: UUID primary keys

```python
# OrderDocument uses UUID PK:
id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
```

Download endpoints accept UUID strings:
```
GET /orders/documents/c0326442-da47-4993-8a0a-fae120f2b388/download
```

**This pattern must be preserved.** Do not revert to integer IDs for documents.
For any new entity that has a file download endpoint, use UUID primary keys.

---

## API Authorization Checks

Every endpoint returning or modifying protected data must:

1. Verify the user is authenticated (JWT).
2. Verify the user has the required module (`require_module`).
3. Verify the user has the required permission.
4. Resolve `OrgContext` and use `apply_org_filter` or `apply_shared_or_org_filter`.
5. Return 403 or 404 if any check fails — never return partial data.

```python
@router.get("/orders/{order_id}/documents")
async def list_order_documents(
    order_id: int,
    current_user = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
):
    # 1. org isolation
    order_query = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == order_id,
        PurchaseOrder.is_deleted.is_(False),
    )
    order = apply_org_filter(order_query, PurchaseOrder, org_context).first()
    if not order:
        raise HTTPException(404, "Order not found")

    # 2. permission gate
    docs = db.query(OrderDocument).filter(
        OrderDocument.order_id == order_id
    ).all()

    # 3. strip vendor pricing if user lacks permission
    can_view_cost = is_financial_user(current_user, org_context)
    return [serialize_doc(d, include_cost=can_view_cost) for d in docs]
```

---

## Search Authorization

Meilisearch does not enforce authorization by itself.

Every search call must:
1. Apply the active/allowed IDs from `OrgContext` as an `org_id` filter.
2. Apply `is_deleted = false` filter.
3. Strip vendor/cost fields from results for unauthorised users before returning.

```python
org_ids = [org_context.org_id] if org_context.selected_org_id else org_context.allowed_org_ids
filters = [
    f"org_id IN [{', '.join(str(org_id) for org_id in org_ids)}]",
    "is_deleted = false",
    "status = active"
]
hits, total = search_products_with_total(query, filters=filters)

if not can_view_vendor:
    for hit in hits:
        hit.pop("suppliers", None)
        hit.pop("factory_code", None)
        hit.pop("unit_cost", None)
```

---

## Frontend Security Boundary

The frontend MAY hide:
- Buttons and actions
- Menu items and navigation
- Table columns
- Tabs and sections

based on user permissions — for a better user experience.

The frontend MUST NOT be the only security layer.
Backend authorization is always mandatory, regardless of what the frontend hides.

Do not assume a user cannot access an endpoint because the frontend hides the button.
Users can always call the API directly.

---

## Sensitive Data in Logs

Do not log:
- Authentication tokens or JWT payloads
- Passwords or password hashes
- Vendor pricing data
- Payment amounts or bank details

Log operation outcomes without the sensitive values:
```python
logger.info("Payment recorded for order %s, payment_id=%s", order.po_number, payment.payment_id)
# NOT: logger.info("Payment of %s %s recorded", amount, currency)
```
