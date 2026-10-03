"""Internal opening/consistency helpers. No assignment to a customer at reservation."""
from sqlalchemy import func
from Model.containermgmt.Inventory.StockSerial import StockSerialIdentity, StockSerialPosition
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import apply_org_filter


def record_serial_opening(db, context, balance, opening, actor_id):
    keys = [row.serial_key for row in opening.items]
    numbers = [row.serial_number for row in opening.items]
    query = db.query(StockSerialIdentity.id).filter(StockSerialIdentity.org_id == context.org_id,
        StockSerialIdentity.is_deleted.is_(False),
        StockSerialIdentity.serial_key.in_(keys) | ((StockSerialIdentity.product_id == balance.product_id)
                                                   & StockSerialIdentity.serial_number.in_(numbers)))
    if apply_org_filter(query, StockSerialIdentity, context).first():
        raise PostingConflict("Serial identity already registered; use its movement/return history instead of reopening")
    identities = [StockSerialIdentity(org_id=context.org_id, product_id=balance.product_id,
        serial_key=row.serial_key, serial_number=row.serial_number, created_by=actor_id) for row in opening.items]
    db.add_all(identities); db.flush()
    db.add_all([StockSerialPosition(org_id=context.org_id, product_id=balance.product_id,
        serial_id=identity.id, balance_id=balance.id, condition=row.condition, created_by=actor_id)
        for identity, row in zip(identities, opening.items)])
    db.flush()


def verify_serial_projection(db, context, balance):
    # Caller holds the balance lock. Future position writers MUST take it too.
    query = db.query(StockSerialPosition.condition, func.count()).join(StockSerialIdentity,
        (StockSerialIdentity.id == StockSerialPosition.serial_id)
        & (StockSerialIdentity.org_id == StockSerialPosition.org_id)
        & (StockSerialIdentity.product_id == StockSerialPosition.product_id)).filter(
        StockSerialPosition.org_id == context.org_id, StockSerialPosition.balance_id == balance.id,
        StockSerialPosition.product_id == balance.product_id, StockSerialPosition.is_deleted.is_(False),
        StockSerialIdentity.is_deleted.is_(False)).group_by(StockSerialPosition.condition)
    counts = dict(apply_org_filter(query, StockSerialPosition, context).all())  # at most three condition groups
    if (sum(counts.values()) != balance.on_hand or counts.get("DAMAGED", 0) != balance.damaged
            or counts.get("QUARANTINED", 0) != balance.quarantined
            or counts.get("AVAILABLE", 0) < balance.reserved):
        raise ValueError("Serial register does not reconcile with stock; review required before posting")
