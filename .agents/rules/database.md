# Database Rules

## PostgreSQL Schemas

The project uses two PostgreSQL schemas:

| Schema | Purpose |
|---|---|
| `containermgmt` | All business data: orders, products, containers, documents |
| `usercredentials` | Users, roles, permissions, organisations, sessions |

Every SQLAlchemy model must explicitly declare its schema:

```python
class PurchaseOrder(Base, AuditMixin, OrgMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = {"schema": "containermgmt"}
```

---

## Model Mixins — Always Use Them

Two standard mixins live in `Model/mixins.py`. Use both for every business entity:

### AuditMixin
Automatically adds:
- `created_at` — timestamp with timezone
- `updated_at` — auto-updated timestamp
- `is_deleted` — soft-delete flag
- `deleted_at` — deletion timestamp
- `created_by`, `updated_by`, `deleted_by` — FK to `usercredentials.users`

### OrgMixin
Adds:
- `org_id` — FK to `usercredentials.organisations` with index

Current stabilization deviation: `OrgMixin.org_id` remains nullable and defaults to
organisation `1`. New code must always assign the resolved organisation explicitly.
Do not rely on that default; Phase 2 will remove it after legacy rows are classified.

```python
from Model.mixins import AuditMixin, OrgMixin

class MyModel(Base, AuditMixin, OrgMixin):
    __tablename__ = "my_table"
    __table_args__ = {"schema": "containermgmt"}
    id = Column(Integer, primary_key=True)
```

---

## Primary Keys

| Record type | PK type | Reason |
|---|---|---|
| Business entities (products, orders, etc.) | `Integer SERIAL` | Efficient joins, display-friendly |
| Documents and file attachments | `UUID` (`gen_random_uuid()`) | Prevents IDOR enumeration on download URLs |
| Payment records linked to documents | Reference UUID from documents | Consistency |

UUID primary key pattern (SQLAlchemy):
```python
import uuid
from sqlalchemy.dialects.postgresql import UUID

class OrderDocument(Base):
    __tablename__ = "order_documents"
    __table_args__ = {"schema": "containermgmt"}
    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
```

---

## Soft Deletes

Never hard-delete business data. Use `AuditMixin`'s `is_deleted` flag.

```python
# Correct
db.query(Product).filter(Product.is_deleted == False, Product.org_id == org_id)

# Incorrect — returns deleted records
db.query(Product).filter(Product.org_id == org_id)
```

Always filter `is_deleted == False` on every query unless specifically retrieving deleted records for audit purposes.

---

## Indexes

Add an index for every column that appears in:
- `WHERE` clauses (filters)
- `ORDER BY` (sorting)
- `JOIN` conditions
- Foreign key columns not already indexed by SQLAlchemy

```python
__table_args__ = (
    Index("ix_purchase_orders_org_id", "org_id"),
    Index("ix_purchase_orders_status", "status"),
    Index("ix_purchase_orders_supplier_id", "supplier_id"),
    {"schema": "containermgmt"},
)
```

`org_id` is already indexed by `OrgMixin`. Do not add it again.

---

## Avoiding N+1 Queries

Use eager loading for relationships that are always accessed together:

```python
# Bad: N+1 — loads each supplier per order separately
orders = db.query(PurchaseOrder).all()
for order in orders:
    print(order.supplier.name)  # N separate queries

# Good: joins in one query
from sqlalchemy.orm import joinedload
orders = db.query(PurchaseOrder).options(
    joinedload(PurchaseOrder.supplier),
    joinedload(PurchaseOrder.items)
).filter(...).all()
```

Avoid lazy-loaded relationships inside loops where they cause N+1 database access.

---

## Schema Migrations

### Pattern

Every schema change must be in its own `Utils/migrate_{feature}.py` file:

```python
# Utils/migrate_my_feature.py

def ensure_my_feature_schema():
    from Model.db import engine
    from sqlalchemy import text

    with engine.connect() as conn:
        # Check if column exists before adding
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'containermgmt'
              AND table_name = 'my_table'
              AND column_name = 'new_column'
        """))
        if not result.fetchone():
            conn.execute(text("""
                ALTER TABLE containermgmt.my_table
                ADD COLUMN new_column TEXT
            """))
            conn.commit()
```

### Rules
- Migrations must be **idempotent** — safe to run on every server restart.
- Always check if the column/table/index exists before creating it.
- Always `conn.commit()` after DDL.
- Register the migration in `containerMgmt.py` `startup_event`.
- Name clearly: `migrate_order_documents.py`, `migrate_product_suppliers.py`.
- New migrations use the date prefix `migrate_YYYYMMDD_feature.py`.

### Registration (containerMgmt.py)
```python
from Utils.migrate_my_feature import ensure_my_feature_schema
ensure_my_feature_schema()
```

---

## Query Design for Large Datasets

- Use `.limit()` and `.offset()` for all list endpoints.
- Use `COUNT(*)` in a separate query for total count (avoid `len(results)`).
- Use `yield_per()` or `chunk_by()` for bulk processing.
- Never load an entire table into memory to filter it in Python.

```python
# Correct: paginated query
total = db.query(func.count(Product.id)).filter(...).scalar()
items = db.query(Product).filter(...).offset(offset).limit(limit).all()

# Incorrect: loads all then slices
all_products = db.query(Product).all()
page = all_products[offset:offset+limit]
```

---

## Relationships Across Schemas

Cross-schema foreign keys (between `containermgmt` and `usercredentials`) are allowed within the same database instance:

```python
created_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
```

Cross-service references (future microservices) must be **denormalized strings**, not FK constraints. See `FUTURE_ARCHITECTURE.md`.
