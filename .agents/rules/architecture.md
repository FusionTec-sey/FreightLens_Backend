# Architecture & Stack

## Project Identity

FreightLens is a multi-module ERP for freight and procurement operations.
Current phase: Phase 1 (Monolith with logical module boundaries).
Future vision: Microservices. See `FUTURE_ARCHITECTURE.md`.

---

## Technology Stack (Locked)

| Layer | Technology |
|---|---|
| Backend framework | FastAPI (Python) |
| Database | PostgreSQL (schemas: `containermgmt`, `usercredentials`) |
| ORM | SQLAlchemy (declarative base) |
| Search | Meilisearch (`Services/search_service.py`) |
| Object storage | RustFS S3-compatible (`Utils/blob_storage.py`) |
| Authentication | JWT (HS256 currently) |
| Frontend | React SPA |
| Containerisation | Docker Compose |
| Background jobs | APScheduler (`cron_jobs.py`) |

---

## Directory Layout

```
Backend/
├── containerMgmt.py          # App factory, startup lifecycle, router registration
├── auth/                     # JWT auth, module guards, permission decorators
│   ├── module_guard.py       # require_module() dependency
│   └── config.py
├── Routes/                   # FastAPI routers, one subfolder per domain
│   ├── Orders/               # PO, RFQ, Receiving, Defects, Documents, Payments
│   ├── Inventory/            # Products, categories
│   ├── BillOfLanding/
│   ├── Container/
│   ├── MasterData/
│   └── ...
├── Model/                    # SQLAlchemy ORM models
│   ├── mixins.py             # AuditMixin, OrgMixin — always use these
│   ├── db.py                 # engine, Base, SessionLocal, get_db
│   └── containermgmt/        # Domain model subpackages
│       ├── Orders/
│       ├── MasterData/
│       └── ...
├── Schema/                   # Pydantic request/response schemas
├── Services/
│   └── search_service.py     # All Meilisearch operations — use this, do not bypass
├── Utils/
│   ├── blob_storage.py       # All RustFS/S3 operations — use this, do not bypass
│   ├── migrate_*.py          # One file per schema migration
│   └── org_filter.py        # Shared org_id query helper
├── Scheduler/                # Cron job definitions
└── FUTURE_ARCHITECTURE.md    # Long-term vision — reference before new modules
```

---

## Module System

Modules gate entire feature areas. Current modules:

| Module key | Feature area |
|---|---|
| `LOGISTICS` | Containers, Bill of Lading, tracking |
| `ORDERS` | Store requests, POs, packing lists, receiving, defects |
| `INVENTORY` | Product master, categories, stock |

### Enforcing module access

Every router that belongs to a module must declare the dependency:

```python
# In containerMgmt.py — this is already done for existing routers
app.include_router(OrderRouter, dependencies=[Depends(require_module("ORDERS"))])
app.include_router(InventoryRouter, dependencies=[Depends(require_module("INVENTORY"))])
```

A new router for a new module area MUST include `require_module`.
Never add business routes without a module guard.

---

## Startup Lifecycle

All one-time setup runs in `containerMgmt.py` `startup_event` in this order:

1. Create PostgreSQL schemas (`containermgmt`, `usercredentials`)
2. Run all `Utils/migrate_*.py` migration scripts (idempotent)
3. Seed reference data via `Model/seed.py`
4. Backfill legacy data (one-shot)
5. Initialise RustFS bucket
6. Bulk index products to Meilisearch

**Rule:** Any new schema migration must be registered here.
**Rule:** Migration scripts must be idempotent (safe to re-run on every restart).

---

## Naming Conventions

### Backend (Python)
- Models: `PascalCase` (e.g. `PurchaseOrder`, `OrderDocument`)
- Routers: `{Domain}Router` (e.g. `OrderRouter`, `InventoryRouter`)
- Migration files: `migrate_{feature_area}.py`
- Services: `{domain}_service.py`
- Utility functions: `snake_case`

### Frontend (React)
- Pages: `{Entity}Page.js` (e.g. `ProductMasterPage.js`)
- Modals: `{Action}{Entity}Modal.js` (e.g. `VendorQuoteEntryModal.js`)
- Reusable components: descriptive name in `UI/UXComponent/`
- Hooks: `use{Feature}.js`

---

## Multi-Tenant Architecture

- Database schema: `containermgmt` (business data), `usercredentials` (auth/users)
- Tenant isolation: row-level via `org_id` on every business data table
- All models inherit `OrgMixin` for `org_id`
- All queries filter `Model.org_id == current_user.org_id`
- Never mix data across organisations

---

## Adding a New Feature — Checklist

1. [ ] Read the existing implementation in the same domain area.
2. [ ] Identify existing models, services, utilities to reuse.
3. [ ] Create SQLAlchemy model (with `AuditMixin` + `OrgMixin`).
4. [ ] Write `Utils/migrate_{feature}.py` migration script.
5. [ ] Register migration in `containerMgmt.py` `startup_event`.
6. [ ] Create Pydantic schemas in `Schema/`.
7. [ ] Create FastAPI router with module guard.
8. [ ] Register router in `containerMgmt.py`.
9. [ ] Sync to Meilisearch if feature involves searchable entities.
10. [ ] Apply authorization checks (see `security.md`).
11. [ ] Implement pagination if the endpoint returns a list (see `pagination.md`).
12. [ ] If an existing rule/standard needs refinement or creates friction, follow the Rule Evolution Protocol in `AGENTS.md` (present rationale & gain approval before updating).

---

## Continuous Improvement & Rule Evolution

Development standards are living guidelines designed to guarantee system scalability, security, and cleanliness.
- If a technical bottleneck, performance edge-case, or superior paradigm highlights a scope of improvement in any rule:
  1. Clearly explain **why** the current standard is insufficient for the task.
  2. Explain **how** updating it benefits future architecture and maintenance.
  3. Seek explicit user approval before applying changes or updating `.agents/rules/`.
- Do not introduce rule change proposals unnecessarily; only trigger when there is a concrete, justifiable gain.
