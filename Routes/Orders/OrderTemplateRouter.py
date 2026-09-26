import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc, cast, String

from Model.db import get_db
from Model.containermgmt.Orders.OrderTemplate import OrderTemplate, OrderTemplateItem
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import is_financial_user, has_permission
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.orders.templates")

OrderTemplateRouter = APIRouter(prefix="/orders/templates", tags=["Order Templates"])

def safe_float(val, default=None):
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def is_accounts_user(user: User, org_context: OrgContext) -> bool:
    return is_financial_user(user, org_context)

def check_can_view_supplier(user: User, org_context: OrgContext) -> bool:
    """
    Zero-trust supplier permission check.
    Only allows viewing vendor/supplier identities if:
    - Root tenant super admins or users with role Administrator
    - User explicitly holds View_Supplier or Supplier permission
    Does NOT infer view access from financial clearance or unrelated roles.
    """
    if not user:
        return False
    if org_context and org_context.is_root:
        return True

    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "administrator", "root"] for r in user_roles):
        return True

    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["View_Supplier", "Supplier"]:
                return True
    return False

def template_to_dict(template: OrderTemplate, is_accounts: bool = True, can_view_supplier: bool = True) -> dict:
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
        "supplier_id": template.supplier_id if can_view_supplier else None,
        "company": supplier_name if can_view_supplier else None,
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
    for_sourcing: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    if not (has_permission(current_user, "View_OrderTemplate") or has_permission(current_user, "View_Order") or is_accounts):
        raise HTTPException(status_code=403, detail="Access forbidden: Missing View_OrderTemplate permission")

    can_view_supplier = check_can_view_supplier(current_user, org_context) and not for_sourcing

    query = (
        db.query(OrderTemplate)
        .options(
            joinedload(OrderTemplate.supplier_rel),
            joinedload(OrderTemplate.items).joinedload(OrderTemplateItem.product)
        )
        .filter(OrderTemplate.is_deleted == False)
    )

    # Multi-tenant and Blueprint Sharing Filter:
    # 1. Root Org users can view templates in their allowed_org_ids or selected_org_id, plus global/master blueprints.
    # 2. Sub-Org users (e.g. Noblecon) can view templates belonging to their own org,
    #    PLUS standard master blueprints from Root Org (org_id=1) that are not private,
    #    or global templates (visibility='global' or org_id IS NULL).
    if org_context.is_root:
        if org_context.selected_org_id:
            query = query.filter(
                or_(
                    OrderTemplate.org_id == org_context.selected_org_id,
                    OrderTemplate.visibility == "global"
                )
            )
        else:
            query = query.filter(
                or_(
                    OrderTemplate.org_id.in_(org_context.allowed_org_ids),
                    OrderTemplate.org_id.is_(None),
                    OrderTemplate.visibility == "global"
                )
            )
    else:
        query = query.filter(
            or_(
                OrderTemplate.org_id.in_(org_context.allowed_org_ids),
                and_(
                    OrderTemplate.org_id == 1,
                    OrderTemplate.visibility.in_(["org", "global"])
                ),
                OrderTemplate.org_id.is_(None),
                OrderTemplate.visibility == "global"
            )
        )

    # Visibility filter: org-wide/global or user's own private templates
    if not is_accounts:
        query = query.filter(
            or_(
                OrderTemplate.visibility.in_(["org", "global"]),
                OrderTemplate.created_by == current_user.id
            )
        )

    # Search
    if search:
        s_term = f"%{search.strip()}%"
        search_clauses = [
            OrderTemplate.name.ilike(s_term),
            OrderTemplate.description.ilike(s_term),
            OrderTemplate.notes.ilike(s_term),
            cast(OrderTemplate.tags, String).ilike(s_term)
        ]
        if can_view_supplier:
            search_clauses.append(OrderTemplate.company.ilike(s_term))
        query = query.filter(or_(*search_clauses))

    if supplier_id:
        query = query.filter(OrderTemplate.supplier_id == supplier_id)

    templates = query.order_by(desc(OrderTemplate.created_at)).all()

    # Filter by tag in python if requested (since tags is stored in JSON column)
    results = []
    for t in templates:
        t_dict = template_to_dict(t, is_accounts, can_view_supplier)
        if tag:
            t_tags = [str(x).strip().lower() for x in (t_dict.get("tags") or [])]
            if tag.strip().lower() not in t_tags:
                continue
        results.append(t_dict)

    return results

