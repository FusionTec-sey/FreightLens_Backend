"""Receipt-classification review through the existing manager case engine.

Approval is for the exact manifest only, not node authority, cost evidence or
permission to receive a source twice. No case consumption/posting happens here.
"""
from Model.containermgmt.Inventory.ReceiptManifest import InventoryReceiptManifestRecord
from Schema.InventoryReceiptSchema import InventoryReceiptManifest
from Services.inventory_receipt_manifest_service import prepare_inventory_receipt_manifest
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding, request_case, review_case
from Utils.org_filter import apply_org_filter


def receipt_manifest_binding(db, context, manifest_key, *, authorize):
    if not callable(authorize):
        raise ValueError('Receipt review permission guard required')
    if not db.in_transaction():
        raise ValueError('Receipt review requires caller transaction')
    authorize(db)
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Receipt manifest company denied')
    row = apply_org_filter(db.query(InventoryReceiptManifestRecord).filter_by(
        manifest_key=manifest_key, org_id=context.org_id, is_deleted=False),
        InventoryReceiptManifestRecord, context).one_or_none()
    if row is None:
        raise LookupError('Receipt manifest not found')
    payload = InventoryReceiptManifest.model_validate(row.snapshot['manifest'])
    current = prepare_inventory_receipt_manifest(db, context, payload, authorize=authorize)
    if current != row.snapshot:
        raise PostingConflict('Receipt source or classification changed; save a new manifest')
    return CaseBinding(context.org_id, 'inventory.receipt.classify', 'inventory.receipt.manifest',
        str(row.manifest_key), 1, dict(snapshot=row.snapshot, manifest_created_by=row.created_by))


def request_receipt_review(db, context, actor_id, operation_key, *, manifest_key, reason, authorize):
    binding = receipt_manifest_binding(db, context, manifest_key, authorize=authorize)
    return request_case(db, context, actor_id, operation_key, binding=binding, reason=reason,
        load_binding=lambda session: receipt_manifest_binding(session, context, manifest_key, authorize=authorize),
        authorize=authorize)


def review_receipt_manifest(db, context, actor_id, operation_key, *, manifest_key,
                            case_key, expected_version, outcome, reason, authorize):
    binding = receipt_manifest_binding(db, context, manifest_key, authorize=authorize)
    def independent(session):
        authorize(session)
        if binding.details['manifest_created_by'] == actor_id:
            raise PermissionError('Manifest creators cannot review their classification through another requestor')
    return review_case(db, context, actor_id, operation_key, case_key=case_key,
        binding=binding, expected_version=expected_version, outcome=outcome, reason=reason,
        load_binding=lambda session: receipt_manifest_binding(session, context, manifest_key, authorize=authorize),
        authorize=independent)
