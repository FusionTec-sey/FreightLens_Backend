"""Append source-bound receipt movements inside a future atomic coordinator.

No commit, operation receipt, valuation or public adapter is created here.
"""
from decimal import Decimal
from Model.containermgmt.Inventory.ReceiptManifest import InventoryReceiptManifestRecord
from Model.containermgmt.Inventory.ReceiptSourceUse import InventoryReceiptSourceUse
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Orders.Product import Product
from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Schema.InventorySerialSchema import SerialOpening
from Services.inventory_quantity_service import QuantityBreakdown, ZERO
from Services.inventory_receipt_source_use_service import check_receipt_source
from Services.policy_activation_service import active_policy
from Services.policy_compatibility_service import extends_policy
from Services.posting_authority_service import AuthorityClaim, require_posting_authority
from Services.serial_stock_service import record_serial_opening, verify_serial_projection
from Services.stock_ledger_service import _record
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import apply_org_filter


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(model.org_id == context.org_id,
        model.is_deleted.is_(False)), model, context)


def check_receipt_stock(db, context, *, manifest_key, authority, authorize):
    if not callable(authorize):
        raise ValueError('Receipt movement permission guard required')
    authorize(db)
    if not isinstance(authority, AuthorityClaim) or authority.org_id != context.org_id:
        raise PermissionError('Trusted receiving-store authority required')
    # The immutable proposal gives us the branch needed to fence the writer
    # without first locking the purchasing source. The full source binding is
    # reloaded below after the authority lock and remains authoritative.
    record = _owned(db, InventoryReceiptManifestRecord, context).filter_by(
        manifest_key=manifest_key).one_or_none()
    if record is None:
        raise LookupError('Receipt manifest not found')
    try:
        branch_id = record.snapshot['source']['branch_id']
    except (KeyError, TypeError):
        raise PostingConflict('Receipt manifest has an invalid source scope') from None
    if type(branch_id) is not int or branch_id <= 0:
        raise PostingConflict('Receipt manifest has an invalid source scope')
    require_posting_authority(db, context, authority, branch_id=branch_id)
    binding = check_receipt_source(db, context, manifest_key=manifest_key, authorize=authorize)
    source = binding.details['snapshot']['source']
    if source['branch_id'] != branch_id:
        raise PostingConflict('Receipt source branch changed before movement')
    return binding


def _batch(db, context, actor_id, product_id, identity):
    row = _owned(db, StockBatch, context).filter_by(batch_key=identity.batch_key,
        product_id=product_id).one_or_none()
    if row is not None:
        if any(getattr(row, field) != getattr(identity, field) for field in ('code', 'shade', 'calibre', 'expires_on')):
            raise PostingConflict('Receipt batch identity differs from its recorded lot')
        return row
    if _owned(db, StockBatch, context).filter_by(product_id=product_id, code=identity.code).first():
        raise PostingConflict('Receipt batch code belongs to another identity')
    row = StockBatch(org_id=context.org_id, product_id=product_id, created_by=actor_id,
        **identity.model_dump())
    db.add(row); db.flush()
    return row


