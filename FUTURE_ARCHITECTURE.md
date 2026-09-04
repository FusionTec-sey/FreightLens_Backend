# FreightLens — Future Architecture Vision
### *(Long-term Reference — Not for Immediate Implementation)*

> This document captures the target architecture for FreightLens as a multi-tenant SaaS platform 
> with independently purchasable modules. It is a design reference — implementation is phased 
> and the "Build Now" plan is a separate document.

---

## Vision

Sell FreightLens as two independent, combinable SaaS products:

| Product | What it does | Who buys it |
|---|---|---|
| **FreightLens Logistics** | Container tracking, BoL, damage reports, port operations | Freight forwarders, shipping agents, port operators |
| **FreightLens Procurement** | Store requests, purchase orders, packing lists, GRN, defects | Procurement teams, importers, warehouse managers |
| **FreightLens Complete** | Both above, with shared data between them | Full-stack logistics+procurement companies |

---

## Target Architecture (24–36 months out)

```
                    ┌────────────────────────────────┐
                    │    Single React SPA Frontend    │
                    │  Module visibility = JWT-driven │
                    └───────────┬────────────────────┘
                                │  HTTPS
                    ┌───────────▼────────────────────┐
                    │     API Gateway (Nginx/Traefik) │
                    │     Single entry: port 443      │
                    └──┬──────────┬──────────────────┘
                       │          │
          ┌────────────▼──┐  ┌────▼───────────────┐  ┌──────────────────────┐
          │  Auth Service │  │  Logistics Service  │  │  Orders Service      │
          │  port 9003    │  │  port 9001          │  │  port 9002           │
          │               │  │                     │  │                      │
          │ • Login/JWT   │  │ • ContainerDetails  │  │ • StoreRequests      │
          │ • Users       │  │ • BillOfLading      │  │ • PurchaseOrders     │
          │ • Roles       │  │ • DamageReports     │  │ • PackingLists       │
          │ • Permissions │  │ • ContainerDocs     │  │ • GoodsReceiving     │
          │ • Tenants     │  │ • ShippingTracking  │  │ • DefectReports      │
          │ • Modules     │  │ • Cron (status)     │  │ • OrderDocuments     │
          └───────┬───────┘  └────────┬────────────┘  └──────────┬───────────┘
                  │                   │                           │
                  ▼                   ▼                           ▼
         ┌─────────────┐    ┌──────────────────┐     ┌──────────────────┐
         │ usercreds   │    │  logistics_db    │     │  orders_db       │
         │ (Postgres)  │    │  (Postgres)      │     │  (Postgres)      │
         └─────────────┘    └──────────────────┘     └──────────────────┘
                  │                   │                           │
                  └───────────────────┼───────────────────────────┘
                                      ▼
                          ┌───────────────────────┐
                          │  Shared RustFS Bucket │
                          │  containermgmt-blobs  │
                          └───────────────────────┘
```

---

## Tenant & Module Model

### Organisation Table Extensions (future)
```sql
ALTER TABLE usercredentials.organisations
ADD COLUMN modules TEXT[] DEFAULT ARRAY['LOGISTICS','ORDERS'],
ADD COLUMN plan VARCHAR(50) DEFAULT 'trial',
ADD COLUMN subscription_expires_at TIMESTAMPTZ,
ADD COLUMN slug VARCHAR(100) UNIQUE;  -- for subdomain routing
```

### JWT Payload (future)
```json
{
  "user_id": 42,
  "tenant_id": 7,
  "tenant_slug": "acme-shipping",
  "roles": ["Manager"],
  "permissions": ["View_Container", "View_Order", "Upload_Document"],
  "modules": ["LOGISTICS"]
}
```

### Module Enforcement (future backend decorator)
```python
def require_module(module: str):
    """Route guard — returns 403 if tenant hasn't subscribed to the module."""
    def dependency(current_user=Depends(get_current_user)):
        if module not in (current_user.tenant.modules or []):
            raise HTTPException(403, f"'{module}' module not in your subscription")
    return Depends(dependency)

# Applied per route:
@ContainerRouter.get("/containers")
async def get_containers(_=require_module("LOGISTICS"), ...):
    ...
```

