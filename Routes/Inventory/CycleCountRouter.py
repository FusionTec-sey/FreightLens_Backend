"""Cycle-count planning, blind entry and discrepancy review (T33A).

Count records only: no endpoint here adjusts, freezes, values or reconciles
stock. The blind sheet is a separate projection from the discrepancy reads, so a
counter holding only Enter_CountResult can never see expected stock.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Model.db import get_db
from Model.containermgmt.Inventory.CycleCount import (CountPlan, CountScope, CountSession,
                                                      CountEntry, CountDiscrepancy)
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Orders.Product import Product
from Model.Credentials.users import User
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.InventoryLocationSchema import LocationPage
from Schema.SalesSourceSchema import SalesBranchChoice, SalesProductChoice
from Services.product_choice_service import product_choices
from Schema.CycleCountSchema import (CountPlanCreate, CountPlanRead, CountScopeSave, CountPlanActivate,
                                     CountCoverageRow, CountSessionCreate, CountSessionRead,
                                     BlindSheetRead, CountEntrySave, CountEntrySaved, CountSubmit,
                                     CountSubmitted, CountRecount, DiscrepancyRead,
                                     DiscrepancyReviewRequest, DiscrepancyDecision, DiscrepancyDecided)
from Schema.ManagerCaseSchema import CaseActionRead
from Services.inventory_posting_service import PostingConflict
from Services import count_plan_service as plans
from Services import count_session_service as sessions
from Services import count_discrepancy_service as reviews
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context, get_current_user
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import require_permission

CycleCountRouter = APIRouter(prefix='/inventory/counts', tags=['Cycle counts'],
                             dependencies=[Depends(require_module('INVENTORY'))])


def translate(error):
    if isinstance(error, LookupError):
        return HTTPException(404, str(error) or 'Count record not found')
    if isinstance(error, PermissionError):
        return HTTPException(403, str(error))
    if isinstance(error, PostingConflict):
        return HTTPException(409, str(error))
    if isinstance(error, ValueError):
        return HTTPException(422, str(error))
    return error


def guard(policy: AccessPolicy, permission: str):
    def check(db):
        if not policy.has(permission):
            raise PermissionError(f'{permission} is required')
    return check


def allowed(context: OrgContext):
    if context.org_id not in context.allowed_org_ids:
        raise HTTPException(403, 'Select an allowed company')


def page_of(items, total, page, limit):
    return dict(items=items, total=total, page=page, limit=limit,
                pages=max(1, (total + limit - 1) // limit))


@CycleCountRouter.get('/sources/branches', response_model=LocationPage[SalesBranchChoice])
def count_branches(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                   db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                   user=Depends(require_permission('Manage_CountPlan'))):
    allowed(context)
    query = plans.owned(db, InventoryBranch, context).filter(InventoryBranch.is_active.is_(True))
    total = query.count()
    rows = query.order_by(InventoryBranch.name, InventoryBranch.id).offset((page - 1) * limit).limit(limit).all()
    return page_of([dict(id=row.id, code=row.code, name=row.name) for row in rows], total, page, limit)


@CycleCountRouter.get('/sources/products', response_model=LocationPage[SalesProductChoice])
def count_products(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                   search: str = Query('', max_length=160), db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context),
                   policy: AccessPolicy = Depends(get_request_policy),
                   user=Depends(require_permission('Manage_CountPlan'))):
    allowed(context)
    return product_choices(db, context, page, limit, search, authorize=guard(policy, 'Manage_CountPlan'))


@CycleCountRouter.get('/sources/branches/{branch_id}/locations', response_model=LocationPage[SalesBranchChoice])
def count_locations(branch_id: int, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                    db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                    policy: AccessPolicy = Depends(get_request_policy)):
    allowed(context)
    if not (policy.has('Manage_CountPlan') or policy.has('Assign_CountSession')):
        raise HTTPException(403, 'Count planning or assignment access required')
    if not plans.owned(db, InventoryBranch, context).filter_by(id=branch_id, is_active=True).first():
        raise HTTPException(404, 'Counting branch not found')
    query = plans.owned(db, StockLocation, context).filter_by(branch_id=branch_id, is_active=True)
    total = query.count()
    rows = query.order_by(StockLocation.name, StockLocation.id).offset((page - 1) * limit).limit(limit).all()
    return page_of([dict(id=row.id, code=row.code, name=row.name) for row in rows], total, page, limit)


# ── Plans and scope ──────────────────────────────────────────────────────────

@CycleCountRouter.get('/plans', response_model=LocationPage[CountPlanRead])
def list_plans(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
               db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
               user=Depends(require_permission('View_CountPlan'))):
    allowed(context)
    query = plans.owned(db, CountPlan, context)
    total = query.count()
    rows = query.order_by(CountPlan.year.desc(), CountPlan.code).offset((page - 1) * limit).limit(limit).all()
    branches = {row.id: row.name for row in apply_org_filter(
        db.query(InventoryBranch.id, InventoryBranch.name).filter(
            InventoryBranch.org_id == context.org_id), InventoryBranch, context).all()}
    counts = {}
    if rows:
        for row in plans.owned(db, CountScope, context).filter(
                CountScope.plan_id.in_([item.id for item in rows])).all():
            counts[row.plan_id] = counts.get(row.plan_id, 0) + 1
    items = [dict(plan_key=row.plan_key, id=row.id, branch_id=row.branch_id,
                  branch_name=branches.get(row.branch_id), code=row.code, name=row.name,
                  year=row.year, state=row.state, scope_lines=counts.get(row.id, 0),
                  created_at=row.created_at) for row in rows]
    return page_of(items, total, page, limit)


@CycleCountRouter.post('/plans', response_model=dict)
def create_plan(payload: CountPlanCreate, db: Session = Depends(get_db),
                context: OrgContext = Depends(get_org_context),
                policy: AccessPolicy = Depends(get_request_policy),
                user=Depends(require_permission('Manage_CountPlan'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = plans.create_plan(db, context, user.id, payload.operation_key, payload,
                                   authorize=guard(policy, 'Manage_CountPlan'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@CycleCountRouter.put('/plans/{key}/scope', response_model=dict)
def save_scope(key: UUID, payload: CountScopeSave, db: Session = Depends(get_db),
               context: OrgContext = Depends(get_org_context),
               policy: AccessPolicy = Depends(get_request_policy),
               user=Depends(require_permission('Manage_CountPlan'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = plans.save_scope(db, context, user.id, payload.operation_key, key, payload,
                                  authorize=guard(policy, 'Manage_CountPlan'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@CycleCountRouter.post('/plans/{key}/activate', response_model=dict)
def activate_plan(key: UUID, payload: CountPlanActivate, db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context),
                  policy: AccessPolicy = Depends(get_request_policy),
                  user=Depends(require_permission('Manage_CountPlan'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = plans.activate_plan(db, context, user.id, payload.operation_key, key, payload,
                                     authorize=guard(policy, 'Manage_CountPlan'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@CycleCountRouter.get('/plans/{key}/coverage', response_model=list[CountCoverageRow])
def plan_coverage(key: UUID, db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context),
                  policy: AccessPolicy = Depends(get_request_policy),
                  user=Depends(require_permission('View_CountPlan'))):
    allowed(context)
    try:
        return plans.plan_coverage(db, context, key, authorize=guard(policy, 'View_CountPlan'))
    except Exception as error:
        raise translate(error) from error


# ── Sessions and blind entry ─────────────────────────────────────────────────

@CycleCountRouter.get('/sessions', response_model=LocationPage[CountSessionRead])
def list_sessions(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                  mine: bool = Query(False), db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context),
                  policy: AccessPolicy = Depends(get_request_policy),
                  user=Depends(get_current_user)):
    allowed(context)
    manages = policy.has('Assign_CountSession') or policy.has('View_CountPlan')
    counts = policy.has('Enter_CountResult')
    if not manages and not counts:
        raise HTTPException(403, 'Count session access required')
    query = plans.owned(db, CountSession, context)
    # A counter only ever sees their own assignments.
    if mine or not manages:
        query = query.filter(CountSession.assignee_id == user.id)
    total = query.count()
    rows = query.order_by(CountSession.id.desc()).offset((page - 1) * limit).limit(limit).all()
    plan_rows = {row.id: row for row in plans.owned(db, CountPlan, context).filter(
        CountPlan.id.in_([row.plan_id for row in rows] or [0])).all()}
    locations = {row.id: row.name for row in apply_org_filter(
        db.query(StockLocation.id, StockLocation.name).filter(
            StockLocation.org_id == context.org_id), StockLocation, context).all()}
    people = {row.id: row.username for row in db.query(User.id, User.username).filter(
        User.id.in_([row.assignee_id for row in rows] or [0])).all()}
    expected, entered = {}, {}
    for row in rows:
        expected[row.id] = plans.owned(db, CountScope, context).filter_by(
            plan_id=row.plan_id, location_id=row.location_id).count()
        entered[row.id] = plans.owned(db, CountEntry, context).filter_by(session_id=row.id).count()
    items = [dict(session_key=row.session_key, id=row.id,
                  plan_key=plan_rows[row.plan_id].plan_key if row.plan_id in plan_rows else None,
                  plan_code=plan_rows[row.plan_id].code if row.plan_id in plan_rows else None,
                  branch_id=row.branch_id, location_id=row.location_id,
                  location_name=locations.get(row.location_id), assignee_id=row.assignee_id,
                  assignee_name=people.get(row.assignee_id), state=row.state, round=row.round,
                  expected_lines=expected.get(row.id, 0), entered_lines=entered.get(row.id, 0),
                  submitted_at=row.submitted_at) for row in rows]
    return page_of(items, total, page, limit)


@CycleCountRouter.post('/sessions', response_model=dict)
def assign_session(payload: CountSessionCreate, db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context),
                   policy: AccessPolicy = Depends(get_request_policy),
                   user=Depends(require_permission('Assign_CountSession'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = sessions.assign_session(db, context, user.id, payload.operation_key, payload,
                                         authorize=guard(policy, 'Assign_CountSession'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@CycleCountRouter.get('/sessions/{key}/sheet', response_model=BlindSheetRead)
def blind_sheet(key: UUID, db: Session = Depends(get_db),
                context: OrgContext = Depends(get_org_context),
                policy: AccessPolicy = Depends(get_request_policy),
                user=Depends(require_permission('Enter_CountResult'))):
    allowed(context)
    try:
        return sessions.blind_sheet(db, context, key, user.id,
                                    authorize=guard(policy, 'Enter_CountResult'))
    except Exception as error:
        raise translate(error) from error


@CycleCountRouter.put('/sessions/{key}/entries', response_model=CountEntrySaved)
def save_entries(key: UUID, payload: CountEntrySave, db: Session = Depends(get_db),
                 context: OrgContext = Depends(get_org_context),
                 policy: AccessPolicy = Depends(get_request_policy),
                 user=Depends(require_permission('Enter_CountResult'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = sessions.save_entries(db, context, user.id, payload.operation_key, key, payload,
                                       authorize=guard(policy, 'Enter_CountResult'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@CycleCountRouter.post('/sessions/{key}/submit', response_model=CountSubmitted)
def submit_session(key: UUID, payload: CountSubmit, db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context),
                   policy: AccessPolicy = Depends(get_request_policy),
                   user=Depends(require_permission('Enter_CountResult'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = sessions.submit_session(db, context, user.id, payload.operation_key, key, payload,
                                         authorize=guard(policy, 'Enter_CountResult'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@CycleCountRouter.post('/sessions/{key}/recount', response_model=dict)
def open_recount(key: UUID, payload: CountRecount, db: Session = Depends(get_db),
                 context: OrgContext = Depends(get_org_context),
                 policy: AccessPolicy = Depends(get_request_policy),
                 user=Depends(require_permission('Assign_CountSession'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = sessions.open_recount(db, context, user.id, payload.operation_key, key, payload,
                                       authorize=guard(policy, 'Assign_CountSession'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


# ── Provisional discrepancies and their review ───────────────────────────────

@CycleCountRouter.get('/discrepancies', response_model=LocationPage[DiscrepancyRead])
def list_discrepancies(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                       session_key: UUID | None = Query(None), db: Session = Depends(get_db),
                       context: OrgContext = Depends(get_org_context),
                       user=Depends(require_permission('View_CountDiscrepancy'))):
    allowed(context)
    query = plans.owned(db, CountDiscrepancy, context)
    session_rows = {row.id: row for row in plans.owned(db, CountSession, context).all()}
    if session_key is not None:
        matching = [row.id for row in session_rows.values() if row.session_key == session_key]
        query = query.filter(CountDiscrepancy.session_id.in_(matching or [0]))
    total = query.count()
    rows = query.order_by(CountDiscrepancy.id.desc()).offset((page - 1) * limit).limit(limit).all()
    decided = reviews.review_state(db, context, [row.id for row in rows])
    pending_cases = {}
    for case in plans.owned(db, ManagerCase, context).filter(
            ManagerCase.action == reviews.ACTION,
            ManagerCase.source_type == reviews.SOURCE_TYPE,
            ManagerCase.source_key.in_([str(row.id) for row in rows])).order_by(ManagerCase.id.desc()).all() if rows else []:
        pending_cases.setdefault(case.source_key, case.case_key)
    labels = {row.id: row for row in apply_org_filter(
        db.query(Product.id, Product.name, Product.sku).filter(
            Product.org_id == context.org_id,
            Product.id.in_([row.product_id for row in rows] or [0])), Product, context).all()}
    locations = {row.id: row.name for row in apply_org_filter(
        db.query(StockLocation.id, StockLocation.name).filter(
            StockLocation.org_id == context.org_id), StockLocation, context).all()}
    items = []
    for row in rows:
        session = session_rows.get(row.session_id)
        review = decided.get(row.id)
        label = labels.get(row.product_id)
        items.append(dict(id=row.id,
                          session_key=session.session_key if session else None,
                          round=session.round if session else 1,
                          product_id=row.product_id,
                          product_name=label.name if label else None,
                          sku=label.sku if label else None,
                          location_id=row.location_id,
                          location_name=locations.get(row.location_id),
                          counted_base=format(row.counted_base, 'f'),
                          expected_base=format(row.expected_base, 'f'),
                          difference_base=format(row.difference_base, 'f'),
                          base_unit=row.base_unit,
                          state='REVIEWED' if review else 'PROVISIONAL',
                          outcome=review.outcome if review else None,
                          case_key=review.case_key if review else pending_cases.get(str(row.id))))
    return page_of(items, total, page, limit)


@CycleCountRouter.post('/discrepancies/{discrepancy_id}/review', response_model=CaseActionRead)
def request_review(discrepancy_id: int, payload: DiscrepancyReviewRequest,
                   db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                   policy: AccessPolicy = Depends(get_request_policy),
                   user=Depends(require_permission('View_CountDiscrepancy'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = reviews.request_discrepancy_review(db, context, user.id, payload.operation_key,
                                                    discrepancy_id, payload,
                                                    authorize=guard(policy, 'View_CountDiscrepancy'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error


@CycleCountRouter.post('/discrepancies/{discrepancy_id}/decision', response_model=DiscrepancyDecided)
def decide_review(discrepancy_id: int, payload: DiscrepancyDecision,
                  db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                  policy: AccessPolicy = Depends(get_request_policy),
                  user=Depends(require_permission('Review_CountDiscrepancy'))):
    allowed(context)
    try:
        if not db.in_transaction():
            db.begin()
        result = reviews.decide_discrepancy(db, context, user.id, payload.operation_key,
                                            discrepancy_id, payload,
                                            authorize=guard(policy, 'Review_CountDiscrepancy'))
        db.commit()
        return dict(discrepancy_id=discrepancy_id, outcome=payload.outcome, state='REVIEWED',
                    replayed=result.replayed)
    except Exception as error:
        db.rollback()
        raise translate(error) from error
