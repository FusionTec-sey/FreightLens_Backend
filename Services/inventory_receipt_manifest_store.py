"""Internal append-only proposal save using the shared operation boundary."""
from uuid import UUID
from Model.containermgmt.Inventory.ReceiptManifest import InventoryReceiptManifestRecord
from Schema.InventoryReceiptSchema import InventoryReceiptManifest
from Services.inventory_receipt_manifest_service import prepare_inventory_receipt_manifest
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Utils.org_filter import apply_org_filter


def save_receipt_manifest(factory, context, actor_id, operation_key, payload, *, authorize):
    if not callable(authorize):
        raise ValueError('Receipt manifest permission guard required')
    if not isinstance(operation_key, UUID) or not operation_key.int:
        raise ValueError('Stable nonzero operation identity required')
    if not isinstance(payload, InventoryReceiptManifest):
        raise ValueError('Typed receipt manifest required')
    payload = InventoryReceiptManifest.model_validate(payload.model_dump())
    prepared = {}
    def guard(db):
        prepared['snapshot'] = prepare_inventory_receipt_manifest(db, context, payload, authorize=authorize)
        existing = apply_org_filter(db.query(InventoryReceiptManifestRecord).filter_by(
            manifest_key=operation_key, org_id=context.org_id, is_deleted=False),
            InventoryReceiptManifestRecord, context).one_or_none()
        if existing is not None and existing.snapshot != prepared['snapshot']:
            raise PostingConflict('Receipt source changed; create and review a new manifest')
    def effect(db):
        db.add(InventoryReceiptManifestRecord(manifest_key=operation_key, org_id=context.org_id,
            receipt_id=payload.source.receipt_id, receipt_item_id=payload.source.receipt_item_id,
            snapshot=prepared['snapshot'], created_by=actor_id))
        db.flush()
        result = dict(manifest_key=str(operation_key), status='SAVED', physical_posting_enabled=False)
        return PostingEffect(result, dict(kind='inventory.receipt.manifest-saved', **result))
    return execute_once(factory, context, actor_id, operation_key, 'inventory.receipt.manifest.save.v1',
        payload.model_dump(mode='json'), effect, authorize=guard)