### Module Guard in Frontend (future)
```jsx
// PrivateRoute gains requiredModules prop
<Route
  path="/viewContainer"
  element={
    <PrivateRoute requiredModules={['LOGISTICS']}>
      <ContainerEntry />
    </PrivateRoute>
  }
/>

// Sidebar hides items per module
const { modules } = useAuth();
{ modules.includes('LOGISTICS') && <NavItem to="/viewContainer" label="Containers" /> }
{ modules.includes('ORDERS') && <NavItem to="/orders" label="Orders" /> }
```

---

## Service Boundaries

### Auth Service owns:
- `usercredentials.users`
- `usercredentials.roles`
- `usercredentials.permissions`
- `usercredentials.role_permissions`
- `usercredentials.user_roles`
- `usercredentials.organisations` (+ modules, plan, slug)
- `usercredentials.refresh_tokens`
- `usercredentials.session_audit`

### Logistics Service owns:
- `containermgmt.bill_of_lading`
- `containermgmt.container_details`
- `containermgmt.container_docs`
- `containermgmt.report_details`
- `containermgmt.damage_products`
- `containermgmt.report_images`
- `containermgmt.status` (reference data)
- `containermgmt.unload_venue`
- `containermgmt.supplier`
- `containermgmt.vessal`
- `containermgmt.material`
- `containermgmt.container_type`

### Orders Service owns:
- `containermgmt.store_requests` + items
- `containermgmt.purchase_orders` + items
- `containermgmt.packing_lists` + items
- `containermgmt.goods_receipts` + items
- `containermgmt.defect_reports` + images
- `containermgmt.order_documents`
- `containermgmt.order_payments`
- `containermgmt.notifications`

### Cross-Service References (loose coupling, never DB FK across services)
```
GoodsReceipt.container_id  → references Logistics container_id (no FK, denormalized)
GoodsReceipt.container_no  → stored string for display without cross-service call
DefectReport.container_id  → same pattern
```

---

## Cross-Module Data Flow (when both modules active)

```
1. Container arrives at port
   → Logistics: Container status → "Inbound"
   → Logistics emits event: container.arrived { container_id, container_no, arrival_date, tenant_id }

2. Orders service consumes event
   → Finds GoodsReceipt linked to this container_no
   → Sets GoodsReceipt.arrival_date automatically
   → Sends notification to procurement manager

3. Goods inspected
   → Orders: GoodsReceipt.status → "INSPECTED"
   → Orders emits event: goods.inspected { po_id, receipt_id, container_id, tenant_id }

4. Logistics service consumes event (optional)
   → Marks container as "unloading complete"
```

### Message Queue Options (in priority order)
1. **Redis Streams** — simplest, already docker-friendly, no extra infra
2. **RabbitMQ** — when you need guaranteed delivery + dead-letter queues
3. **Kafka** — at enterprise scale with audit trail requirements

---

## Deployment Phases

### Phase 1 — Monolith with logical module boundaries *(current → 6 months)*
Single FastAPI app, single DB, row-level tenant isolation (already done).
Just add `modules[]` to Org table + JWT + frontend guards.

### Phase 2 — Separate Auth service *(6–12 months)*
Extract `usercredentials` into its own FastAPI app.
Other services verify JWT locally using shared secret.
No DB split yet — just routing.

### Phase 3 — Separate Logistics and Orders services *(12–18 months)*
Two Docker containers, each with own DB connection pool.
Cross-service calls via HTTP (authenticated service-to-service JWT).
Events via Redis Streams.

### Phase 4 — Full multi-tenant SaaS infra *(18–36 months)*
- Kubernetes cluster with namespace-per-enterprise-tenant
- Schema-per-tenant Postgres (logistics_{slug}, orders_{slug})
- Tenant onboarding portal
- Billing integration (Stripe)
- White-label frontend per enterprise tenant

---

## Technology Decisions (locked for future reference)

| Concern | Choice | Reason |
|---|---|---|
| Backend framework | FastAPI (Python) | Already in use |
| Auth | JWT HS256 → RS256 eventually | HS256 now, RS256 when services split |
| DB | PostgreSQL | Already in use |
| Object storage | RustFS (S3-compatible) | Already integrated |
| Message queue | Redis Streams (when needed) | Low infra overhead |
| Container orchestration | Docker Compose → Kubernetes | Scale-driven migration |
| Frontend | React SPA (same build, module-gated) | No separate app per module |
| API gateway | Nginx → Traefik | Traefik for K8s dynamic routing |

---

*Last updated: 2026-09-03 | Status: Future Vision — not in current sprint*
