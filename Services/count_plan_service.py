"""Cycle-count planning and scope (T33A). Creates count records only.

Plans and their product-location scope are editable while DRAFT and frozen once
ACTIVE, so an assignment can never be re-aimed at different shelves after a
counter has started. No stock is read, posted or valued here.
"""
from datetime import date
from uuid import UUID

from Model.containermgmt.Inventory.CycleCount import CountPlan, CountScope, CountSession, CountEntry
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Orders.Product import Product
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.policy_activation_service import active_policy
from Utils.org_filter import apply_org_filter


def owned(db, model, context):
    return apply_org_filter(db.query(model).filter_by(org_id=context.org_id, is_deleted=False), model, context)


def _scope(context):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Count plan company scope denied')


def locked_plan(db, context, plan_key, *, for_update=True):
    query = owned(db, CountPlan, context).filter_by(plan_key=plan_key)
    row = (query.with_for_update() if for_update else query).one_or_none()
    if row is None:
        raise LookupError('Count plan not found')
    return row


def create_plan(factory, context, actor_id, operation_key, payload, *, authorize):
    if not callable(authorize):
        raise ValueError('Count plan permission guard required')

    def effect(db):
        authorize(db)
        _scope(context)
        branch = apply_org_filter(db.query(InventoryBranch).filter_by(
            id=payload.branch_id, org_id=context.org_id, is_deleted=False, is_active=True),
            InventoryBranch, context).one_or_none()
        if branch is None:
            raise LookupError('Counting branch not found')
        if owned(db, CountPlan, context).filter_by(branch_id=branch.id, code=payload.code).first():
            raise PostingConflict('A plan with this code already exists in the branch')
        row = CountPlan(org_id=context.org_id, plan_key=operation_key, branch_id=branch.id,
                        code=payload.code, name=payload.name, year=payload.year,
                        state='DRAFT', created_by=actor_id)
        db.add(row)
        db.flush()
        result = dict(plan_key=str(operation_key), id=row.id, state='DRAFT')
        return PostingEffect(result, dict(kind='inventory.count.plan.created', **result))

    return execute_once(factory, context, actor_id, operation_key, 'inventory.count.plan.create.v1',
                        dict(branch_id=payload.branch_id, code=payload.code, year=payload.year),
                        effect, authorize=lambda db: authorize(db))


def save_scope(factory, context, actor_id, operation_key, plan_key, payload, *, authorize):
    """Replace a DRAFT plan's scope with the exact supplied lines."""
    if not callable(authorize):
        raise ValueError('Count plan permission guard required')

    def effect(db):
        authorize(db)
        _scope(context)
        plan = locked_plan(db, context, plan_key)
        if plan.state != payload.expected_state:
            raise PostingConflict('Plan state changed; reload before saving scope')
        if plan.state != 'DRAFT':
            raise PostingConflict('Only a draft plan may have its scope changed')

        product_ids = sorted({line.product_id for line in payload.lines})
        location_ids = sorted({line.location_id for line in payload.lines})
        products = {row.id for row in apply_org_filter(db.query(Product.id).filter(
            Product.org_id == context.org_id, Product.id.in_(product_ids),
            Product.is_deleted.is_(False), Product.status == 'active'), Product, context).all()}
        if len(products) != len(product_ids):
            raise LookupError('Count scope product not found')
        locations = {row.id for row in apply_org_filter(db.query(StockLocation.id).filter(
            StockLocation.org_id == context.org_id, StockLocation.branch_id == plan.branch_id,
            StockLocation.id.in_(location_ids), StockLocation.is_active.is_(True),
            StockLocation.is_deleted.is_(False)), StockLocation, context).all()}
        if len(locations) != len(location_ids):
            raise LookupError('Count scope location not found in this branch')
        # A counted quantity has no meaning without a reviewed unit policy.
        for product_id in product_ids:
            if active_policy(db, context, product_id) is None:
                raise PostingConflict('Every counted product needs a reviewed inventory policy')

        existing = owned(db, CountScope, context).filter_by(plan_id=plan.id).all()
        for row in existing:
            db.delete(row)
        db.flush()
        for line in payload.lines:
            db.add(CountScope(org_id=context.org_id, plan_id=plan.id, product_id=line.product_id,
                              branch_id=plan.branch_id, location_id=line.location_id,
                              cadence=line.cadence, due_on=line.due_on, created_by=actor_id))
        db.flush()
        result = dict(plan_key=str(plan_key), scope_lines=len(payload.lines), state=plan.state)
        return PostingEffect(result, dict(kind='inventory.count.scope.saved', **result))

    return execute_once(factory, context, actor_id, operation_key, 'inventory.count.scope.save.v1',
                        dict(plan_key=str(plan_key), lines=[line.model_dump(mode='json') for line in payload.lines]),
                        effect, authorize=lambda db: authorize(db))


def activate_plan(factory, context, actor_id, operation_key, plan_key, payload, *, authorize):
    if not callable(authorize):
        raise ValueError('Count plan permission guard required')

    def effect(db):
        authorize(db)
        _scope(context)
        plan = locked_plan(db, context, plan_key)
        if plan.state != payload.expected_state:
            raise PostingConflict('Plan state changed; reload before activating')
        if not owned(db, CountScope, context).filter_by(plan_id=plan.id).first():
            raise PostingConflict('Add at least one product and location before activating')
        plan.state = 'ACTIVE'
        plan.updated_by = actor_id
        db.flush()
        result = dict(plan_key=str(plan_key), state='ACTIVE')
        return PostingEffect(result, dict(kind='inventory.count.plan.activated', **result))

    return execute_once(factory, context, actor_id, operation_key, 'inventory.count.plan.activate.v1',
                        dict(plan_key=str(plan_key)), effect, authorize=lambda db: authorize(db))


def plan_coverage(db, context, plan_key, *, authorize):
    """Annual coverage per location: scoped lines versus lines counted at least once.

    A query over the scope and submitted rounds, not a second store.
    """
    if not callable(authorize):
        raise ValueError('Count plan permission guard required')
    authorize(db)
    _scope(context)
    plan = locked_plan(db, context, plan_key, for_update=False)
    scopes = owned(db, CountScope, context).filter_by(plan_id=plan.id).all()
    counted = set()
    sessions = owned(db, CountSession, context).filter(
        CountSession.plan_id == plan.id, CountSession.state.in_(('SUBMITTED', 'REVIEWED'))).all()
    if sessions:
        rows = owned(db, CountEntry, context).filter(
            CountEntry.session_id.in_([row.id for row in sessions])).with_entities(
                CountEntry.product_id, CountEntry.location_id).distinct().all()
        counted = {(row.product_id, row.location_id) for row in rows}
    names = {row.id: row.name for row in apply_org_filter(db.query(StockLocation.id, StockLocation.name).filter(
        StockLocation.org_id == context.org_id, StockLocation.branch_id == plan.branch_id),
        StockLocation, context).all()}
    buckets = {}
    for row in scopes:
        bucket = buckets.setdefault(row.location_id, dict(
            location_id=row.location_id, location_name=names.get(row.location_id),
            scope_lines=0, counted_lines=0, outstanding_lines=0, next_due_on=None))
        bucket['scope_lines'] += 1
        if (row.product_id, row.location_id) in counted:
            bucket['counted_lines'] += 1
        else:
            bucket['outstanding_lines'] += 1
            if bucket['next_due_on'] is None or row.due_on < bucket['next_due_on']:
                bucket['next_due_on'] = row.due_on
    return sorted(buckets.values(), key=lambda item: (item['next_due_on'] or date.max, item['location_id']))
