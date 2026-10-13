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
    include_unlisted: bool = Query(False, description="Also show entries that have been unlisted, so they can be offered again"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Search the dictionary, marking what this company has already adopted."""
    if not has_permission(current_user, "View_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to view products.")

    query = db.query(ProductDefinition).filter(ProductDefinition.is_deleted == False)
    if not include_unlisted:
        # An unlisted entry is hidden by default but must stay reachable, or
        # there would be no way to offer it again.
        query = query.filter(ProductDefinition.is_active == True)
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


def _publish_one(db: Session, product: Product, user_id: int):
    """Publish a product, or link it to the entry its SKU already has.

    Returns (definition, created). Deduplicated on the normalised SKU rather
    than creating a second entry -- the lesson from the vendor master, which had
    to have its duplicates merged out after the fact.
    """
    key = _sku_key(product.sku)
    existing = db.query(ProductDefinition).filter(
        ProductDefinition.sku_key == key, ProductDefinition.is_deleted == False
    ).first()
    if existing:
        if product.definition_id != existing.id:
            product.definition_id = existing.id
        return existing, False

    definition = ProductDefinition(
        sku=product.sku.strip(), sku_key=key,
        suggested_category_id=product.category_id,
        source_org_id=product.org_id,
        created_by=user_id, updated_by=user_id,
        **{f: getattr(product, f, None) for f in DEFINITION_FIELDS},
    )
    db.add(definition)
    db.flush()
    product.definition_id = definition.id
    return definition, True


@ProductDictionaryRouter.post("/publish-bulk")
def publish_products_bulk(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Publish many of this company's products at once.

    A catalogue of thousands cannot be published a row at a time, and the
    dictionary is useless until something is in it.
    """
    if not has_permission(current_user, "Edit_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to modify products.")

    product_ids = (payload or {}).get("product_ids")
    publish_all = bool((payload or {}).get("all"))
    if not product_ids and not publish_all:
        raise HTTPException(status_code=400, detail="Give product_ids, or all=true for this company's whole catalogue.")

    query = db.query(Product).filter(Product.is_deleted == False)
    if not publish_all:
        query = query.filter(Product.id.in_(product_ids))
    products = apply_org_filter(query, Product, org_context).all()

    published, linked, skipped = 0, 0, 0
    for product in products:
        if not (product.sku and product.sku.strip()):
            skipped += 1  # no SKU, so nothing to deduplicate it against
            continue
        _definition, created = _publish_one(db, product, current_user.id)
        if created:
            published += 1
        else:
            linked += 1
    db.commit()

    parts = [f"{published} published"]
    if linked:
        parts.append(f"{linked} already in the dictionary and now linked")
    if skipped:
        parts.append(f"{skipped} skipped for having no SKU")
    return {"published": published, "linked": linked, "skipped_no_sku": skipped,
            "considered": len(products), "message": ", ".join(parts) + "."}


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

    definition, created = _publish_one(db, product, current_user.id)
    db.commit()
    if not created:
        return {"definition_id": definition.id, "created": False,
                "message": f"'{definition.name}' is already in the dictionary; this product now points at it."}
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


@ProductDictionaryRouter.get("/{definition_id}/usage")
def get_definition_usage(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Which companies have adopted this entry, shown before it is withdrawn."""
    if not has_permission(current_user, "View_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to view products.")
    definition = db.query(ProductDefinition).filter(
        ProductDefinition.id == definition_id, ProductDefinition.is_deleted == False
    ).first()
    if not definition:
        raise HTTPException(status_code=404, detail="Dictionary entry not found.")

    rows = db.query(Product.org_id, func.count(Product.id)).filter(
        Product.definition_id == definition_id, Product.is_deleted == False
    ).group_by(Product.org_id).all()
    return {
        "name": definition.name, "sku": definition.sku,
        "adopted_by_companies": len(rows),
        "adopted_products": sum(int(c) for _o, c in rows),
        "is_active": bool(definition.is_active),
    }


@ProductDictionaryRouter.post("/{definition_id}/withdraw")
def withdraw_definition(
    definition_id: int,
    payload: Optional[dict] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Take an entry out of the dictionary, or just stop offering it.

    Nothing breaks either way, which is the whole point of copying rather than
    sharing: every company that adopted it already holds its own product, with
    its own stock, cost and supplier. Only the link back is affected, and only
    on a full removal.
    """
    if not has_permission(current_user, "Edit_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to modify products.")

    definition = db.query(ProductDefinition).filter(
        ProductDefinition.id == definition_id, ProductDefinition.is_deleted == False
    ).first()
    if not definition:
        raise HTTPException(status_code=404, detail="Dictionary entry not found.")

    adopted = db.query(func.count(Product.id)).filter(
        Product.definition_id == definition_id, Product.is_deleted == False
    ).scalar() or 0

    # "unlist" keeps the entry and its links, and stops it being adopted again.
    # "remove" deletes it; the FK is SET NULL, so the copies simply lose their
    # provenance rather than their data.
    mode = ((payload or {}).get("mode") or "unlist").lower()
    if mode not in ("unlist", "remove"):
        raise HTTPException(status_code=400, detail="mode must be 'unlist' or 'remove'.")

    if mode == "unlist":
        definition.is_active = False
        definition.updated_by = current_user.id
        db.commit()
        return {"mode": "unlist", "adopted_products": adopted,
                "message": (f"'{definition.name}' is no longer offered in the dictionary. "
                            f"{adopted} product(s) already copied from it keep working.")}

    db.query(Product).filter(Product.definition_id == definition_id).update(
        {Product.definition_id: None}, synchronize_session=False
    )
    definition.is_deleted = True
    definition.is_active = False
    definition.updated_by = current_user.id
    db.commit()
    return {"mode": "remove", "adopted_products": adopted,
            "message": (f"'{definition.name}' removed from the dictionary. "
                        f"{adopted} product(s) copied from it keep their data and lose only the link.")}


@ProductDictionaryRouter.post("/relist/{definition_id}")
def relist_definition(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Offer an unlisted entry again."""
    if not has_permission(current_user, "Edit_Product"):
        raise HTTPException(status_code=403, detail="Insufficient permissions to modify products.")
    definition = db.query(ProductDefinition).filter(
        ProductDefinition.id == definition_id, ProductDefinition.is_deleted == False
    ).first()
    if not definition:
        raise HTTPException(status_code=404, detail="Dictionary entry not found.")
    definition.is_active = True
    definition.updated_by = current_user.id
    db.commit()
    return {"message": f"'{definition.name}' is offered in the dictionary again."}
