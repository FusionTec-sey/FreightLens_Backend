"""Blind counting rounds (T33A). Counting records what was seen; it posts nothing.

The blind rule is enforced here, not in the client: `blind_sheet` returns product
identity, location, unit and step only. Expected stock is read for the first time
at submission, and the difference it produces is explicitly provisional because
stock can move before anyone reviews it.
"""
from decimal import Decimal
from datetime import datetime, timezone
from uuid import UUID

from Model.containermgmt.Inventory.CycleCount import (CountPlan, CountScope, CountSession,
                                                      CountEntry, CountDiscrepancy)
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Orders.Product import Product
from Model.Credentials.users import User
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.inventory_unit_service import convert_quantity
from Services.policy_activation_service import active_policy
from Services.count_plan_service import owned, locked_plan
from Utils.org_filter import apply_org_filter

OPEN_STATES = ('ASSIGNED', 'IN_PROGRESS')


def eligible_counter(db, context, assignee_id):
    """Use identical company membership validation for assignment and recount."""
    _scope(context)
    row = db.query(User).filter(User.id == assignee_id, User.is_deleted.is_(False)).one_or_none()
    if row is None:
        raise LookupError('Assigned counter not found')
    if context.org_id not in set(row.allowed_org_ids or []) | {row.org_id}:
        raise PermissionError('Assign a counter from this company')
    return row


def _scope(context):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Count session company scope denied')


def locked_session(db, context, session_key, *, for_update=True):
    query = owned(db, CountSession, context).filter_by(session_key=session_key)
    row = (query.with_for_update() if for_update else query).one_or_none()
    if row is None:
        raise LookupError('Count session not found')
    return row


def assign_session(factory, context, actor_id, operation_key, payload, *, authorize):
    if not callable(authorize):
        raise ValueError('Count assignment permission guard required')

    def effect(db):
        authorize(db)
        _scope(context)
        plan = locked_plan(db, context, payload.plan_key)
        if plan.state != 'ACTIVE':
            raise PostingConflict('Only an active plan can be assigned')
        scope_lines = owned(db, CountScope, context).filter_by(
            plan_id=plan.id, location_id=payload.location_id).count()
        if not scope_lines:
            raise LookupError('This location is not in the plan scope')
        assignee = eligible_counter(db, context, payload.assignee_id)
        open_round = owned(db, CountSession, context).filter(
            CountSession.plan_id == plan.id, CountSession.location_id == payload.location_id,
            CountSession.state.in_(OPEN_STATES)).first()
        if open_round is not None:
            raise PostingConflict('An open round already exists for this location')
        row = CountSession(org_id=context.org_id, session_key=operation_key, plan_id=plan.id,
                           branch_id=plan.branch_id, location_id=payload.location_id,
                           assignee_id=assignee.id, state='ASSIGNED', round=1, created_by=actor_id)
        db.add(row)
        db.flush()
        result = dict(session_key=str(operation_key), id=row.id, state='ASSIGNED', round=1)
        return PostingEffect(result, dict(kind='inventory.count.session.assigned', **result))

    return execute_once(factory, context, actor_id, operation_key, 'inventory.count.session.assign.v1',
                        dict(plan_key=str(payload.plan_key), location_id=payload.location_id,
                             assignee_id=payload.assignee_id), effect, authorize=lambda db: authorize(db))


