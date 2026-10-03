from decimal import Decimal
from Model.containermgmt.Inventory.UnitBarcode import UnitBarcode, UnitBarcodeRetirement
from Model.containermgmt.Orders.Product import Product
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Schema.UnitBarcodeSchema import UnitBarcodeCreate
from Services.policy_activation_service import active_policy
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Utils.org_filter import apply_org_filter
from Services.policy_compatibility_service import extends_policy


class BarcodeSourceUnavailable(LookupError):
    pass


def barcode_query(db, context):
    return apply_org_filter(db.query(UnitBarcode).filter(UnitBarcode.org_id == context.org_id,
        UnitBarcode.is_deleted.is_(False)), UnitBarcode, context)


def barcode_product(db, context, product_id, *, lock=False):
    query = apply_org_filter(db.query(Product.id, Product.unit, Product.status).filter(
        Product.id == product_id, Product.org_id == context.org_id,
        Product.is_shared.is_(False), Product.is_deleted.is_(False)), Product, context)
    product = (query.with_for_update(of=Product) if lock else query).one_or_none()
    if product is None:
        raise BarcodeSourceUnavailable("Product not found")
    return product


def barcode_result(row, policy, product):
    return {"id": row.id, "product_id": row.product_id, "policy_version": row.policy_version,
        "barcode": row.barcode, "unit": row.unit, "base_unit": policy.config["base_unit"],
        "base_quantity": format(row.factor, ".8f"), "eligible": product.status == "active" and
        policy.version == row.policy_version and product.unit == policy.config["base_unit"]}


def barcode_eligible(row, original, active, product):
    if not active or not original or product.status != "active" or product.unit != active.config.get("base_unit"):
        return False
    if not extends_policy(original.config, active.config):
        return False
    config = InventoryPolicyConfig.model_validate(active.config)
    units = {config.base_unit: Decimal(1), **{item.unit: item.factor for item in config.conversions}}
    return units.get(row.unit) == row.factor


def register_barcode(factory, context, actor_id, *, product_id, payload: UnitBarcodeCreate, authorize):
    def guard(db):
        authorize(db)
        product = barcode_product(db, context, product_id, lock=True)
        policy = active_policy(db, context, product_id)
        if product.status != "active" or policy is None or policy.config["base_unit"] != product.unit:
            raise PostingConflict("An active product with a reviewed active policy is required")
        if policy.version != payload.expected_policy_version:
            raise PostingConflict("Active policy changed; reload before registering a barcode")
        retired = barcode_query(db, context).join(UnitBarcodeRetirement,
            (UnitBarcodeRetirement.barcode_id == UnitBarcode.id) &
            (UnitBarcodeRetirement.org_id == UnitBarcode.org_id)).filter(UnitBarcode.barcode == payload.barcode).first()
        if retired:
            raise PostingConflict("Barcode is retired; its identity cannot be reused")
    def apply(db):
        policy = active_policy(db, context, product_id)
        config = InventoryPolicyConfig.model_validate(policy.config)
        units = [(config.base_unit, Decimal(1))] + [(item.unit, item.factor) for item in config.conversions]
        match = next(((unit, factor) for unit, factor in units if unit.casefold() == payload.unit.casefold()), None)
        if match is None:
            raise ValueError("Barcode unit must belong to the reviewed active policy")
        if barcode_query(db, context).filter_by(barcode=payload.barcode).first():
            raise PostingConflict("Barcode is already registered; identifiers cannot be reassigned")
        row = UnitBarcode(org_id=context.org_id, product_id=product_id, policy_version=policy.version,
            barcode=payload.barcode, unit=match[0], factor=match[1], operation_key=payload.operation_key, created_by=actor_id)
        db.add(row); db.flush()
        result = barcode_result(row, policy, barcode_product(db, context, product_id))
        return PostingEffect(result, {"kind": "inventory.barcode.registered", "barcode_id": row.id,
            "product_id": product_id, "policy_version": policy.version})
    request = payload.model_dump(mode="json", exclude={"operation_key"})
    return execute_once(factory, context, actor_id, payload.operation_key, "inventory.barcode.register.v1",
                        {"product_id": product_id, **request}, apply, authorize=guard)
