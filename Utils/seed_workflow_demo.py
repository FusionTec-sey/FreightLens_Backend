"""Explicit local-only Sales/Counts examples. Never run during startup.

Requires the existing T05 synthetic company. Does not open/change stock, create
payments, grant roles, enable runtime writers or alter another company's records.
All workflow changes commit together; subsequent runs preserve user edits.
"""
import argparse
import os
from datetime import date
from uuid import UUID, uuid5
from sqlalchemy import text
from Model.db import engine, SessionLocal
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.CycleCount import CountPlan, CountSession, CountDiscrepancy
from Schema.CustomerSchema import CustomerIdentityInput
from Schema.SalesIntentSchema import SalesIntentInput
from Schema.CycleCountSchema import (CountPlanCreate, CountScopeSave, CountScopeLine,
    CountPlanActivate, CountSessionCreate, CountEntrySave, CountSubmit,
    DiscrepancyReviewRequest)
from Services.customer_identity_service import create_customer
from Services.sales_intent_service import save_sales_intent
from Services.policy_activation_service import active_policy
from Services.count_plan_service import create_plan, save_scope, activate_plan
from Services.count_session_service import assign_session, save_entries, submit_session
from Services.count_discrepancy_service import request_discrepancy_review
from Utils.org_filter import OrgContext
from Utils.seed_t05_demo import NAME, CODE

NAMESPACE = UUID('6bc88292-4b84-4e68-abda-ad613e04c920')