@OrderTemplateRouter.get("/tags")
async def list_template_tags(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    if not (has_permission(current_user, "View_OrderTemplate") or has_permission(current_user, "View_Order") or is_accounts):
        raise HTTPException(status_code=403, detail="Access forbidden: Missing View_OrderTemplate permission")

    query = db.query(OrderTemplate.tags).filter(OrderTemplate.is_deleted == False)

    if org_context.is_root:
        if org_context.selected_org_id:
            query = query.filter(
                or_(
                    OrderTemplate.org_id == org_context.selected_org_id,
                    OrderTemplate.visibility == "global"
                )
            )
        else:
            query = query.filter(
                or_(
                    OrderTemplate.org_id.in_(org_context.allowed_org_ids),
                    OrderTemplate.org_id.is_(None),
                    OrderTemplate.visibility == "global"
                )
            )
    else:
        query = query.filter(
            or_(
                OrderTemplate.org_id.in_(org_context.allowed_org_ids),
                and_(OrderTemplate.org_id == 1, OrderTemplate.visibility.in_(["org", "global"])),
                OrderTemplate.org_id.is_(None),
                OrderTemplate.visibility == "global"
            )
        )

    if not is_accounts:
        query = query.filter(
            or_(
                OrderTemplate.visibility.in_(["org", "global"]),
                OrderTemplate.created_by == current_user.id
            )
        )

    tag_rows = query.all()
    all_tags = set()
    for row in tag_rows:
        tags_val = row[0]
        if isinstance(tags_val, list):
            for t in tags_val:
                if t and str(t).strip():
                    all_tags.add(str(t).strip())

    return sorted(list(all_tags), key=lambda x: x.lower())

@OrderTemplateRouter.get("/{template_id}")
async def get_template(
    template_id: int,
    for_sourcing: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    if not (has_permission(current_user, "View_OrderTemplate") or has_permission(current_user, "View_Order") or is_accounts):
        raise HTTPException(status_code=403, detail="Access forbidden: Missing View_OrderTemplate permission")

    can_view_supplier = check_can_view_supplier(current_user, org_context) and not for_sourcing

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

    return template_to_dict(template, is_accounts, can_view_supplier)

@OrderTemplateRouter.post("")
@OrderTemplateRouter.post("/")
async def create_template(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    if not (has_permission(current_user, "Add_OrderTemplate") or has_permission(current_user, "Add_Order") or is_accounts):
        raise HTTPException(status_code=403, detail="Access forbidden: Missing Add_OrderTemplate permission")

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
        default_qty = safe_float(it.get("default_quantity") or it.get("quantity"), 1.0)
        u_price = safe_float(it.get("unit_price")) if is_accounts else None
        item_obj = OrderTemplateItem(
            template_id=template.id,
            product_id=it.get("product_id"),
            item_code=it.get("item_code"),
            description=desc_text,
            default_quantity=default_qty,
            unit=it.get("unit") or "PCS",
            unit_price=u_price,
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
    if not (has_permission(current_user, "Edit_OrderTemplate") or has_permission(current_user, "Edit_Order") or is_accounts):
        raise HTTPException(status_code=403, detail="Access forbidden: Missing Edit_OrderTemplate permission")

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
            default_qty = safe_float(it.get("default_quantity") or it.get("quantity"), 1.0)
            u_price = safe_float(it.get("unit_price")) if is_accounts else None
            item_obj = OrderTemplateItem(
                template_id=template.id,
                product_id=it.get("product_id"),
                item_code=it.get("item_code"),
                description=desc_text,
                default_quantity=default_qty,
                unit=it.get("unit") or "PCS",
                unit_price=u_price,
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
    if not (has_permission(current_user, "Delete_OrderTemplate") or has_permission(current_user, "Delete_Order") or is_accounts):
        raise HTTPException(status_code=403, detail="Access forbidden: Missing Delete_OrderTemplate permission")

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
