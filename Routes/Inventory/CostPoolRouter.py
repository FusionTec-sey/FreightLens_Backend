"""Cost pool configuration only; no stock journal, valuation or price mutation."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.CostPool import InventoryCostPool, BranchCostPool
from Model.containermgmt.Inventory.PostingAuthority import CostPoolAuthorityEpoch
from Schema.InventoryLocationSchema import LocationPage
from Schema.InventoryCostPoolSchema import CostPoolCreate, CostPoolRead, BranchCostPoolAssign, BranchCostPoolRead
from Routes.Inventory.LocationRouter import page_result, save, scoped_branch
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission

CostPoolRouter = APIRouter(prefix="/inventory", tags=["Inventory Cost Pools"])


from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Orders.Product import Product
from Schema.InventoryValuationSchema import InventoryValuationRead
from Schema.InventoryValuationSchema import CostAllocationPreviewRequest, CostAllocationPreview
from Services.inventory_costing_service import allocate_additional_cost
from decimal import Decimal
from uuid import UUID
from Model.containermgmt.Inventory.CostAllocation import CostAllocationProposal
from Schema.CostAllocationSchema import CostAllocationSave, CostAllocationSaved, CostAllocationSummary, CostAllocationDetail
from Services.cost_allocation_proposal_service import save_allocation_proposal
from Services.inventory_posting_service import PostingConflict
from typing import Literal
from Schema.CostAllocationSchema import CostAllocationReviewRequest, CostAllocationCaseRead
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page, case_metadata
from Services.cost_allocation_proposal_service import load_allocation_binding


def allocation_binding(db, context, pool_id, key, reviewer_id=None):
    return load_allocation_binding(db, context, pool_id, key, reviewer_id=reviewer_id,
        load_snapshot=lambda session, manifest: preview_cost_allocation(pool_id,
            CostAllocationPreviewRequest(**{field: manifest[field] for field in ('valuation_ids', 'total_scr', 'basis')}),
            db=session, context=context, user=None))


def allocation_cases(db, context, pool_id, key):
    row = cost_proposals(db, context, pool_id).filter_by(proposal_key=key).one_or_none()
    if row is None: raise HTTPException(404, 'Cost allocation proposal not found')
    return apply_org_filter(db.query(ManagerCase).filter_by(org_id=context.org_id, is_deleted=False,
        action='inventory.cost.allocate', source_type='inventory.cost-allocation', source_key=str(key)), ManagerCase, context)


def allocation_review_error(error):
    if isinstance(error, LookupError): return HTTPException(404, str(error))
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


@CostPoolRouter.post('/cost-pools/{pool_id}/allocation-proposals/{key}/request-review', response_model=CaseActionRead,
    dependencies=[Depends(require_permission('View_Product')), Depends(require_permission('View_Financials'))])
def request_allocation_review(pool_id: int, key: UUID, payload: CostAllocationReviewRequest,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('Manage_Financials'))):
    try:
        load = lambda session: allocation_binding(session, context, pool_id, key)
        outcome = request_case(db, context, user.id, payload.operation_key, binding=load(db), reason=payload.reason,
            load_binding=load, authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise allocation_review_error(error) from error


@CostPoolRouter.get('/cost-pools/{pool_id}/allocation-proposals/{key}/cases', response_model=LocationPage[CostAllocationCaseRead],
    dependencies=[Depends(require_permission('View_Product'))])
def list_allocation_reviews(pool_id: int, key: UUID, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        view: Literal['ALL', 'NEEDS_MY_REVIEW', 'MY_REQUESTS'] = Query('ALL'),
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('View_Financials'))):
    query = allocation_cases(db, context, pool_id, key)
    if view == 'NEEDS_MY_REVIEW':
        query = query.filter(ManagerCase.binding['details']['creator_id'].as_integer() != user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    return dict(items=[dict(**case_metadata(case, decision, used),
        creator_id=case.binding['details']['creator_id'], charge_reference=case.binding['details']['manifest']['charge_reference'],
        declaration_reason=case.binding['details']['manifest']['reason'],
        snapshot=case.binding['details']['snapshot']) for case, decision, used in rows], total=total,
        page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@CostPoolRouter.post('/cost-pools/{pool_id}/allocation-proposals/{key}/cases/{case_key}/review', response_model=CaseActionRead,
    dependencies=[Depends(require_permission('View_Product')), Depends(require_permission('View_Financials'))])
def review_allocation(pool_id: int, key: UUID, case_key: UUID, payload: PolicyCaseReview,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('Manage_Financials'))):
    try:
        case = allocation_cases(db, context, pool_id, key).filter_by(case_key=case_key).one_or_none()
        if case is None: raise HTTPException(404, 'Cost allocation review not found')
        outcome = review_case(db, context, user.id, payload.operation_key, case_key=case_key,
            binding=CaseBinding(**case.binding), expected_version=payload.expected_version, outcome=payload.outcome,
            reason=payload.reason, load_binding=lambda session: allocation_binding(session, context, pool_id, key, user.id),
            authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise allocation_review_error(error) from error


def scoped_pool(db, context, pool_id):
    pool = apply_org_filter(db.query(InventoryCostPool.id).filter(InventoryCostPool.id == pool_id,
        InventoryCostPool.org_id == context.org_id, InventoryCostPool.is_deleted.is_(False)), InventoryCostPool, context).first()
    if pool is None: raise HTTPException(404, 'Cost pool not found')
    return pool


def cost_proposals(db, context, pool_id):
    scoped_pool(db, context, pool_id)
    return apply_org_filter(db.query(CostAllocationProposal).filter_by(org_id=context.org_id,
        cost_pool_id=pool_id, is_deleted=False), CostAllocationProposal, context)


@CostPoolRouter.post('/cost-pools/{pool_id}/allocation-proposals', response_model=CostAllocationSaved,
    dependencies=[Depends(require_permission('View_Product')), Depends(require_permission('View_Financials'))])
def save_cost_allocation(pool_id: int, payload: CostAllocationSave, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context), user=Depends(require_permission('Manage_Financials'))):
    try:
        if not db.in_transaction(): db.begin()
        outcome = save_allocation_proposal(db, context, user.id, pool_id, payload, authorize=lambda session: None,
            load_snapshot=lambda session: preview_cost_allocation(pool_id, payload, db=session, context=context, user=user))
        db.commit()
        return CostAllocationSaved(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback()
        if isinstance(error, PostingConflict): raise HTTPException(409, str(error)) from error
        if isinstance(error, ValueError): raise HTTPException(422, str(error)) from error
        raise


@CostPoolRouter.get('/cost-pools/{pool_id}/allocation-proposals', response_model=LocationPage[CostAllocationSummary],
    dependencies=[Depends(require_permission('View_Product'))])
def list_cost_allocations(pool_id: int, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context), user=Depends(require_permission('View_Financials'))):
    query = cost_proposals(db, context, pool_id)
    total = query.count()
    rows = query.with_entities(CostAllocationProposal.proposal_key, CostAllocationProposal.created_at,
        CostAllocationProposal.manifest['charge_reference'].astext.label('charge_reference'),
        CostAllocationProposal.snapshot['total_scr'].astext.label('total_scr'),
        CostAllocationProposal.snapshot['basis'].astext.label('basis')).order_by(CostAllocationProposal.created_at.desc(),
        CostAllocationProposal.proposal_key.desc()).offset((page - 1) * limit).limit(limit).all()
    return dict(items=[dict(row._mapping) for row in rows], total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@CostPoolRouter.get('/cost-pools/{pool_id}/allocation-proposals/{key}', response_model=CostAllocationDetail,
    dependencies=[Depends(require_permission('View_Product'))])
def read_cost_allocation(pool_id: int, key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context), user=Depends(require_permission('View_Financials'))):
    row = cost_proposals(db, context, pool_id).filter(CostAllocationProposal.proposal_key == key).one_or_none()
    if row is None: raise HTTPException(404, 'Cost allocation proposal not found')
    return dict(proposal_key=row.proposal_key, created_at=row.created_at, charge_reference=row.manifest['charge_reference'],
        total_scr=row.snapshot['total_scr'], basis=row.snapshot['basis'], reason=row.manifest['reason'], snapshot=row.snapshot)


@CostPoolRouter.get('/cost-pools/{pool_id}/valuations', response_model=LocationPage[InventoryValuationRead],
    dependencies=[Depends(require_permission('View_Product'))])
def list_valuations(pool_id: int, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                    db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                    user=Depends(require_permission('View_Financials'))):
    pool = apply_org_filter(db.query(InventoryCostPool.id).filter(InventoryCostPool.id == pool_id,
        InventoryCostPool.org_id == context.org_id, InventoryCostPool.is_deleted.is_(False)), InventoryCostPool, context).first()
    if pool is None:
        raise HTTPException(404, 'Cost pool not found')
    query = visible_valuations(db, context, pool_id)
    total = query.count()
    rows = query.order_by(InventoryValuation.id.desc()).offset((page - 1) * limit).limit(limit).all()
    items = [{**{field: getattr(row, field) for field in ('id', 'product_id', 'balance_id', 'source_version',
        'version', 'base_unit', 'status', 'reason', 'created_at', 'kind', 'source_valuation_id')}, 'product_name': name,
        **{field: format(getattr(row, field), '.6f') for field in ('quantity', 'goods_value_scr',
        'additional_cost_scr', 'pool_quantity', 'pool_value_scr')}} for row, name in rows]
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


def visible_valuations(db, context, pool_id):
    query = db.query(InventoryValuation, Product.name).join(Product,
        (Product.id == InventoryValuation.product_id) & (Product.org_id == InventoryValuation.org_id))
    query = query.join(StockBalance, (StockBalance.id == InventoryValuation.balance_id) & (StockBalance.org_id == InventoryValuation.org_id))
    query = query.join(StockLocation, (StockLocation.id == StockBalance.location_id) & (StockLocation.org_id == StockBalance.org_id))
    query = query.join(InventoryBranch, (InventoryBranch.id == StockBalance.branch_id) & (InventoryBranch.org_id == StockBalance.org_id))
    query = apply_org_filter(query.filter(InventoryValuation.org_id == context.org_id,
        InventoryValuation.cost_pool_id == pool_id, InventoryValuation.is_deleted.is_(False),
        Product.is_deleted.is_(False), Product.is_shared.is_(False), StockBalance.is_deleted.is_(False),
        StockLocation.is_deleted.is_(False), InventoryBranch.is_deleted.is_(False)), InventoryValuation, context)
    return query


@CostPoolRouter.post('/cost-pools/{pool_id}/allocate-cost-preview', response_model=CostAllocationPreview,
    dependencies=[Depends(require_permission('View_Product'))])
def preview_cost_allocation(pool_id: int, payload: CostAllocationPreviewRequest,
                    db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                    user=Depends(require_permission('View_Financials'))):
    pool = apply_org_filter(db.query(InventoryCostPool.id).filter(InventoryCostPool.id == pool_id,
        InventoryCostPool.org_id == context.org_id, InventoryCostPool.is_deleted.is_(False)), InventoryCostPool, context).first()
    if pool is None:
        raise HTTPException(404, 'Cost pool not found')
    rows = visible_valuations(db, context, pool_id).filter(InventoryValuation.id.in_(payload.valuation_ids), InventoryValuation.kind == 'OPENING').order_by(InventoryValuation.id).all()
    if len(rows) != len(payload.valuation_ids):
        raise HTTPException(404, 'One or more valuation sources are unavailable in this pool')
    if payload.basis == 'BASE_QUANTITY' and len({row.base_unit for row, _ in rows}) != 1:
        raise HTTPException(422, 'Quantity allocation requires the same base unit; use goods value for mixed units')
    bases = {str(row.id): row.quantity if payload.basis == 'BASE_QUANTITY' else row.goods_value_scr for row, _ in rows}
    try:
        allocated = allocate_additional_cost(Decimal(payload.total_scr), bases)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return dict(basis=payload.basis, total_scr=format(Decimal(payload.total_scr), '.6f'),
        lines=[dict(valuation_id=row.id, balance_id=row.balance_id, product_id=row.product_id, product_name=name,
            base_unit=row.base_unit, basis_value=format(bases[str(row.id)], '.6f'), allocated_scr=format(allocated[str(row.id)], '.6f')) for row, name in rows])


@CostPoolRouter.get("/cost-pools", response_model=LocationPage[CostPoolRead])
def list_cost_pools(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                    db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                    user=Depends(require_permission("View_Product"))):
    query = apply_org_filter(db.query(InventoryCostPool).filter(InventoryCostPool.is_deleted == False), InventoryCostPool, context)
    result = page_result(query, page, limit, CostPoolRead, InventoryCostPool)
    ids = [row.id for row in result['items']]
    if ids:
        # One bounded page lookup, never one query per pool or a full history load.
        authority = apply_org_filter(db.query(CostPoolAuthorityEpoch).filter(
            CostPoolAuthorityEpoch.cost_pool_id.in_(ids), CostPoolAuthorityEpoch.is_deleted.is_(False)),
            CostPoolAuthorityEpoch, context).distinct(
                CostPoolAuthorityEpoch.org_id, CostPoolAuthorityEpoch.cost_pool_id).order_by(
                CostPoolAuthorityEpoch.org_id, CostPoolAuthorityEpoch.cost_pool_id,
                CostPoolAuthorityEpoch.epoch.desc()).all()
        latest = {(row.org_id, row.cost_pool_id): row for row in authority}
        for pool in result['items']:
            row = latest.get((pool.org_id, pool.id))
            if row:
                pool.central_authority_state = row.state
                pool.central_authority_epoch = row.epoch
    return result


@CostPoolRouter.post("/cost-pools", response_model=CostPoolRead, status_code=201)
def create_cost_pool(payload: CostPoolCreate, db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context),
                     user=Depends(require_permission("Manage_InventoryCostPool"))):
    if context.org_id not in context.allowed_org_ids:
        raise HTTPException(403, "Select an allowed organisation before creating a cost pool")
    return save(db, InventoryCostPool(**payload.model_dump(), org_id=context.org_id, created_by=user.id), CostPoolRead)


@CostPoolRouter.get("/branches/{branch_id}/cost-pool", response_model=BranchCostPoolRead | None)
def get_branch_cost_pool(branch_id: int, db: Session = Depends(get_db),
                         context: OrgContext = Depends(get_org_context),
                         user=Depends(require_permission("View_Product"))):
    branch = scoped_branch(db, context, branch_id)
    row = db.query(BranchCostPool).filter(BranchCostPool.branch_id == branch.id,
        BranchCostPool.org_id == branch.org_id, BranchCostPool.is_deleted == False).first()
    return BranchCostPoolRead.model_validate(row) if row else None


@CostPoolRouter.put("/branches/{branch_id}/cost-pool", response_model=BranchCostPoolRead)
def assign_branch_cost_pool(branch_id: int, payload: BranchCostPoolAssign, db: Session = Depends(get_db),
                            context: OrgContext = Depends(get_org_context),
                            user=Depends(require_permission("Manage_InventoryCostPool"))):
    # Serialize initial assignments on an existing branch row, including retries
    # when no binding yet exists. Future posting must use the same lock boundary.
    try:
        query = db.query(InventoryBranch).filter(InventoryBranch.id == branch_id, InventoryBranch.is_deleted == False)
        branch = apply_org_filter(query, InventoryBranch, context).populate_existing().with_for_update().first()
        if branch is None:
            raise HTTPException(404, "Branch not found")
        pool = db.query(InventoryCostPool).filter(InventoryCostPool.id == payload.cost_pool_id,
            InventoryCostPool.org_id == branch.org_id, InventoryCostPool.is_deleted == False).with_for_update().first()
        if pool is None:
            raise HTTPException(404, "Cost pool not found in this organisation")
        if not branch.is_active or not pool.is_active:
            raise HTTPException(409, "Use an active branch and cost pool")
        row = db.query(BranchCostPool).filter(BranchCostPool.branch_id == branch.id,
            BranchCostPool.org_id == branch.org_id, BranchCostPool.is_deleted == False).first()
        if row:
            if row.cost_pool_id != pool.id:
                raise HTTPException(409, "Cost pool already assigned; reassignment requires an audited cutover and is not available yet")
            result = BranchCostPoolRead.model_validate(row)
            db.commit()
            return result
        return save(db, BranchCostPool(org_id=branch.org_id, branch_id=branch.id,
            cost_pool_id=pool.id, created_by=user.id), BranchCostPoolRead)
    except Exception:
        db.rollback()
        raise
