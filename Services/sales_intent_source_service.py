"""Prepare locked authoritative references for the forthcoming draft writer.

Caller owns the transaction. No commit, external I/O, stock or financial effect.
The returned snapshot alone is never evidence of sales/collection eligibility.
"""
from decimal import Decimal
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Orders.Product import Product
from Schema.SalesIntentSchema import SalesIntentInput
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.customer_identity_service import get_customer
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Services.inventory_unit_service import convert_quantity
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import apply_org_filter


def prepare_sales_intent(db, context, payload, *, authorize):
    if not callable(authorize):
        raise ValueError('Sales-draft and source-data permission guard required')
    if not isinstance(payload, SalesIntentInput):
        raise ValueError('Typed sales draft required')
    if not db.in_transaction():
        raise ValueError('Sales draft preparation requires a caller-owned transaction')
    authorize(db)
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Sales draft company denied')
    payload = SalesIntentInput.model_validate(payload.model_dump())
    branch = apply_org_filter(db.query(InventoryBranch).filter_by(
        id=payload.branch_id, org_id=context.org_id, is_deleted=False, is_active=True,
        kind='STORE'), InventoryBranch, context).with_for_update(read=True).populate_existing().one_or_none()
    if branch is None:
        raise LookupError('Selling branch not found')
    customer = get_customer(db, context, payload.customer_key, authorize=authorize)
    if customer.version != payload.expected_customer_version:
        raise PostingConflict('Customer profile changed')
    ids = sorted({line.product_id for line in payload.lines})
    products = apply_org_filter(db.query(Product).enable_eagerloads(False).filter(
        Product.org_id == context.org_id, Product.id.in_(ids), Product.is_deleted.is_(False),
        Product.status == 'active'), Product, context).order_by(Product.id).with_for_update(read=True, of=Product).populate_existing().all()
    if len(products) != len(ids):
        raise LookupError('Draft product not found')
    # Products remain locked until the caller commits; activation uses the same
    # product lock. One bounded latest-policy query avoids a query per cart line.
    rows = apply_org_filter(db.query(ProductPolicyActivation).filter(
        ProductPolicyActivation.org_id == context.org_id,
        ProductPolicyActivation.product_id.in_(ids),
        ProductPolicyActivation.is_deleted.is_(False)), ProductPolicyActivation, context
    ).distinct(ProductPolicyActivation.product_id).order_by(
        ProductPolicyActivation.product_id, ProductPolicyActivation.version.desc()).all()
    policies = {row.product_id: row for row in rows}
    lines = []
    for line in payload.lines:
        policy = policies.get(line.product_id)
        if policy is None or policy.version != line.expected_policy_version:
            raise PostingConflict('Reviewed inventory policy missing or changed')
        config = InventoryPolicyConfig.model_validate(policy.config)
        quantity = convert_quantity(config, Decimal(line.quantity), line.unit)
        lines.append(dict(line.model_dump(mode='json'), base_quantity=format(quantity, 'f'),
            base_unit=config.base_unit, policy=config.model_dump(mode='json')))
    return dict(customer_key=str(customer.customer_key), customer_version=customer.version,
                branch_id=branch.id, lines=lines, status='DRAFT')
