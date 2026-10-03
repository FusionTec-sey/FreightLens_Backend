"""Initial branch/location master: create and paginated read, no stock writes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Schema.InventoryLocationSchema import BranchCreate, BranchRead, LocationCreate, LocationRead, LocationPage
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch
from Model.containermgmt.Orders.Product import Product
from Schema.InventoryStockSchema import StockBalanceRead
from Services.inventory_quantity_service import QuantityBreakdown
from Model.containermgmt.Inventory.StockSerial import StockSerialIdentity, StockSerialPosition
from Schema.InventorySerialSchema import StockSerialRead

LocationRouter = APIRouter(prefix="/inventory/branches", tags=["Inventory Locations"])


def scoped_branch(db, context, branch_id):
    query = db.query(InventoryBranch).filter(InventoryBranch.id == branch_id, InventoryBranch.is_deleted == False)
    branch = apply_org_filter(query, InventoryBranch, context).first()
    if branch is None:
        raise HTTPException(404, "Branch not found")
    return branch


def scoped_location(db, context, branch, location_id):
    location = apply_org_filter(db.query(StockLocation).filter(
        StockLocation.id == location_id, StockLocation.branch_id == branch.id,
        StockLocation.org_id == branch.org_id, StockLocation.is_deleted.is_(False)), StockLocation, context).first()
    if location is None:
        raise HTTPException(404, "Location not found")
    return location


def page_result(query, page, limit, schema, model):
    total = query.count()
    rows = query.order_by(model.id).offset((page - 1) * limit).limit(limit).all()
    return {"items": [schema.model_validate(row) for row in rows], "total": total,
            "page": page, "pages": max(1, (total + limit - 1) // limit), "limit": limit}


def save(db, row, schema):
    try:
        db.add(row)
        db.flush()
        result = schema.model_validate(row)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Code already exists or location references conflict; reload and check the record")
    except Exception:
        db.rollback()
        raise


@LocationRouter.get("", response_model=LocationPage[BranchRead])
def list_branches(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                  db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                  user=Depends(require_permission("View_Product"))):
    query = apply_org_filter(db.query(InventoryBranch).filter(InventoryBranch.is_deleted == False), InventoryBranch, context)
    return page_result(query, page, limit, BranchRead, InventoryBranch)


@LocationRouter.post("", response_model=BranchRead, status_code=201)
def create_branch(payload: BranchCreate, db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context),
                  user=Depends(require_permission("Manage_InventoryLocation"))):
    if context.org_id not in context.allowed_org_ids:
        raise HTTPException(403, "Select an allowed organisation before creating a branch")
    row = InventoryBranch(**payload.model_dump(), org_id=context.org_id, created_by=user.id)
    return save(db, row, BranchRead)


@LocationRouter.get("/{branch_id}/locations", response_model=LocationPage[LocationRead])
def list_locations(branch_id: int, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                   db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                   user=Depends(require_permission("View_Product"))):
    branch = scoped_branch(db, context, branch_id)
    query = db.query(StockLocation).filter(StockLocation.branch_id == branch.id,
        StockLocation.org_id == branch.org_id, StockLocation.is_deleted == False)
    return page_result(query, page, limit, LocationRead, StockLocation)


@LocationRouter.get("/{branch_id}/locations/{location_id}/stock", response_model=LocationPage[StockBalanceRead])
def list_location_stock(branch_id: int, location_id: int,
                        page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                        user=Depends(require_permission("View_Product"))):
    """Exact location only: never roll children/remote stock or legacy totals in."""
    branch = scoped_branch(db, context, branch_id)
    location = scoped_location(db, context, branch, location_id)
    # Public product columns only: do not load eager supplier relationships.
    query = db.query(StockBalance.id, StockBalance.product_id, Product.sku,
        Product.name.label("product_name"), Product.status.label("product_status"),
        StockBalance.base_unit, StockBalance.tracking_policy, StockBalance.quantity_step, StockBalance.on_hand,
        StockBalance.reserved, StockBalance.damaged, StockBalance.quarantined,
        StockBalance.version, StockBalance.updated_at, StockBalance.batch_key,
        StockBatch.code.label("batch_code"), StockBatch.shade.label("batch_shade"),
        StockBatch.calibre.label("batch_calibre"), StockBatch.expires_on).join(Product,
            (Product.id == StockBalance.product_id) & (Product.org_id == StockBalance.org_id)
        ).outerjoin(StockBatch, (StockBatch.batch_key == StockBalance.batch_key)
            & (StockBatch.product_id == StockBalance.product_id) & (StockBatch.org_id == StockBalance.org_id)
        ).filter(StockBalance.org_id == branch.org_id, StockBalance.branch_id == branch.id,
            StockBalance.location_id == location.id, StockBalance.is_deleted.is_(False),
            Product.is_deleted.is_(False), Product.is_shared.is_(False))
    query = apply_org_filter(query, StockBalance, context)
    total = query.count()
    rows = query.order_by(StockBalance.id).offset((page - 1) * limit).limit(limit).all()
    items = []
    for row in rows:
        values = dict(row._mapping)
        values["unit_policy_status"] = "SNAPSHOTTED" if row.quantity_step is not None else "REVIEW_REQUIRED"
        values["available"] = QuantityBreakdown(row.on_hand, row.reserved, row.damaged, row.quarantined).available
        items.append(StockBalanceRead(**values))
    return {"items": items, "total": total, "page": page,
            "pages": max(1, (total + limit - 1) // limit), "limit": limit}


@LocationRouter.get("/{branch_id}/locations/{location_id}/stock/{balance_id}/serials", response_model=LocationPage[StockSerialRead])
def list_stock_serials(branch_id: int, location_id: int, balance_id: int,
                      page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                      db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                      user=Depends(require_permission("View_Product"))):
    branch = scoped_branch(db, context, branch_id)
    location = scoped_location(db, context, branch, location_id)
    balance = apply_org_filter(db.query(StockBalance).join(Product,
        (Product.id == StockBalance.product_id) & (Product.org_id == StockBalance.org_id)).filter(
        StockBalance.id == balance_id, StockBalance.location_id == location.id, StockBalance.branch_id == branch.id,
        StockBalance.org_id == branch.org_id, StockBalance.tracking_policy == "SERIAL",
        StockBalance.is_deleted.is_(False), Product.is_deleted.is_(False), Product.is_shared.is_(False)), StockBalance, context).first()
    if balance is None:
        raise HTTPException(404, "Serial stock not found")
    query = db.query(StockSerialIdentity.id, StockSerialIdentity.serial_key, StockSerialIdentity.serial_number,
        StockSerialPosition.condition).join(StockSerialPosition,
        (StockSerialPosition.serial_id == StockSerialIdentity.id) & (StockSerialPosition.org_id == StockSerialIdentity.org_id)
        & (StockSerialPosition.product_id == StockSerialIdentity.product_id)).filter(
        StockSerialPosition.balance_id == balance.id, StockSerialPosition.org_id == branch.org_id,
        StockSerialPosition.product_id == balance.product_id, StockSerialPosition.is_deleted.is_(False),
        StockSerialIdentity.is_deleted.is_(False))
    query = apply_org_filter(query, StockSerialIdentity, context)
    total = query.count()
    rows = query.order_by(StockSerialIdentity.id).offset((page - 1) * limit).limit(limit).all()
    return {"items": [StockSerialRead(**row._mapping) for row in rows], "total": total, "page": page,
            "pages": max(1, (total + limit - 1) // limit), "limit": limit}


@LocationRouter.post("/{branch_id}/locations", response_model=LocationRead, status_code=201)
def create_location(branch_id: int, payload: LocationCreate, db: Session = Depends(get_db),
                    context: OrgContext = Depends(get_org_context),
                    user=Depends(require_permission("Manage_InventoryLocation"))):
    branch = scoped_branch(db, context, branch_id)
    if not branch.is_active:
        raise HTTPException(409, "Branch is inactive")
    if payload.parent_id:
        parent = db.query(StockLocation).filter(StockLocation.id == payload.parent_id,
            StockLocation.branch_id == branch.id, StockLocation.org_id == branch.org_id,
            StockLocation.is_deleted == False).first()
        if parent is None:
            raise HTTPException(404, "Parent location not found")
        expected = "SITE" if payload.kind == "ZONE" else "ZONE"
        if not parent.is_active or parent.kind != expected:
            raise HTTPException(409, "Use an active site for a zone, or an active zone for a bin")
    row = StockLocation(**payload.model_dump(), branch_id=branch.id, org_id=branch.org_id, created_by=user.id)
    return save(db, row, LocationRead)
