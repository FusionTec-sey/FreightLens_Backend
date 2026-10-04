"""Internal source-capacity claim for a future atomic receipt posting coordinator.

This helper never commits and has no public route. The caller must place it inside
the same execute_once effect as stock movement, valuation and outbox writes.
"""
from decimal import Decimal
from sqlalchemy import func
from Model.containermgmt.Inventory.ReceiptSourceUse import InventoryReceiptSourceUse
from Services.inventory_receipt_review_service import receipt_manifest_binding
from Services.manager_case_service import consume_case
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import apply_org_filter


def check_receipt_source(db, context, *, manifest_key, authorize):
    """Outer execute_once guard: call on first attempt and every replay."""
    return receipt_manifest_binding(db, context, manifest_key, authorize=authorize)


def consume_receipt_source(db, context, actor_id, operation_key, *, manifest_key, case_key, authorize):
    if not db.in_transaction():
        raise ValueError('Receipt source consumption requires an active posting transaction')
    binding = check_receipt_source(db, context, manifest_key=manifest_key, authorize=authorize)
    snapshot = binding.details['snapshot']
    source = snapshot['source']
    quantity = Decimal(source['base_quantities']['received_quantity'])
    existing = apply_org_filter(db.query(InventoryReceiptSourceUse).filter_by(
        org_id=context.org_id, manifest_key=manifest_key, is_deleted=False),
        InventoryReceiptSourceUse, context).one_or_none()
    if existing is not None:
        raise PostingConflict('Receipt manifest has already consumed its source')
    consumed = apply_org_filter(db.query(func.coalesce(func.sum(InventoryReceiptSourceUse.quantity), 0)).filter(
        InventoryReceiptSourceUse.org_id == context.org_id,
        InventoryReceiptSourceUse.receipt_id == source['receipt_id'],
        InventoryReceiptSourceUse.receipt_item_id == source['receipt_item_id'],
        InventoryReceiptSourceUse.is_deleted.is_(False)), InventoryReceiptSourceUse, context).scalar()
    if Decimal(consumed) + quantity > quantity:
        raise PostingConflict('Receipt line quantity has already been consumed')
    # Source revalidation above owns the receipt-line lock. Consumption of the
    # exact approval and capacity claim then share the future outer transaction.
    consume_case(db, context, actor_id, operation_key, case_key=case_key, binding=binding,
        load_binding=lambda session: receipt_manifest_binding(session, context, manifest_key, authorize=authorize),
        authorize=authorize)
    row = InventoryReceiptSourceUse(org_id=context.org_id, operation_key=operation_key,
        manifest_key=manifest_key, receipt_id=source['receipt_id'], receipt_item_id=source['receipt_item_id'],
        quantity=quantity, base_unit=source['base_unit'], created_by=actor_id)
    db.add(row); db.flush()
    return row
