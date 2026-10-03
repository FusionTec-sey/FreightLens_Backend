"""Authoritative inventory policy adapter for the shared manager-case engine."""
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Services.manager_case_service import CaseBinding
from Utils.org_filter import apply_org_filter
from Services.policy_compatibility_service import extends_policy
from Schema.InventoryPolicySchema import InventoryPolicyConfig


class PolicySourceUnavailable(LookupError):
    """No visible, eligible policy source; do not reveal foreign identities."""


def load_policy_case_binding(db, context, product_id, *, lock=True):
    # Same product lock used by draft saves; draft cannot change before commit.
    query = apply_org_filter(db.query(Product.id, Product.name, Product.unit).filter(
        Product.id == product_id, Product.org_id == context.org_id, Product.is_deleted.is_(False),
        Product.is_shared.is_(False), Product.status == "active"), Product, context)
    product = (query.with_for_update(of=Product) if lock else query).one_or_none()
    if product is None:
        raise PolicySourceUnavailable("Policy source not found")
    draft = apply_org_filter(db.query(ProductPolicyDraft).filter(
        ProductPolicyDraft.org_id == context.org_id, ProductPolicyDraft.product_id == product_id,
        ProductPolicyDraft.is_deleted.is_(False)), ProductPolicyDraft, context).order_by(ProductPolicyDraft.version.desc()).first()
    if draft is None or draft.config.get("base_unit") != product.unit:
        raise ValueError("Save a valid draft matching the current catalogue unit before requesting review")
    active = apply_org_filter(db.query(ProductPolicyActivation.version, ProductPolicyActivation.config).filter(
        ProductPolicyActivation.org_id == context.org_id, ProductPolicyActivation.product_id == product_id,
        ProductPolicyActivation.is_deleted.is_(False)), ProductPolicyActivation, context
        ).order_by(ProductPolicyActivation.version.desc()).first()
    details = {"product_id": product.id, "product_name": product.name, "base_unit": product.unit, "config": draft.config}
    # Keep existing initial-activation bindings compatible; revisions pin their predecessor.
    if active:
        details["expected_active_version"] = active.version
        if extends_policy(active.config, draft.config) and InventoryPolicyConfig.model_validate(active.config) != InventoryPolicyConfig.model_validate(draft.config):
            details["transition"] = "EXTEND_UNITS"
    return CaseBinding(context.org_id, "inventory.policy.activate", "product.policy", str(product.id), draft.version, details)
