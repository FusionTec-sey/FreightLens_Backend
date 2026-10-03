"""Reviewed activation/revision without history; stock conversion remains separate."""
from dataclasses import replace
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Model.containermgmt.Orders.Product import Product
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.manager_case_service import consume_case
from Services.policy_case_binding_service import load_policy_case_binding
from Services.policy_transition_service import revision_blockers
from Utils.org_filter import apply_org_filter


def active_policy(db, context, product_id):
    return apply_org_filter(db.query(ProductPolicyActivation).filter(
        ProductPolicyActivation.org_id == context.org_id, ProductPolicyActivation.product_id == product_id,
        ProductPolicyActivation.is_deleted.is_(False)), ProductPolicyActivation, context
        ).order_by(ProductPolicyActivation.version.desc()).first()


def require_catalogue_update_compatible(db, context, product, payload):
    """Product must be locked by the caller before checking and changing it."""
    active = apply_org_filter(db.query(ProductPolicyActivation.id).filter(
        ProductPolicyActivation.org_id == product.org_id, ProductPolicyActivation.product_id == product.id,
        ProductPolicyActivation.is_deleted.is_(False)), ProductPolicyActivation, context).first()
    if active and any(getattr(payload, field, None) is not None and
                      getattr(payload, field) != getattr(product, field) for field in ("unit", "current_stock")):
        raise PostingConflict("Activated inventory requires reviewed transitions and Inventory stock posting")


def activate_initial_policy(factory, context, actor_id, operation_key, *, case_key, binding, authorize,
                            expected_active_version=0):
    if binding.action != "inventory.policy.activate" or binding.source_type != "product.policy":
        raise ValueError("An inventory policy activation case is required")
    product_id = int(binding.source_key)
    if type(expected_active_version) is not int or expected_active_version < 0:
        raise ValueError("An exact nonnegative active version is required")
    if binding.details.get("expected_active_version", 0) != expected_active_version:
        raise PostingConflict("Approval does not match the expected active policy version")
    def load(db):
        current = load_policy_case_binding(db, context, product_id)
        active = active_policy(db, context, product_id)
        if active and active.operation_key == operation_key and active.version == expected_active_version + 1:
            # Only this exact operation's latest effect may normalize its predecessor
            # for replay. Newer activations, changed drafts and foreign writers fail.
            details = dict(current.details)
            if expected_active_version:
                details["expected_active_version"] = expected_active_version
            else:
                details.pop("expected_active_version", None)
            if binding.details.get("transition") == "EXTEND_UNITS":
                details["transition"] = "EXTEND_UNITS"
            current = replace(current, details=details)
        return current
    def guard(db):
        authorize(db)
        if binding.org_id != context.org_id:
            raise PermissionError("Policy scope denied")
        if load(db).snapshot() != binding.snapshot():
            raise PostingConflict("Reviewed policy changed; request a new review")
    def apply(db):
        previous = active_policy(db, context, product_id)
        if (previous.version if previous else 0) != expected_active_version:
            raise PostingConflict("Active policy changed; a new reviewed transition is required")
        # Source loader holds the product lock also used by all new stock openings.
        blockers = revision_blockers(db, context, product_id, previous, binding.details["config"])
        if blockers:
            raise PostingConflict("; ".join(blockers))
        config = InventoryPolicyConfig.model_validate(binding.details["config"]).model_dump(mode="json")
        if previous and InventoryPolicyConfig.model_validate(previous.config) == InventoryPolicyConfig.model_validate(config):
            raise PostingConflict("Saved policy is already active; no transition is needed")
        consume_case(db, context, actor_id, operation_key, case_key=case_key, binding=binding,
                     load_binding=load, authorize=authorize)
        version = expected_active_version + 1
        db.add(ProductPolicyActivation(org_id=context.org_id, product_id=product_id, version=version,
            draft_version=binding.source_version, case_key=case_key, operation_key=operation_key,
            config=config, created_by=actor_id))
        db.flush()
        return PostingEffect({"product_id": product_id, "version": version, "draft_version": binding.source_version,
            "status": "ACTIVE", "config": config}, {"kind": "inventory.policy.activated", "product_id": product_id,
            "version": version, "case_key": str(case_key)})
    kind = "inventory.policy.extend-units.v1" if binding.details.get("transition") == "EXTEND_UNITS" else (
        "inventory.policy.revise-empty.v1" if expected_active_version else "inventory.policy.activate.v1")
    return execute_once(factory, context, actor_id, operation_key, kind,
        {"case_key": str(case_key), "expected_active_version": expected_active_version, "binding": binding.snapshot()}, apply, authorize=guard)