def _bucket(db, context, actor_id, operation_key, source, policy, tracking, quantities,
            reason, *, batch=None, serials=None):
    batch_key = batch.batch_key if batch else None
    balance = _owned(db, StockBalance, context).filter_by(location_id=source['location_id'],
        product_id=source['product_id'], batch_key=batch_key).populate_existing().with_for_update().one_or_none()
    before = QuantityBreakdown(ZERO)
    if balance is None:
        balance = StockBalance(org_id=context.org_id, branch_id=source['branch_id'],
            location_id=source['location_id'], product_id=source['product_id'],
            base_unit=source['base_unit'], tracking_policy=tracking, batch_key=batch_key,
            policy_config=policy.model_dump(mode='json'), quantity_step=Decimal(policy.quantity_step),
            on_hand=quantities.on_hand, reserved=ZERO, damaged=quantities.damaged,
            quarantined=quantities.quarantined, version=1, created_by=actor_id)
        db.add(balance); db.flush()
    else:
        if (balance.branch_id != source['branch_id'] or balance.base_unit != source['base_unit']
                or balance.tracking_policy != tracking or not extends_policy(balance.policy_config, policy.model_dump(mode='json'))):
            raise PostingConflict('Existing receiving bucket has incompatible identity or policy')
        before = QuantityBreakdown(balance.on_hand, balance.reserved, balance.damaged, balance.quarantined)
        balance.on_hand += quantities.on_hand
        balance.damaged += quantities.damaged
        balance.quarantined += quantities.quarantined
        balance.version += 1
        balance.updated_by = actor_id
    if serials:
        record_serial_opening(db, context, balance, serials, actor_id)
        verify_serial_projection(db, context, balance)
    return _record(db, balance, operation_key, actor_id, 'RECEIPT', reason, before)


def append_receipt_stock(db, context, actor_id, operation_key, *, manifest_key, authority, authorize):
    if not db.in_transaction() or not callable(authorize):
        raise ValueError('Receipt movement requires an active outer transaction and permission guard')
    binding = check_receipt_stock(db, context, manifest_key=manifest_key,
        authority=authority, authorize=authorize)
    snapshot = binding.details['snapshot']; source = snapshot['source']; manifest = snapshot['manifest']
    use = _owned(db, InventoryReceiptSourceUse, context).filter_by(operation_key=operation_key,
        manifest_key=manifest_key, created_by=actor_id).one_or_none()
    if use is None:
        raise PermissionError('Receipt movement requires source consumption in this operation')
    record = _owned(db, InventoryReceiptManifestRecord, context).filter_by(manifest_key=manifest_key).one()
    if record.snapshot != snapshot:
        raise PostingConflict('Receipt manifest changed before movement')
    policy = InventoryPolicyConfig.model_validate(source['policy'])
    current = active_policy(db, context, source['product_id'])
    if current is None or current.version != source['policy_version'] or current.config != policy.model_dump(mode='json'):
        raise PostingConflict('Reviewed receipt policy changed before movement')
    _owned(db, Product, context).filter_by(id=source['product_id'], status='active', is_shared=False
        ).with_for_update(of=Product).one()
    _owned(db, StockLocation, context).filter_by(id=source['location_id'], branch_id=source['branch_id'],
        is_active=True).with_for_update().one()
    reason = manifest['reason']
    effects = []
    if policy.tracking == 'BATCH':
        for item in sorted(manifest['batches'], key=lambda row: row['identity']['batch_key']):
            identity = StockBatchIdentity.model_validate(item['identity'])
            _batch(db, context, actor_id, source['product_id'], identity)
            quantities = QuantityBreakdown(Decimal(item['on_hand']), damaged=Decimal(item['damaged']),
                quarantined=Decimal(item['quarantined']))
            effects.append(_bucket(db, context, actor_id, operation_key, source, policy, 'BATCH',
                quantities, reason, batch=identity))
    elif policy.tracking == 'SERIAL':
        serials = SerialOpening.model_validate(manifest['serials'])
        quantities = QuantityBreakdown(Decimal(manifest['on_hand']), damaged=Decimal(manifest['damaged']),
            quarantined=Decimal(manifest['quarantined']))
        effects.append(_bucket(db, context, actor_id, operation_key, source, policy, 'SERIAL',
            quantities, reason, serials=serials))
    else:
        quantities = QuantityBreakdown(Decimal(manifest['on_hand']), damaged=Decimal(manifest['damaged']),
            quarantined=Decimal(manifest['quarantined']))
        effects.append(_bucket(db, context, actor_id, operation_key, source, policy, 'UNTRACKED',
            quantities, reason))
    db.flush()
    return [effect.result for effect in effects]
