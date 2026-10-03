"""Atomic versioned draft saves; not sale confirmation, allocation or payment."""
from decimal import Decimal
from uuid import UUID
from sqlalchemy.dialects.postgresql import insert
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision, SalesIntentLineRevision
from Model.containermgmt.Orders.Product import Product
from Schema.SalesIntentSchema import SalesIntentInput
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.sales_intent_source_service import prepare_sales_intent
from Services.sales_reservation_source_service import protect_held_draft, active_demand_holds
from Utils.org_filter import apply_org_filter


def scoped(db, model, context, document_key):
    return apply_org_filter(db.query(model).filter_by(org_id=context.org_id,
        document_key=document_key, is_deleted=False), model, context)


def save_sales_intent(factory, context, actor_id, operation_key, document_key,
                      payload, *, expected_version, authorize):
    if not callable(authorize): raise ValueError('Sales draft permission guard required')
    if not isinstance(document_key, UUID) or not document_key.int:
        raise ValueError('Nonzero document UUID required')
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError('Expected draft version required')
    if not isinstance(payload, SalesIntentInput): raise ValueError('Typed sales draft required')
    payload = SalesIntentInput.model_validate(payload.model_dump())

    def effect(db):
        if expected_version == 0:
            # A conflicting insert waits for the creator; all later writes lock
            # this same stable parent. No advisory-lock implementation duplicated.
            db.execute(insert(SalesIntent).values(document_key=document_key,
                org_id=context.org_id, created_by=actor_id).on_conflict_do_nothing())
        parent = scoped(db, SalesIntent, context, document_key).with_for_update().one_or_none()
        if parent is None: raise LookupError('Sales draft not found')
        previous = scoped(db, SalesIntentRevision, context, document_key).order_by(
            SalesIntentRevision.version.desc()).first()
        if (previous.version if previous else 0) != expected_version:
            raise PostingConflict('Sales draft changed; reload before saving')
        protect_held_draft(db, context, document_key, previous, payload)
        snapshot = prepare_sales_intent(db, context, payload, authorize=authorize)
        # Line identities are scoped to their document and cannot be relabelled
        # as a different product, even after removal from an intervening revision.
        line_keys = [line.line_key for line in payload.lines]
        historical = scoped(db, SalesIntentLineRevision, context, document_key).filter(
            SalesIntentLineRevision.line_key.in_(line_keys)).with_entities(
                SalesIntentLineRevision.line_key, SalesIntentLineRevision.product_id).distinct().all()
        supplied = {line.line_key: line.product_id for line in payload.lines}
        if any(supplied[key] != product for key, product in historical):
            raise PostingConflict('A retained line identity cannot change product')
        version = expected_version + 1
        db.add(SalesIntentRevision(org_id=context.org_id, document_key=document_key,
            version=version, operation_key=operation_key, customer_key=payload.customer_key,
            customer_version=snapshot['customer_version'], branch_id=payload.branch_id,
            status='DRAFT', created_by=actor_id))
        db.flush()
        for position, line in enumerate(snapshot['lines'], 1):
            db.add(SalesIntentLineRevision(org_id=context.org_id, document_key=document_key,
                version=version, line_key=UUID(line['line_key']), position=position,
                product_id=line['product_id'], policy_version=line['expected_policy_version'],
                quantity=Decimal(line['quantity']), unit=line['unit'],
                base_quantity=Decimal(line['base_quantity']), base_unit=line['base_unit'],
                policy=line['policy'], created_by=actor_id))
        result = dict(document_key=str(document_key), version=version, status='DRAFT')
        return PostingEffect(result, dict(kind='sales.intent.saved', **result))

    return execute_once(factory, context, actor_id, operation_key, 'sales.intent.save.v1',
        dict(document_key=str(document_key), expected_version=expected_version,
             draft=payload.model_dump(mode='json')), effect, authorize=authorize)


def get_sales_intent(db, context, document_key, *, authorize):
    if not callable(authorize): raise ValueError('Sales draft permission guard required')
    authorize(db)
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Sales draft company denied')
    revision = scoped(db, SalesIntentRevision, context, document_key).order_by(
        SalesIntentRevision.version.desc()).first()
    if revision is None: raise LookupError('Sales draft not found')
    lines = scoped(db, SalesIntentLineRevision, context, document_key).filter_by(
        version=revision.version).order_by(SalesIntentLineRevision.position).limit(100).all()
    # Current display labels are not a historical invoice snapshot. Never load
    # supplier relationships or costs merely to label the existing catalogue IDs.
    labels = {row.id: row for row in apply_org_filter(db.query(Product.id, Product.name, Product.sku).filter(
        Product.org_id == context.org_id, Product.is_deleted.is_(False),
        Product.id.in_([line.product_id for line in lines])), Product, context).all()}
    holds = active_demand_holds(db, context, document_key)
    return dict(document_key=str(document_key), version=revision.version, status=revision.status,
        customer_key=str(revision.customer_key), expected_customer_version=revision.customer_version,
        branch_id=revision.branch_id, lines=[dict(line_key=str(line.line_key),
            product_id=line.product_id, expected_policy_version=line.policy_version,
            quantity=format(line.quantity, 'f'), unit=line.unit,
            base_quantity=format(line.base_quantity, 'f'), base_unit=line.base_unit,
            product_name=labels[line.product_id].name if line.product_id in labels else None,
            sku=labels[line.product_id].sku if line.product_id in labels else None,
            reserved_quantity=format(holds.get(line.line_key, Decimal(0)), 'f'),
            units=[line.policy['base_unit']] + [unit['unit'] for unit in line.policy['conversions']]) for line in lines])