def blind_sheet(db, context, session_key, actor_id, *, authorize):
    """The counter's sheet. No expected quantity, no earlier round, no value."""
    if not callable(authorize):
        raise ValueError('Count entry permission guard required')
    authorize(db)
    _scope(context)
    session = locked_session(db, context, session_key, for_update=False)
    if session.assignee_id != actor_id:
        raise PermissionError('A count sheet is only available to its assigned counter')
    scopes = owned(db, CountScope, context).filter_by(
        plan_id=session.plan_id, location_id=session.location_id).all()
    entered = {row.product_id for row in owned(db, CountEntry, context).filter_by(
        session_id=session.id).with_entities(CountEntry.product_id).all()}
    labels = {row.id: row for row in apply_org_filter(db.query(Product.id, Product.name, Product.sku).filter(
        Product.org_id == context.org_id, Product.id.in_([row.product_id for row in scopes] or [0])),
        Product, context).all()}
    location = apply_org_filter(db.query(StockLocation).filter_by(
        id=session.location_id, org_id=context.org_id), StockLocation, context).one_or_none()
    lines = []
    for row in scopes:
        policy = active_policy(db, context, row.product_id)
        if policy is None:
            continue
        config = InventoryPolicyConfig.model_validate(policy.config)
        label = labels.get(row.product_id)
        lines.append(dict(product_id=row.product_id,
                          product_name=label.name if label else None,
                          sku=label.sku if label else None,
                          location_id=row.location_id,
                          location_name=location.name if location else None,
                          base_unit=config.base_unit, quantity_step=str(config.quantity_step),
                          units=[config.base_unit] + [unit.unit for unit in config.conversions],
                          entered=row.product_id in entered))
    return dict(session_key=str(session.session_key), state=session.state, round=session.round,
                location_id=session.location_id,
                location_name=location.name if location else None, lines=lines)


def save_entries(factory, context, actor_id, operation_key, session_key, payload, *, authorize):
    """Append immutable counted lines. A correction is a recount round, not an edit."""
    if not callable(authorize):
        raise ValueError('Count entry permission guard required')

    def effect(db):
        authorize(db)
        _scope(context)
        session = locked_session(db, context, session_key)
        if session.assignee_id != actor_id:
            raise PermissionError('Only the assigned counter may enter this round')
        if session.state not in OPEN_STATES:
            raise PostingConflict('This round is closed; open a recount to count again')
        scopes = {(row.product_id, row.location_id): row for row in owned(db, CountScope, context).filter_by(
            plan_id=session.plan_id, location_id=session.location_id).all()}
        existing = {row.product_id for row in owned(db, CountEntry, context).filter_by(
            session_id=session.id).with_entities(CountEntry.product_id).all()}
        for entry in payload.entries:
            if (entry.product_id, entry.location_id) not in scopes:
                raise LookupError('Counted line is not in this round')
            if entry.product_id in existing:
                raise PostingConflict('This product was already counted in this round')
            policy = active_policy(db, context, entry.product_id)
            if policy is None:
                raise PostingConflict('Reviewed inventory policy missing for a counted product')
            config = InventoryPolicyConfig.model_validate(policy.config)
            quantity = Decimal(entry.quantity)
            base = (Decimal('0') if quantity == 0
                    else convert_quantity(config, quantity, entry.unit))
            db.add(CountEntry(org_id=context.org_id, session_id=session.id,
                              product_id=entry.product_id, branch_id=session.branch_id,
                              location_id=entry.location_id, counted_quantity=quantity,
                              unit=entry.unit, base_quantity=base, base_unit=config.base_unit,
                              policy=config.model_dump(mode='json'),
                              operation_key=operation_key, created_by=actor_id))
        if session.state == 'ASSIGNED':
            session.state = 'IN_PROGRESS'
        session.updated_by = actor_id
        db.flush()
        entered = owned(db, CountEntry, context).filter_by(session_id=session.id).count()
        result = dict(session_key=str(session_key), entered_lines=entered, state='IN_PROGRESS')
        return PostingEffect(result, dict(kind='inventory.count.entries.saved',
                                          session_key=str(session_key), entered_lines=entered))

    return execute_once(factory, context, actor_id, operation_key, 'inventory.count.entries.save.v1',
                        dict(session_key=str(session_key),
                             entries=[entry.model_dump(mode='json') for entry in payload.entries]),
                        effect, authorize=lambda db: authorize(db))