def seed_workflows(db, viewer_id):
    database = db.bind.url.database or ''
    if database != 'freightlens_pos_preview' and not (
            os.getenv('ENVIRONMENT') == 'test' and database.endswith('_test')):
        raise ValueError('Workflow examples require local preview or isolated test database')
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('freightlens-workflow-demo-v1', 0))"))
    demo = db.query(Organisation).filter_by(name=NAME, code=CODE, is_active=True).one()
    viewer = db.query(User).filter_by(id=viewer_id, is_deleted=False).one()
    if demo.id not in set(viewer.allowed_org_ids or []) | {viewer.org_id}:
        raise PermissionError('Viewer must already have access to the demo company')
    context = OrgContext(current_org_id=demo.id, allowed_org_ids=[demo.id],
                         selected_org_id=demo.id, is_root=False)
    key = lambda label: uuid5(NAMESPACE, f'{demo.id}:{label}')
    summary = dict(org_id=demo.id, customers=2, drafts=3, plans=3, rounds=2,
                   open_round=str(key('round-open')), submitted_round=str(key('round-submitted')))
    if db.query(CountPlan.id).filter_by(org_id=demo.id, plan_key=key('plan-draft')).first():
        return dict(summary, created=False)
    requestor = db.query(User).filter_by(org_id=demo.id, username='demo-t05-requestor', is_deleted=False).one()
    branch = db.query(InventoryBranch).filter_by(org_id=demo.id, code='DEMO-STORE', is_deleted=False, is_active=True).one()
    location = db.query(StockLocation).filter_by(org_id=demo.id, branch_id=branch.id, code='DEMO-SITE', is_deleted=False).one()
    products = db.query(Product).filter(Product.org_id == demo.id,
        Product.sku.in_(['DEMO-EXTENDED', 'DEMO-EXTENSION']), Product.is_deleted.is_(False)).order_by(Product.sku).all()
    if len(products) != 2:
        raise ValueError('Existing T05 training products required')
    policies = [active_policy(db, context, product.id) for product in products]
    if any(policy is None or policy.config['base_unit'] != 'PCS' for policy in policies):
        raise ValueError('Expected reviewed PCS demo policies required')

    def guard(session):
        # CLI-only scope guard: no client-supplied company or production adapters.
        if context.org_id != demo.id or demo.name != NAME or demo.code != CODE:
            raise PermissionError('Demo workflow scope changed')

    demo.modules = list(dict.fromkeys([*(demo.modules or []), 'INVENTORY', 'SALES']))
    for index, label in enumerate(('Home renovation', 'Trade contractor')):
        create_customer(db, context, requestor.id, key(f'customer-{index}'),
            CustomerIdentityInput(name=f'DEMO ONLY - {label}', kind='PERSON' if index == 0 else 'BUSINESS',
                contacts=[dict(kind='EMAIL', value=f'workflow-{index}@example.invalid',
                               primary=True, label='Synthetic - never send')]),
            expected_version=0, authorize=guard)
    for index in range(3):
        payload = SalesIntentInput(customer_key=key(f'customer-{index % 2}'),
            expected_customer_version=1, branch_id=branch.id,
            lines=[dict(line_key=key(f'line-{index}-{position}'), product_id=product.id,
                        expected_policy_version=policy.version, quantity=str(index + 2), unit='PCS')
                   for position, (product, policy) in enumerate(zip(products, policies))])
        save_sales_intent(db, context, requestor.id, key(f'save-{index}-1'), key(f'draft-{index}'),
                          payload, expected_version=0, authorize=guard)
        if index == 0:
            revised = payload.model_copy(deep=True)
            revised.lines[0].quantity = '5'
            save_sales_intent(db, context, requestor.id, key('save-0-2'), key('draft-0'),
                              revised, expected_version=1, authorize=guard)
    for label in ('draft', 'open', 'submitted'):
        plan_key = key(f'plan-{label}')
        plan = CountPlanCreate(operation_key=plan_key, branch_id=branch.id,
            code=f'DEMO-WF-{label.upper()}', name=f'DEMO ONLY - {label.title()} count workflow', year=2026)
        create_plan(db, context, requestor.id, plan_key, plan, authorize=guard)
        scope = CountScopeSave(operation_key=key(f'scope-{label}'), lines=[
            CountScopeLine(product_id=product.id, location_id=location.id, cadence='QUARTERLY',
                           due_on=date(2026, 12, 31)) for product in products])
        save_scope(db, context, requestor.id, scope.operation_key, plan_key, scope, authorize=guard)
        if label == 'draft':
            continue
        activate = CountPlanActivate(operation_key=key(f'activate-{label}'))
        activate_plan(db, context, requestor.id, activate.operation_key, plan_key, activate, authorize=guard)
        assignment = CountSessionCreate(operation_key=key(f'round-{label}'), plan_key=plan_key,
            location_id=location.id, assignee_id=viewer.id if label == 'open' else requestor.id)
        assign_session(db, context, requestor.id, assignment.operation_key, assignment, authorize=guard)
        if label == 'open':
            continue
        entries = CountEntrySave(operation_key=key('count-entries'), entries=[
            dict(product_id=product.id, location_id=location.id, quantity=str(index + 1), unit='PCS')
            for index, product in enumerate(products)])
        save_entries(db, context, requestor.id, entries.operation_key, assignment.operation_key, entries, authorize=guard)
        submit = CountSubmit(operation_key=key('count-submit'), expected_entered_lines=2)
        submit_session(db, context, requestor.id, submit.operation_key, assignment.operation_key, submit, authorize=guard)
        session_id = db.query(CountSession.id).filter_by(org_id=demo.id, session_key=assignment.operation_key).scalar()
        for difference in db.query(CountDiscrepancy).filter_by(org_id=demo.id, session_id=session_id).all():
            request = DiscrepancyReviewRequest(operation_key=key(f'review-{difference.product_id}'),
                expected_counted_base=format(difference.counted_base, 'f'),
                reason='DEMO ONLY - synthetic discrepancy; review does not adjust stock')
            request_discrepancy_review(db, context, requestor.id, request.operation_key,
                                       difference.id, request, authorize=guard)
    db.flush()
    return dict(summary, created=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-demo-only', action='store_true')
    parser.add_argument('--viewer-id', type=int, required=True)
    args = parser.parse_args()
    if not args.confirm_demo_only or engine.url.database != 'freightlens_pos_preview' or engine.url.host != 'db':
        raise SystemExit('Refusing: explicit local preview confirmation required')
    with SessionLocal.begin() as db:
        result = seed_workflows(db, args.viewer_id)
    # Search is a post-commit projection; never hold workflow locks over network I/O.
    from Services.search_service import sync_customer_document
    from Services.customer_profile_service import read_customer_profile
    context = OrgContext(current_org_id=result['org_id'], allowed_org_ids=[result['org_id']],
                         selected_org_id=result['org_id'], is_root=False)
    with SessionLocal() as db:
        profiles = [read_customer_profile(db, context, uuid5(NAMESPACE, f"{result['org_id']}:customer-{i}"),
            authorize=lambda session: None) for i in range(2)]
    indexed = all([sync_customer_document(row.customer_key, result['org_id'],
        row.model_dump(mode='json')) for row in profiles])
    print(dict(result, search_indexed=indexed))


if __name__ == '__main__':
    main()
