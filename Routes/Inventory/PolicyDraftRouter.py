"""Unit/tracking preparation without product-master or ledger mutation."""
from fastapi import APIRouter, Depends, HTTPException
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Schema.InventoryPolicySchema import InventoryPolicySave, InventoryPolicyRead, InventoryUnitPreview, InventoryUnitPreviewRead
from Services.inventory_unit_service import convert_quantity
from Services.policy_activation_service import active_policy
from Schema.PolicyActivationSchema import PolicyActivationRead, PolicyTransitionRead
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.policy_transition_service import no_history_blockers, revision_blockers
from Services.policy_compatibility_service import extends_policy
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission

PolicyDraftRouter = APIRouter(prefix="/inventory/products", tags=["Inventory Policy Drafts"])


@PolicyDraftRouter.get("/{product_id}/inventory-policy/transition-readiness", response_model=PolicyTransitionRead)
def transition_readiness(product_id: int, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                         user=Depends(require_permission("View_Product"))):
    product = scoped_product(db, context, product_id)
    if product.org_id != context.org_id:
        raise HTTPException(404, "Product not found")
    draft = latest(db, product)
    active = active_policy(db, context, product_id)
    blockers = revision_blockers(db, context, product_id, active, draft.config) if draft else no_history_blockers(db, context, product_id)
    if product.status != "active":
        blockers.append("Activate the product before requesting a policy review")
    changed = []
    if not draft:
        blockers.append("Save an explicit unit and tracking draft first")
    else:
        config = InventoryPolicyConfig.model_validate(draft.config).model_dump()
        if config["base_unit"] != product.unit:
            blockers.append("Saved draft no longer matches the catalogue base unit")
        before = InventoryPolicyConfig.model_validate(active.config).model_dump() if active else {}
        changed = [field for field, value in config.items() if before.get(field) != value]
    route = "BLOCKED" if blockers else "NO_CHANGE" if active and not changed else (
        "COMPATIBLE_REVISION_REVIEW" if active and extends_policy(active.config, draft.config) else
        "EMPTY_REVISION_REVIEW" if active else "INITIAL_REVIEW")
    return PolicyTransitionRead(product_id=product_id, draft_version=draft.version if draft else 0,
        active_version=active.version if active else 0, changed_fields=changed, blockers=blockers, route=route,
        active_config=active.config if active else None, proposed_config=draft.config if draft else None)


@PolicyDraftRouter.get("/{product_id}/inventory-policy", response_model=PolicyActivationRead)
def read_active_policy(product_id: int, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                       user=Depends(require_permission("View_Product"))):
    product = scoped_product(db, context, product_id)
    if product.org_id != context.org_id:
        raise HTTPException(404, "Product not found")
    row = active_policy(db, context, product_id)
    return PolicyActivationRead(product_id=product_id, version=row.version if row else 0,
        draft_version=row.draft_version if row else None, status="ACTIVE" if row else "NOT_ACTIVE",
        config=row.config if row else None)


def scoped_product(db, context, product_id, lock=False):
    query = apply_org_filter(db.query(Product.id, Product.org_id, Product.unit, Product.status).filter(
        Product.id == product_id, Product.is_deleted.is_(False), Product.is_shared.is_(False)), Product, context)
    if lock:
        query = query.with_for_update(of=Product)
    product = query.one_or_none()
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


def latest(db, product):
    return db.query(ProductPolicyDraft).filter(ProductPolicyDraft.product_id == product.id,
        ProductPolicyDraft.org_id == product.org_id, ProductPolicyDraft.is_deleted.is_(False)
        ).order_by(ProductPolicyDraft.version.desc()).first()


def read_result(product, draft):
    return InventoryPolicyRead(product_id=product.id, current_base_unit=product.unit,
        version=draft.version if draft else 0, status="DRAFT" if draft else "NOT_CONFIGURED",
        config=draft.config if draft else None)


@PolicyDraftRouter.get("/{product_id}/inventory-policy-draft", response_model=InventoryPolicyRead)
def read_policy(product_id: int, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                user=Depends(require_permission("View_Product"))):
    product = scoped_product(db, context, product_id)
    return read_result(product, latest(db, product))


@PolicyDraftRouter.post("/{product_id}/inventory-policy-draft/preview-unit", response_model=InventoryUnitPreviewRead)
def preview_unit(product_id: int, payload: InventoryUnitPreview, db: Session = Depends(get_db),
                 context: OrgContext = Depends(get_org_context), user=Depends(require_permission("View_Product"))):
    """Read-only calculation; does not save, activate, reserve or authorise a sale."""
    product = scoped_product(db, context, product_id)
    if payload.config.base_unit != product.unit:
        raise HTTPException(409, "Base unit changed or does not match the catalogue; reload before testing")
    try:
        quantity = convert_quantity(payload.config, Decimal(payload.quantity), payload.unit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return InventoryUnitPreviewRead(base_unit=payload.config.base_unit, base_quantity=format(quantity, ".6f"),
                                    quantity_step=payload.config.quantity_step)


@PolicyDraftRouter.put("/{product_id}/inventory-policy-draft", response_model=InventoryPolicyRead)
def save_policy(product_id: int, payload: InventoryPolicySave, db: Session = Depends(get_db),
                context: OrgContext = Depends(get_org_context), user=Depends(require_permission("Edit_Product"))):
    try:
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        product = scoped_product(db, context, product_id, lock=True)
        if payload.config.base_unit != product.unit:
            raise HTTPException(409, "Base unit changed or does not match the catalogue; reload before saving")
        previous = latest(db, product)
        version = previous.version if previous else 0
        config = payload.config.model_dump(mode="json")
        # Lost-response replay is safe only for the same actor, revision and content.
        if previous and previous.version == payload.expected_version + 1 and previous.config == config and previous.created_by == user.id:
            result = read_result(product, previous)
        else:
            if version != payload.expected_version:
                raise HTTPException(409, "Draft changed since you opened it; reload and review before saving")
            draft = ProductPolicyDraft(org_id=product.org_id, product_id=product.id,
                version=version + 1, config=config, created_by=user.id)
            db.add(draft); db.flush()
            result = read_result(product, draft)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
