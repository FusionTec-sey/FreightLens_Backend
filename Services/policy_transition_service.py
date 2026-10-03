"""Shared no-history eligibility. Reads are advisory; posting holds product lock."""
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch
from Model.containermgmt.Inventory.StockSerial import StockSerialIdentity
from Model.containermgmt.Inventory.UnitBarcode import UnitBarcode, UnitBarcodeRetirement
from Model.containermgmt.Orders.Product import Product
from Utils.org_filter import apply_org_filter
from Services.policy_compatibility_service import extends_policy


def live_barcode_query(db, context, product_id):
    """One scoped retirement predicate for readiness and locked activation."""
    retired = apply_org_filter(db.query(UnitBarcodeRetirement.id).filter(
        UnitBarcodeRetirement.org_id == context.org_id,
        UnitBarcodeRetirement.barcode_id == UnitBarcode.id,
        UnitBarcodeRetirement.is_deleted.is_(False)), UnitBarcodeRetirement, context
        ).correlate(UnitBarcode).exists()
    return apply_org_filter(db.query(UnitBarcode.id).filter(
        UnitBarcode.org_id == context.org_id, UnitBarcode.product_id == product_id,
        UnitBarcode.is_deleted.is_(False), ~retired), UnitBarcode, context)


def no_history_blockers(db, context, product_id):
    legacy = apply_org_filter(db.query(Product.current_stock).filter(
        Product.id == product_id, Product.org_id == context.org_id,
        Product.is_deleted.is_(False)), Product, context).scalar()
    blockers = []
    if legacy is None or legacy != 0:
        blockers.append("Legacy stock requires opening reconciliation before policy activation")
    # Indexed existence probes, not an unbounded load of balances or identities.
    for model, message in (
        (StockBalance, "Existing stock history requires a reviewed stock conversion"),
        (StockBatch, "Batch history requires a reviewed stock conversion"),
        (StockSerialIdentity, "Serial history requires a reviewed stock conversion"),
    ):
        query = apply_org_filter(db.query(model).filter(model.org_id == context.org_id,
            model.product_id == product_id, model.is_deleted.is_(False)), model, context)
        if db.query(query.exists()).scalar():
            blockers.append(message)
    # Retirement never removes identity history, but a permanently disabled code
    # cannot resolve under a new policy. Every still-live code remains a blocker.
    live_codes = live_barcode_query(db, context, product_id)
    if db.query(live_codes.exists()).scalar():
        blockers.append("Registered barcodes require reviewed retirement or rebinding")
    return blockers


def revision_blockers(db, context, product_id, previous, proposed):
    """Product lock is required for posting; the readiness caller is advisory.

    Compatible extensions change no balance rule. Stream distinct historical
    snapshots, never load quantities, reservations or whole stock rows.
    """
    blockers = no_history_blockers(db, context, product_id)
    if not previous or not extends_policy(previous.config, proposed):
        return blockers
    # Legacy stock is not authoritative ledger stock and may not be reinterpreted.
    if any(reason.startswith("Legacy stock") for reason in blockers):
        return blockers
    snapshots = apply_org_filter(db.query(StockBalance.policy_config).filter(
        StockBalance.org_id == context.org_id, StockBalance.product_id == product_id,
        StockBalance.is_deleted.is_(False)), StockBalance, context).distinct().yield_per(100)
    for (snapshot,) in snapshots:
        if not extends_policy(snapshot, proposed):
            return ["Existing stock rules are missing or incompatible; reviewed stock conversion is required"]
    # Every live code also retains its original policy snapshot. Normally each is
    # an ancestor, but do not assume this for imported or inconsistent history.
    from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
    policies = live_barcode_query(db, context, product_id).outerjoin(ProductPolicyActivation,
        (UnitBarcode.org_id == ProductPolicyActivation.org_id) &
        (UnitBarcode.product_id == ProductPolicyActivation.product_id) &
        (UnitBarcode.policy_version == ProductPolicyActivation.version) &
        ProductPolicyActivation.is_deleted.is_(False)
        ).with_entities(ProductPolicyActivation.config).distinct().yield_per(100)
    for (snapshot,) in policies:
        if not extends_policy(snapshot, proposed):
            return ["Live barcode rules are missing or incompatible; reviewed retirement is required"]
    return []
