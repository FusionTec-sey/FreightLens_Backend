"""The group product dictionary: publish a definition, adopt one as your own.

The dictionary holds what is true for every company. Adopting copies it into a
product of the adopting company's own, which then carries that company's code,
cost, stock and supplier, plus a link back to the entry it came from.

Copying rather than sharing is deliberate. A product row mixes universal facts
with company facts, so sharing it would mean splitting the row; and a vendor
master built on copies without a link is what produced the duplicates merged out
earlier. The link is what makes a copy attributable.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from Model.db import get_db
from Model.containermgmt.Orders.Product import Product, ProductCategory
from Model.containermgmt.MasterData.ProductDefinition import ProductDefinition
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import has_permission
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.product_dictionary")

ProductDictionaryRouter = APIRouter(prefix="/inventory/dictionary", tags=["Group Product Dictionary"])

# The universal half of a product: what is true wherever it is bought.
# Deliberately excludes code, unit_cost, current_stock and default_supplier_id.
DEFINITION_FIELDS = (
    "name", "description", "brand", "model_number", "series",
    "country_of_origin", "barcode", "hs_code", "unit",
    "length", "width", "height", "weight_per_unit", "dimension_unit", "weight_unit",
)


def _sku_key(sku: str) -> str:
    return " ".join(str(sku or "").split()).upper()


def _serialize(d: ProductDefinition, adopted_id=None) -> dict:
    out = {"id": d.id, "sku": d.sku, "source_org_id": d.source_org_id,
           "suggested_category_id": d.suggested_category_id,
           "is_active": bool(d.is_active), "adopted_product_id": adopted_id}
    for f in DEFINITION_FIELDS:
        value = getattr(d, f, None)
        out[f] = float(value) if isinstance(value, (int, float)) and f not in ("name", "unit") else value
    return out


@ProductDictionaryRouter.get("")
def list_definitions(
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Search the dictionary, marking what this company has already adopted."""
    if not has_permission(current_user, "View_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to view products.")

    query = db.query(ProductDefinition).filter(
        ProductDefinition.is_deleted == False,
        ProductDefinition.is_active == True,
    )
    if search and search.strip():
        like = f"%{search.strip()}%"
        query = query.filter(or_(
            ProductDefinition.sku.ilike(like),
            ProductDefinition.name.ilike(like),
            ProductDefinition.brand.ilike(like),
        ))
    rows = query.order_by(ProductDefinition.name.asc()).limit(limit).all()

    # Which of these this company already holds, so the screen offers "open"
    # rather than "adopt" and nobody creates a second copy.
    adopted = {}
    if rows:
        mine = apply_org_filter(
            db.query(Product.definition_id, Product.id).filter(
                Product.definition_id.in_([r.id for r in rows]),
                Product.is_deleted == False,
            ), Product, org_context,
        ).all()
        adopted = {definition_id: product_id for definition_id, product_id in mine}
    return [_serialize(r, adopted.get(r.id)) for r in rows]


@ProductDictionaryRouter.post("/publish/{product_id}")
def publish_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Publish one of this company's products to the group dictionary."""
    if not has_permission(current_user, "Edit_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to modify products.")

    product = apply_org_filter(
        db.query(Product).filter(Product.id == product_id, Product.is_deleted == False),
        Product, org_context,
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    if not (product.sku and product.sku.strip()):
        raise HTTPException(status_code=400, detail="A product needs a SKU before it can be published.")

    key = _sku_key(product.sku)
    existing = db.query(ProductDefinition).filter(
        ProductDefinition.sku_key == key, ProductDefinition.is_deleted == False
    ).first()
    if existing:
        # Deduplicated on SKU rather than creating a second entry -- the lesson
        # from the vendor master, which had to have its duplicates merged out.
        if product.definition_id != existing.id:
            product.definition_id = existing.id
            db.commit()
        return {"definition_id": existing.id, "created": False,
                "message": f"'{existing.name}' is already in the dictionary; this product now points at it."}

    definition = ProductDefinition(
        sku=product.sku.strip(), sku_key=key,
        suggested_category_id=product.category_id,
        source_org_id=product.org_id,
        created_by=current_user.id, updated_by=current_user.id,
        **{f: getattr(product, f, None) for f in DEFINITION_FIELDS},
    )
    db.add(definition)
    db.commit()
    db.refresh(definition)

    product.definition_id = definition.id
    db.commit()
    return {"definition_id": definition.id, "created": True,
            "message": f"'{definition.name}' published to the group dictionary."}


@ProductDictionaryRouter.post("/{definition_id}/adopt")
def adopt_definition(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Copy a definition into this company as a product of its own."""
    if not has_permission(current_user, "Add_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to create products.")

    definition = db.query(ProductDefinition).filter(
        ProductDefinition.id == definition_id, ProductDefinition.is_deleted == False
    ).first()
    if not definition:
        raise HTTPException(status_code=404, detail="Dictionary entry not found.")

    org_id = org_context.org_id

    already = db.query(Product).filter(
        Product.org_id == org_id, Product.is_deleted == False,
        or_(Product.definition_id == definition.id,
            func.upper(func.trim(Product.sku)) == definition.sku_key),
    ).first()
    if already:
        if already.definition_id is None:
            already.definition_id = definition.id
            db.commit()
        return {"product_id": already.id, "created": False,
                "message": f"This company already has '{already.name}'."}

    # A suggested category only applies if this company can actually see it.
    category_id = None
    note = None
    if definition.suggested_category_id:
        cat = db.query(ProductCategory).filter(
            ProductCategory.id == definition.suggested_category_id,
            ProductCategory.is_deleted == False,
        ).first()
        if cat and (cat.is_shared or cat.org_id == org_id):
            category_id = cat.id
        else:
            note = ("The suggested category belongs to a catalogue this company does not "
                    "read, so the product is uncategorised. File it under one of this "
                    "company's categories.")

    product = Product(
        org_id=org_id, sku=definition.sku, name=definition.name,
        category_id=category_id, definition_id=definition.id,
        status="active", current_stock=0, min_stock_quantity=0,
        created_by=current_user.id, updated_by=current_user.id,
        **{f: getattr(definition, f, None) for f in DEFINITION_FIELDS if f != "name"},
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"product_id": product.id, "created": True, "note": note,
            "message": f"'{product.name}' added to this company. Stock, cost and supplier are its own."}
