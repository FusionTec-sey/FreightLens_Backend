"""Internal opening/consistency helpers. No assignment to a customer at reservation."""
from sqlalchemy import func
from Model.containermgmt.Inventory.StockSerial import (
    StockSerialIdentity, StockSerialMovement, StockSerialPosition,
)
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
        StockSerialIdentity.is_deleted.is_(False),
        ~db.query(StockSerialMovement.id).filter(
            StockSerialMovement.org_id == context.org_id,
            StockSerialMovement.serial_id == StockSerialPosition.serial_id,
            StockSerialMovement.is_deleted.is_(False)).exists(),
    ).group_by(StockSerialPosition.condition)
    counts = dict(apply_org_filter(query, StockSerialPosition, context).all())  # at most three condition groups
    if (sum(counts.values()) != balance.on_hand or counts.get("DAMAGED", 0) != balance.damaged
            or counts.get("QUARANTINED", 0) != balance.quarantined
            or counts.get("AVAILABLE", 0) < balance.reserved):
        raise ValueError("Serial register does not reconcile with stock; review required before posting")


def lock_serials_for_handover(db, context, balance, serial_keys):
    query = db.query(StockSerialIdentity, StockSerialPosition).join(
        StockSerialPosition,
        (StockSerialPosition.serial_id == StockSerialIdentity.id)
        & (StockSerialPosition.org_id == StockSerialIdentity.org_id)
        & (StockSerialPosition.product_id == StockSerialIdentity.product_id),
    ).filter(
        StockSerialIdentity.org_id == context.org_id,
        StockSerialIdentity.product_id == balance.product_id,
        StockSerialIdentity.serial_key.in_(serial_keys),
        StockSerialIdentity.is_deleted.is_(False),
        StockSerialPosition.balance_id == balance.id,
        StockSerialPosition.condition == "AVAILABLE",
        StockSerialPosition.is_deleted.is_(False),
        ~db.query(StockSerialMovement.id).filter(
            StockSerialMovement.org_id == context.org_id,
            StockSerialMovement.serial_id == StockSerialIdentity.id,
            StockSerialMovement.is_deleted.is_(False)).exists(),
    ).order_by(StockSerialIdentity.id).with_for_update(of=StockSerialIdentity)
    rows = apply_org_filter(query, StockSerialIdentity, context).all()
    if {identity.serial_key for identity, _ in rows} != set(serial_keys):
        raise PostingConflict("Every serial must be available on the exact handover balance")
    return rows


def record_serial_handover(db, context, balance, movement, rows, actor_id):
    db.add_all([StockSerialMovement(
        org_id=context.org_id, operation_key=movement.operation_key,
        stock_movement_id=movement.id, serial_id=identity.id,
        product_id=balance.product_id, sequence=1, kind="HANDOVER",
        from_balance_id=balance.id, to_balance_id=None,
        from_condition=position.condition, to_condition=None,
        created_by=actor_id,
    ) for identity, position in rows])
    db.flush()
