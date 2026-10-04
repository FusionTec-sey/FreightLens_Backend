"""Source ownership/quantity gates shared by holds and draft revisions."""
from decimal import Decimal, localcontext, Context
from sqlalchemy import func
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision, SalesIntentLineRevision
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockReservation
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.inventory_posting_service import PostingConflict
from Services.inventory_unit_service import convert_quantity
from Utils.org_filter import apply_org_filter


def owned(db, model, context):
    return apply_org_filter(db.query(model).filter_by(org_id=context.org_id, is_deleted=False), model, context)


def load_reservation_demand(db, context, source):
    """One locked, version-checked saved-demand boundary for planners and writers."""
    if not isinstance(source, SalesDemandReference): raise ValueError('Typed saved sales demand required')
    if not db.in_transaction(): raise ValueError('Caller transaction required')
    parent = owned(db, SalesIntent, context).filter_by(document_key=source.document_key).with_for_update().one_or_none()
    if parent is None: raise LookupError('Sales demand not found')
    revision = owned(db, SalesIntentRevision, context).filter_by(document_key=source.document_key).order_by(SalesIntentRevision.version.desc()).first()
    if revision is None or revision.version != source.version: raise PostingConflict('Saved sales demand changed')
    line = owned(db, SalesIntentLineRevision, context).filter_by(document_key=source.document_key,
        version=source.version, line_key=source.line_key).one_or_none()
    if line is None: raise LookupError('Sales demand line not found')
    return revision, line


def validate_reservation_source(db, context, source, balance_id, quantity, input_unit):
    revision, line = load_reservation_demand(db, context, source)
    balance = owned(db, StockBalance, context).filter_by(id=balance_id).one_or_none()
    if balance is None or balance.product_id != line.product_id or balance.base_unit != line.base_unit:
        raise PostingConflict('Stock does not match saved demand')
    if balance.branch_id != revision.branch_id:
        raise PostingConflict('Another store requires an explicit fulfilment approval')
    base_quantity = convert_quantity(InventoryPolicyConfig.model_validate(line.policy), quantity, input_unit or balance.base_unit)
    if base_quantity > line.base_quantity: raise PostingConflict('Hold exceeds saved line quantity')
    return line


def active_demand_holds(db, context, document_key):
    return dict(owned(db, SalesReservationSource, context).join(StockReservation,
        (StockReservation.reservation_key == SalesReservationSource.reservation_key) &
        (StockReservation.org_id == SalesReservationSource.org_id)).filter(
            SalesReservationSource.document_key == document_key,
            StockReservation.is_deleted.is_(False), StockReservation.quantity > StockReservation.released
        ).with_entities(SalesReservationSource.line_key, func.sum(StockReservation.quantity - StockReservation.released))
        .group_by(SalesReservationSource.line_key).all())


def protect_held_draft(db, context, document_key, previous, payload):
    """Caller holds the document lock shared with source-linked reservation writes."""
    rows = active_demand_holds(db, context, document_key)
    if not rows: return
    if previous.customer_key != payload.customer_key or previous.branch_id != payload.branch_id:
        raise PostingConflict('Held demand cannot change customer or selling store without reviewed release')
    current_lines = {line.line_key: line for line in owned(db, SalesIntentLineRevision, context).filter_by(
        document_key=document_key, version=previous.version).all()}
    proposed = {line.line_key: line for line in payload.lines}
    for key, remaining in rows.items():
        old, new = current_lines.get(key), proposed.get(key)
        if old is None or new is None or new.product_id != old.product_id or new.expected_policy_version != old.policy_version:
            raise PostingConflict('Held line cannot be removed or reclassified without reviewed release')
        base = convert_quantity(InventoryPolicyConfig.model_validate(old.policy), Decimal(new.quantity), new.unit)
        with localcontext(Context(prec=48)):
            if base < remaining:
                raise PostingConflict('Draft quantity cannot fall below its active hold')
