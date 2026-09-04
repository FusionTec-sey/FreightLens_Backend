from Model.db import engine, SessionLocal
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.seed import DEFAULT_ORDER_STATUSES
from sqlalchemy import text

print("1. Running ALTER TABLE queries...")
with engine.connect() as conn:
    stmts = [
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS request_id INTEGER REFERENCES containermgmt.store_requests(id);",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) DEFAULT 'NONE';",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS production_status VARCHAR(50) DEFAULT 'NOT_STARTED';",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS shipment_status VARCHAR(50) DEFAULT 'NOT_SHIPPED';",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS receipt_status VARCHAR(50) DEFAULT 'PENDING';",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS total_amount NUMERIC(14, 2);",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS advance_amount NUMERIC(14, 2);",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS balance_amount NUMERIC(14, 2);",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'USD';",
        "ALTER TABLE containermgmt.purchase_orders ADD COLUMN IF NOT EXISTS org_id INTEGER REFERENCES usercredentials.organisations(id) DEFAULT 1;",
        "ALTER TABLE containermgmt.order_status ADD COLUMN IF NOT EXISTS badge_color VARCHAR(200);"
    ]
    for s in stmts:
        conn.execute(text(s))
    conn.commit()
print("ALTER TABLE statements succeeded.")

print("2. Syncing 14 Lifecycle Statuses...")
db = SessionLocal()
for status_id, name, code, seq, progress, color, badge_color in DEFAULT_ORDER_STATUSES:
    st = db.query(OrderStatus).filter((OrderStatus.id == status_id) | (OrderStatus.code == code)).first()
    if st:
        st.name = name
        st.code = code
        st.sequence_order = seq
        st.progress = progress
        st.color = color
        st.badge_color = badge_color
        st.is_active = True
    else:
        st = OrderStatus(
            id=status_id,
            name=name,
            code=code,
            sequence_order=seq,
            progress=progress,
            color=color,
            badge_color=badge_color,
            is_active=True
        )
        db.add(st)
db.commit()

# Re-map existing PO statuses
status_map = {
    'PENDING': 'DRAFT',
    'QUOTE_SENT': 'SOURCING',
    'QUOTE_RECEIVED': 'SOURCING',
    'PI_CONFIRMED': 'ORDERED',
    'UNDER_PRODUCTION': 'IN_PRODUCTION',
    'READY_TO_LOAD': 'READY',
    'SEA_WAY': 'SHIPPED',
    'RECEIVED': 'RECEIVED'
}
for po in db.query(PurchaseOrder).all():
    new_code = status_map.get(po.status, po.status)
    matched_st = db.query(OrderStatus).filter(OrderStatus.code == new_code).first()
    if matched_st:
        po.status_id = matched_st.id
        po.status = matched_st.code
        po.status_label = matched_st.name
    # Assign org_id based on sheet_type / consignee if null
    if not po.org_id or po.org_id == 1:
        if 'NOBLE' in (po.sheet_type or '').upper() or 'NOBLE' in (po.consignee or '').upper():
            po.org_id = 2
        elif 'SAHAJ' in (po.sheet_type or '').upper():
            po.org_id = 1
db.commit()

print("3. Verification of seeded 14 statuses:")
for s in db.query(OrderStatus).order_by(OrderStatus.sequence_order).all():
    print(f"  #{s.sequence_order:02d} (ID={s.id:02d}) | {s.code:16s} | {s.name:20s} | {s.progress:3d}% | {s.color}")

print("\n4. Verification of sample Purchase Orders with org_id and status:")
for po in db.query(PurchaseOrder).filter(PurchaseOrder.is_deleted != True).all():
    print(f"  PO={po.po_number} | org_id={po.org_id} | status={po.status_label} ({po.status})")
