"""Locked purchasing source for future physical receipt and valuation composition.

No public writer, commit, stock effect, price inference or consumption receipt.
Caller must keep this transaction and later bind the full source to an immutable
receipt manifest, source-use cap, authority and valuation approval. Never treat
this returned dictionary as standalone posting authority after releasing locks.
"""
from decimal import Decimal
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt, ReceiptItem
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Schema.InventoryReceiptSchema import InventoryReceiptSource
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.policy_activation_service import active_policy
from Services.inventory_unit_service import convert_quantity
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import apply_org_filter


def _owned(db, model, context):
    return apply_org_filter(db.query(model).enable_eagerloads(False).filter(
        model.org_id == context.org_id, model.is_deleted.is_(False)), model, context)


def prepare_inventory_receipt_source(db, context, payload, *, authorize):
    if not callable(authorize):
        raise ValueError('Receipt/source and inventory permission guard required')
    if not isinstance(payload, InventoryReceiptSource):
        raise ValueError('Typed inventory receipt source required')
    payload = InventoryReceiptSource.model_validate(payload.model_dump())
    if not db.in_transaction():
        raise ValueError('Receipt preparation requires a caller-owned transaction')
    authorize(db)
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Receipt company denied')
    source = _owned(db, GoodsReceipt, context).filter_by(id=payload.receipt_id).one_or_none()
    if source is None:
        raise LookupError('Receipt source not found')
    # Purchasing submission locks PO then receipt then PO lines. Preserve that
    # order and recheck the parent after locks; never trust an earlier ORM cache.
    po_id = source.po_id
    po = _owned(db, PurchaseOrder, context).filter_by(id=po_id, doc_type='PO').populate_existing().with_for_update(of=PurchaseOrder).one_or_none()
    receipt = _owned(db, GoodsReceipt, context).filter_by(id=payload.receipt_id, po_id=po_id).populate_existing().with_for_update(of=GoodsReceipt).one_or_none()
    if po is None or receipt is None:
        raise LookupError('Receipt purchase order not found')
    if receipt.posting_version != 1 or receipt.status not in {'SUBMITTED', 'VERIFIED'} or receipt.submitted_at is None:
        raise PostingConflict('Receipt must be submitted through the reviewed purchasing posting contract')
    # ReceiptItem has no org column: exact scoped parent binding is mandatory.
    line = db.query(ReceiptItem).filter_by(id=payload.receipt_item_id,
        receipt_id=receipt.id, is_deleted=False).populate_existing().with_for_update().one_or_none()
    if line is None:
        raise LookupError('Receipt line not found')
    item = _owned(db, POItem, context).filter_by(id=line.po_item_id, po_id=po.id,
        item_status='ACTIVE').populate_existing().with_for_update(of=POItem).one_or_none()
    if item is None or item.product_id is None or line.unit != item.unit:
        raise PostingConflict('Receipt line requires an exact active PO product and matching unit')
    branch = _owned(db, InventoryBranch, context).filter_by(id=payload.branch_id, is_active=True).with_for_update(read=True).one_or_none()
    location = _owned(db, StockLocation, context).filter_by(id=payload.location_id,
        branch_id=payload.branch_id, is_active=True).with_for_update(read=True).one_or_none()
    product = _owned(db, Product, context).filter_by(id=item.product_id,
        status='active', is_shared=False).populate_existing().with_for_update(of=Product).one_or_none()
    if branch is None or location is None or product is None:
        raise LookupError('Active receiving location or product not found')
    policy = active_policy(db, context, product.id)
    if policy is None or policy.version != payload.expected_policy_version:
        raise PostingConflict('Reviewed receipt unit policy missing or changed')
    config = InventoryPolicyConfig.model_validate(policy.config)
    if config.base_unit != product.unit:
        raise PostingConflict('Receipt product base unit differs from reviewed policy')
    quantities = {}
    for field in ('received_quantity', 'damaged_quantity', 'incorrect_quantity'):
        value = getattr(line, field)
        if not isinstance(value, Decimal):
            raise ValueError('Receipt quantities must be authoritative exact decimals')
        quantities[field] = convert_quantity(config, value, line.unit,
            allow_zero=field != 'received_quantity')
    if any(quantities[field] > quantities['received_quantity'] for field in ('damaged_quantity', 'incorrect_quantity')):
        raise PostingConflict('Receipt discrepancy exceeds received quantity')
    return dict(org_id=context.org_id, receipt_id=receipt.id, receipt_item_id=line.id,
        po_id=po.id, po_item_id=item.id, product_id=product.id,
        posting_version=receipt.posting_version, submitted_at=receipt.submitted_at.isoformat(),
        branch_id=branch.id, location_id=location.id, unit=line.unit,
        received_quantity=format(line.received_quantity, '.6f'), base_unit=config.base_unit,
        base_quantities={field: format(value, '.6f') for field, value in quantities.items()},
        policy_version=policy.version, policy=config.model_dump(mode='json'),
        requires_condition_review=(not line.condition_ok or any(quantities[field] for field in ('damaged_quantity', 'incorrect_quantity'))),
        physical_posting_enabled=False)
