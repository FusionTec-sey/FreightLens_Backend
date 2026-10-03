from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.UnitBarcode import UnitBarcodeRetirement
from Services.barcode_retirement_service import retirements
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Schema.UnitBarcodeSchema import UnitBarcodeCreate, UnitBarcodeRead
from Schema.InventoryLocationSchema import LocationPage
from Services.unit_barcode_service import (barcode_query, barcode_product, barcode_result,
    register_barcode, BarcodeSourceUnavailable, barcode_eligible)
from Services.policy_activation_service import active_policy
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission

UnitBarcodeRouter = APIRouter(prefix="/inventory/unit-barcodes", tags=["Inventory Unit Barcodes"])


def visible_product(db, context, product_id):
    try: return barcode_product(db, context, product_id)
    except BarcodeSourceUnavailable as exc: raise HTTPException(404, str(exc)) from exc


@UnitBarcodeRouter.get("/resolve", response_model=UnitBarcodeRead)
def resolve_barcode(code: str = Query(min_length=1, max_length=100, pattern=r"^[!-~]+$"),
                    db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                    user=Depends(require_permission("View_Product"))):
    row = barcode_query(db, context).filter_by(barcode=code).one_or_none()
    if row is None: raise HTTPException(404, "Registered unit barcode not found")
    product = visible_product(db, context, row.product_id)
    if retirements(db, context).filter_by(barcode_id=row.id).first():
        raise HTTPException(409, "Barcode is retired; its identity cannot be reused")
    policy = active_policy(db, context, row.product_id)
    original = apply_org_filter(db.query(ProductPolicyActivation).filter(
        ProductPolicyActivation.org_id == context.org_id, ProductPolicyActivation.product_id == row.product_id,
        ProductPolicyActivation.version == row.policy_version, ProductPolicyActivation.is_deleted.is_(False)),
        ProductPolicyActivation, context).one_or_none()
    if not barcode_eligible(row, original, policy, product):
        raise HTTPException(409, "Barcode requires policy review before use")
    return dict(barcode_result(row, original, product), eligible=True)


@UnitBarcodeRouter.get("/products/{product_id}", response_model=LocationPage[UnitBarcodeRead])
def list_barcodes(product_id: int, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                  db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                  user=Depends(require_permission("View_Product"))):
    product = visible_product(db, context, product_id)
    query = barcode_query(db, context).filter_by(product_id=product_id)
    total = query.count()
    rows = query.order_by("id").offset((page - 1) * limit).limit(limit).all()
    versions = {row.policy_version for row in rows}
    history = apply_org_filter(db.query(ProductPolicyActivation).filter(ProductPolicyActivation.org_id == context.org_id,
        ProductPolicyActivation.product_id == product_id, ProductPolicyActivation.version.in_(versions),
        ProductPolicyActivation.is_deleted.is_(False)), ProductPolicyActivation, context).all() if versions else []
    snapshots = {row.version: row for row in history}
    active = active_policy(db, context, product_id)
    retired = {entry.barcode_id for entry in retirements(db, context).filter(
        UnitBarcodeRetirement.barcode_id.in_([row.id for row in rows])).all()} if rows else set()
    items = [dict(barcode_result(row, snapshots[row.policy_version], product),
                  retired=row.id in retired,
                  eligible=bool(row.id not in retired and barcode_eligible(row, snapshots[row.policy_version], active, product))) for row in rows]
    return {"items": items, "page": page, "limit": limit, "total": total, "pages": max(1, (total + limit - 1) // limit)}


@UnitBarcodeRouter.post("/products/{product_id}", response_model=UnitBarcodeRead)
def create_barcode(product_id: int, payload: UnitBarcodeCreate, db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context), user=Depends(require_permission("Manage_InventoryBarcode"))):
    try:
        if not db.in_transaction(): db.begin()
        outcome = register_barcode(db, context, user.id, product_id=product_id, payload=payload, authorize=lambda session: None)
        db.commit()
        return UnitBarcodeRead(**outcome.result, replayed=outcome.replayed)
    except Exception as exc:
        db.rollback()
        if isinstance(exc, BarcodeSourceUnavailable): raise HTTPException(404, str(exc)) from exc
        if isinstance(exc, PostingConflict): raise HTTPException(409, str(exc)) from exc
        if isinstance(exc, IntegrityError): raise HTTPException(409, "Barcode conflicts with an existing identity") from exc
        if isinstance(exc, ValueError): raise HTTPException(422, str(exc)) from exc
        raise