def submit_session(factory, context, actor_id, operation_key, session_key, payload, *, authorize):
    """Close the round and capture provisional differences against current stock."""
    if not callable(authorize):
        raise ValueError('Count entry permission guard required')

    def effect(db):
        authorize(db)
        _scope(context)
        session = locked_session(db, context, session_key)
        if session.assignee_id != actor_id:
            raise PermissionError('Only the assigned counter may submit this round')
        if session.state not in OPEN_STATES:
            raise PostingConflict('This round has already been submitted')
        entries = owned(db, CountEntry, context).filter_by(session_id=session.id).all()
        if len(entries) != payload.expected_entered_lines:
            raise PostingConflict('Counted lines changed; reload the sheet before submitting')
        scope_lines = owned(db, CountScope, context).filter_by(
            plan_id=session.plan_id, location_id=session.location_id).count()
        if len(entries) != scope_lines:
            raise PostingConflict('Count every line in this round before submitting')

        # Expected stock is read here for the first time, and only to record a
        # provisional difference. No balance is locked, changed, valued or posted.
        balances = {}
        for row in apply_org_filter(db.query(StockBalance).filter(
                StockBalance.org_id == context.org_id, StockBalance.branch_id == session.branch_id,
                StockBalance.location_id == session.location_id, StockBalance.is_deleted.is_(False),
                StockBalance.product_id.in_([entry.product_id for entry in entries])),
                StockBalance, context).all():
            bucket = balances.setdefault(row.product_id, dict(quantity=Decimal('0'), version=row.version))
            bucket['quantity'] += row.on_hand
        differences = 0
        for entry in entries:
            bucket = balances.get(entry.product_id, dict(quantity=Decimal('0'), version=None))
            expected = bucket['quantity']
            difference = entry.base_quantity - expected
            if difference != 0:
                differences += 1
            db.add(CountDiscrepancy(org_id=context.org_id, session_id=session.id,
                                    product_id=entry.product_id,
                                    location_id=entry.location_id, counted_base=entry.base_quantity,
                                    expected_base=expected, difference_base=difference,
                                    base_unit=entry.base_unit, balance_version=bucket['version'],
                                    created_by=actor_id))
        session.state = 'SUBMITTED'
        session.submitted_at = datetime.now(timezone.utc)
        session.updated_by = actor_id
        db.flush()
        result = dict(session_key=str(session_key), state='SUBMITTED', discrepancy_lines=differences)
        return PostingEffect(result, dict(kind='inventory.count.session.submitted', **result))

    return execute_once(factory, context, actor_id, operation_key, 'inventory.count.session.submit.v1',
                        dict(session_key=str(session_key),
                             expected_entered_lines=payload.expected_entered_lines),
                        effect, authorize=lambda db: authorize(db))


def open_recount(factory, context, actor_id, operation_key, session_key, payload, *, authorize):
    """Open the next immutable round. Earlier rounds and entries are untouched."""
    if not callable(authorize):
        raise ValueError('Count assignment permission guard required')

    def effect(db):
        authorize(db)
        _scope(context)
        parent = locked_session(db, context, session_key)
        if parent.state not in ('SUBMITTED', 'REVIEWED'):
            raise PostingConflict('Only a submitted round can be recounted')
        if owned(db, CountSession, context).filter(
                CountSession.parent_session_id == parent.id,
                CountSession.state.in_(OPEN_STATES)).first():
            raise PostingConflict('A recount round is already open')
        assignee = eligible_counter(db, context, payload.assignee_id)
        row = CountSession(org_id=context.org_id, session_key=operation_key, plan_id=parent.plan_id,
                           branch_id=parent.branch_id, location_id=parent.location_id,
                           assignee_id=assignee.id, state='ASSIGNED', round=parent.round + 1,
                           parent_session_id=parent.id, created_by=actor_id)
        db.add(row)
        db.flush()
        result = dict(session_key=str(operation_key), id=row.id, state='ASSIGNED', round=row.round)
        return PostingEffect(result, dict(kind='inventory.count.session.recount', **result))

    return execute_once(factory, context, actor_id, operation_key, 'inventory.count.session.recount.v1',
                        dict(session_key=str(session_key), assignee_id=payload.assignee_id,
                             reason=payload.reason), effect, authorize=lambda db: authorize(db))
