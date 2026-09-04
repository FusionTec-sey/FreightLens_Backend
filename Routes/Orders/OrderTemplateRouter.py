import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc

from Model.db import get_db
from Model.containermgmt.Orders.OrderTemplate import OrderTemplate, OrderTemplateItem
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.orders.templates")

OrderTemplateRouter = APIRouter(prefix="/orders/templates", tags=["Order Templates"])

def is_accounts_user(user: User, org_context: OrgContext) -> bool:
    if org_context.is_root:
        return True
    user_roles = [r.name for r in getattr(user, "roles", [])]
    return any(r in ["Administrator", "Admin", "Account", "Accounts", "Accounts_Finance", "Finance"] for r in user_roles)

def template_to_dict(template: OrderTemplate, is_accounts: bool = True) -> dict:
    supplier_name = template.company
    if template.supplier_rel and template.supplier_rel.name:
        supplier_name = template.supplier_rel.name

    items = []
    for it in (template.items or []):
        if getattr(it, "is_deleted", False):
            continue
        items.append({
            "id": it.id,
            "product_id": it.product_id,
            "product_name": it.product.name if it.product else None,
            "item_code": it.item_code or (it.product.code if it.product else None) or (it.product.sku if it.product else None),
            "description": it.description,
            "default_quantity": float(it.default_quantity or 1),
            "unit": it.unit or (it.product.unit if it.product else "PCS"),
            "unit_price": float(it.unit_price) if it.unit_price is not None and is_accounts else (float(it.product.unit_cost) if it.product and it.product.unit_cost and is_accounts else None),
            "currency": it.currency or "USD",
            "sort_order": it.sort_order or 0,
            "notes": it.notes
        })

    return {
        "id": template.id,
        "org_id": template.org_id,
        "name": template.name,
        "description": template.description,
        "tags": template.tags or [],
        "supplier_id": template.supplier_id,
        "company": supplier_name,
        "freight_type": template.freight_type or "Sea Freight",
        "notes": template.notes,
        "visibility": template.visibility or "org",
        "created_by": template.created_by,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        "items_count": len(items),
        "items": items
    }

@OrderTemplateRouter.get("")
@OrderTemplateRouter.get("/")
async def list_templates(
    search: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    supplier_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    query = (
        db.query(OrderTemplate)
        .options(
            joinedload(OrderTemplate.supplier_rel),
            joinedload(OrderTemplate.items).joinedload(OrderTemplateItem.product)
        )
        .filter(OrderTemplate.is_deleted == False)
    )

    query = apply_org_filter(query, OrderTemplate, org_context)

    # Visibility filter: org-wide or user's own private templates
    if not is_accounts:
        query = query.filter(
            or_(
                OrderTemplate.visibility == "org",
                OrderTemplate.created_by == current_user.id
            )
        )

    # Search
    if search:
        s_term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                OrderTemplate.name.ilike(s_term),
                OrderTemplate.description.ilike(s_term),
                OrderTemplate.company.ilike(s_term),
                OrderTemplate.notes.ilike(s_term)
            )
        )

    if supplier_id:
        query = query.filter(OrderTemplate.supplier_id == supplier_id)

    templates = query.order_by(desc(OrderTemplate.created_at)).all()

    # Filter by tag in python if requested (since tags is stored in JSON column)
    results = []
    for t in templates:
        t_dict = template_to_dict(t, is_accounts)
        if tag:
            t_tags = [str(x).strip().lower() for x in (t_dict.get("tags") or [])]
            if tag.strip().lower() not in t_tags:
                continue
        results.append(t_dict)

    return results

@OrderTemplateRouter.get("/{template_id}")
async def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    template = (
        db.query(OrderTemplate)
        .options(
            joinedload(OrderTemplate.supplier_rel),
            joinedload(OrderTemplate.items).joinedload(OrderTemplateItem.product)
        )
        .filter(OrderTemplate.id == template_id, OrderTemplate.is_deleted == False)
        .first()
    )
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if template.visibility == "private" and template.created_by != current_user.id and not is_accounts:
        raise HTTPException(status_code=403, detail="Access denied to private template")

    return template_to_dict(template, is_accounts)

