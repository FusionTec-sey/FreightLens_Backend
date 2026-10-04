"""Prepare a conserved full-line physical manifest. No approval or stock effect."""
from decimal import Context, Decimal, localcontext
from Schema.InventoryReceiptSchema import InventoryReceiptManifest
from Services.inventory_receipt_source_service import prepare_inventory_receipt_source
from Services.inventory_quantity_service import QuantityBreakdown
from Services.stock_reclassification_service import BatchAllocation, validate_stock_manifest


def prepare_inventory_receipt_manifest(db, context, payload, *, authorize):
    if not isinstance(payload, InventoryReceiptManifest):
        raise ValueError('Typed physical receipt manifest required')
    payload = InventoryReceiptManifest.model_validate(payload.model_dump())
    source = prepare_inventory_receipt_source(db, context, payload.source, authorize=authorize)
    quantities = QuantityBreakdown(Decimal(payload.on_hand),
        damaged=Decimal(payload.damaged), quarantined=Decimal(payload.quarantined))
    if quantities.on_hand != Decimal(source['base_quantities']['received_quantity']):
        raise ValueError('Full receipt line manifest must conserve received quantity exactly')
    validate_stock_manifest(source['policy'], quantities,
        batches=tuple(BatchAllocation(row.identity, row.quantities()) for row in payload.batches),
        serials=payload.serials)
    # Damaged and incorrect purchasing observations can overlap. Never subtract
    # both to invent available stock. Exact disposition needs independent review.
    observed = max(Decimal(source['base_quantities'][field]) for field in
                   ('damaged_quantity', 'incorrect_quantity'))
    with localcontext(Context(prec=48)):
        if quantities.damaged + quantities.quarantined < observed:
            raise ValueError('Reported damaged/incorrect goods cannot become available in the receipt manifest')
    return dict(source=source, manifest=payload.model_dump(mode='json'),
        quantities={field: format(getattr(quantities, field), '.6f') for field in
                    ('on_hand', 'damaged', 'quarantined', 'available')},
        condition_review_required=source['requires_condition_review'],
        physical_posting_enabled=False)