@OrderTemplateRouter.post("")
@OrderTemplateRouter.post("/")
async def create_template(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Template name is required")

    supplier_id = payload.get("supplier_id") or payload.get("supplier")
    company = (payload.get("company") or "").strip()
    if supplier_id:
        supp = db.query(Supplier).filter(Supplier.supplier_id == supplier_id).first()
        if supp:
            company = supp.name

    target_org_id = payload.get("org_id") or org_context.selected_org_id or current_user.org_id or 1

    template = OrderTemplate(
        org_id=target_org_id,
        name=name,
        description=payload.get("description"),
        tags=payload.get("tags") or [],
        supplier_id=supplier_id,
        company=company,
        freight_type=payload.get("freight_type", "Sea Freight"),
        notes=payload.get("notes") or payload.get("remark"),
        visibility=payload.get("visibility", "org"),
        created_by=current_user.id
    )
    db.add(template)
    db.flush()

    # Add items
    items_data = payload.get("items") or []
    for idx, it in enumerate(items_data):
        desc_text = (it.get("description") or "").strip()
        if not desc_text:
            continue
        item_obj = OrderTemplateItem(
            template_id=template.id,
            product_id=it.get("product_id"),
            item_code=it.get("item_code"),
            description=desc_text,
            default_quantity=it.get("default_quantity") or it.get("quantity") or 1.0,
            unit=it.get("unit") or "PCS",
            unit_price=it.get("unit_price") if is_accounts else None,
            currency=it.get("currency") or "USD",
            sort_order=it.get("sort_order", idx),
            notes=it.get("notes")
        )
        db.add(item_obj)

    db.commit()
    db.refresh(template)
    return template_to_dict(template, is_accounts)

@OrderTemplateRouter.put("/{template_id}")
@OrderTemplateRouter.patch("/{template_id}")
async def update_template(
    template_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    template = db.query(OrderTemplate).filter(
        OrderTemplate.id == template_id,
        OrderTemplate.is_deleted == False
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if template.visibility == "private" and template.created_by != current_user.id and not is_accounts:
        raise HTTPException(status_code=403, detail="Permission denied to edit this template")

    if "name" in payload:
        template.name = payload["name"].strip()
    if "description" in payload:
        template.description = payload["description"]
    if "tags" in payload:
        template.tags = payload["tags"]
    if "freight_type" in payload:
        template.freight_type = payload["freight_type"]
    if "notes" in payload:
        template.notes = payload["notes"]
    if "visibility" in payload:
        template.visibility = payload["visibility"]
    if "supplier_id" in payload or "supplier" in payload:
        s_id = payload.get("supplier_id") or payload.get("supplier")
        template.supplier_id = s_id
        if s_id:
            supp = db.query(Supplier).filter(Supplier.supplier_id == s_id).first()
            if supp:
                template.company = supp.name
        else:
            template.company = payload.get("company", "")

    # If items list provided, replace template items
    if "items" in payload:
        # Soft-delete or remove existing items
        for existing_it in template.items:
            db.delete(existing_it)
        db.flush()

        items_data = payload.get("items") or []
        for idx, it in enumerate(items_data):
            desc_text = (it.get("description") or "").strip()
            if not desc_text:
                continue
            item_obj = OrderTemplateItem(
                template_id=template.id,
                product_id=it.get("product_id"),
                item_code=it.get("item_code"),
                description=desc_text,
                default_quantity=it.get("default_quantity") or it.get("quantity") or 1.0,
                unit=it.get("unit") or "PCS",
                unit_price=it.get("unit_price") if is_accounts else None,
                currency=it.get("currency") or "USD",
                sort_order=it.get("sort_order", idx),
                notes=it.get("notes")
            )
            db.add(item_obj)

    template.updated_by = current_user.id
    db.commit()
    db.refresh(template)
    return template_to_dict(template, is_accounts)

@OrderTemplateRouter.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    template = db.query(OrderTemplate).filter(
        OrderTemplate.id == template_id,
        OrderTemplate.is_deleted == False
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if template.visibility == "private" and template.created_by != current_user.id and not is_accounts:
        raise HTTPException(status_code=403, detail="Permission denied to delete this template")

    template.is_deleted = True
    template.deleted_by = current_user.id
    db.commit()
    return {"message": "Template deleted successfully", "id": template_id}
