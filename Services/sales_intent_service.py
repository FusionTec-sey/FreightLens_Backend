"""Atomic versioned draft saves; not sale confirmation, allocation or payment."""
from decimal import Decimal
from uuid import UUID
from sqlalchemy.dialects.postgresql import insert
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision, SalesIntentLineRevision
from Model.containermgmt.Orders.SalesIntentCopyOrigin import SalesIntentCopyOrigin
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.Location import InventoryBranch
from Schema.SalesIntentSchema import SalesIntentInput, SalesIntentSourceReference
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.sales_intent_source_service import prepare_sales_intent
from Services.customer_profile_service import historical_names_for_page
from Services.sales_product_media import sales_thumbnail
from Services.sales_reservation_source_service import protect_held_draft, active_demand_holds
from Utils.org_filter import apply_org_filter


def scoped(db, model, context, document_key):
    return apply_org_filter(db.query(model).filter_by(org_id=context.org_id,
        document_key=document_key, is_deleted=False), model, context)


def sales_branch_labels(db, context, branch_ids):
    """Current display labels only, bounded by the existing sales page limit."""
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Sales draft company denied')
    ids = set(branch_ids)
    if len(ids) > 100:
        raise ValueError('Branch labels require a bounded sales page')
    if not ids:
        return {}
    rows = apply_org_filter(db.query(InventoryBranch.id, InventoryBranch.name).filter(
        InventoryBranch.org_id == context.org_id, InventoryBranch.is_deleted.is_(False),
        InventoryBranch.id.in_(ids)), InventoryBranch, context).all()
    return {row.id: row.name for row in rows}


def save_sales_intent(factory, context, actor_id, operation_key, document_key,
                      payload, *, expected_version, authorize,
                      source_reference=None):
    if not callable(authorize): raise ValueError('Sales draft permission guard required')
    if not isinstance(document_key, UUID) or not document_key.int:
        raise ValueError('Nonzero document UUID required')
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError('Expected draft version required')
    if not isinstance(payload, SalesIntentInput): raise ValueError('Typed sales draft required')
    payload = SalesIntentInput.model_validate(payload.model_dump())
    if source_reference is not None:
        if not isinstance(source_reference, SalesIntentSourceReference):
            raise ValueError('Typed sales draft source reference required')
        source_reference = SalesIntentSourceReference.model_validate(
            source_reference.model_dump())
        if expected_version != 0:
            raise ValueError('A source reference is allowed only on the initial draft save')
        if source_reference.document_key == document_key:
            raise ValueError('A copied draft needs a new document identity')

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
        if source_reference is not None:
            source = scoped(db, SalesIntentRevision, context,
                source_reference.document_key).filter(
                    SalesIntentRevision.version == source_reference.version
                ).one_or_none()
            if source is None:
                raise LookupError('Sales draft copy source not found')
            source_line_keys = {row.line_key for row in scoped(
                db, SalesIntentLineRevision, context,
                source_reference.document_key
            ).filter(
                SalesIntentLineRevision.version == source_reference.version
            ).with_entities(SalesIntentLineRevision.line_key).all()}
            if source_line_keys.intersection(line.line_key for line in payload.lines):
                raise PostingConflict('Copied draft lines require new identities')
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
        if source_reference is not None:
            db.add(SalesIntentCopyOrigin(org_id=context.org_id,
                destination_document_key=document_key,
                source_document_key=source_reference.document_key,
                source_version=source_reference.version,
                operation_key=operation_key, created_by=actor_id))
        result = dict(document_key=str(document_key), version=version, status='DRAFT')
        event = dict(kind=('sales.intent.copied' if source_reference is not None
                           else 'sales.intent.saved'), **result)
        if source_reference is not None:
            event['source_reference'] = source_reference.model_dump(mode='json')
        return PostingEffect(result, event)

    request = dict(document_key=str(document_key), expected_version=expected_version,
                   draft=payload.model_dump(mode='json'))
    # Preserve the pre-T15 operation fingerprint for ordinary saves so an
    # uncertain retry created before this additive field remains replayable.
    if source_reference is not None:
        request['source_reference'] = source_reference.model_dump(mode='json')
    operation_kind = ('sales.intent.copy.v1' if source_reference is not None
                      else 'sales.intent.save.v1')
    return execute_once(factory, context, actor_id, operation_key,
        operation_kind, request, effect, authorize=authorize)


def get_sales_intent(db, context, document_key, *, authorize, version=None):
    if not callable(authorize): raise ValueError('Sales draft permission guard required')
    authorize(db)
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Sales draft company denied')
    if version is not None and (type(version) is not int or version < 1):
        raise ValueError('Positive draft version required')
    revisions = scoped(db, SalesIntentRevision, context, document_key)
    if version is not None:
        revisions = revisions.filter(SalesIntentRevision.version == version)
    revision = revisions.order_by(SalesIntentRevision.version.desc()).first()
    if revision is None: raise LookupError('Sales draft not found')
    lines = scoped(db, SalesIntentLineRevision, context, document_key).filter_by(
        version=revision.version).order_by(SalesIntentLineRevision.position).limit(100).all()
    # Current display labels are not a historical invoice snapshot. Never load
    # supplier relationships or costs merely to label the existing catalogue IDs.
    labels = {row.id: row for row in apply_org_filter(db.query(Product.id, Product.name, Product.sku, Product.images).filter(
        Product.org_id == context.org_id, Product.is_deleted.is_(False),
        Product.id.in_([line.product_id for line in lines])), Product, context).all()}
    # Never project current reservation balances as if they belonged to history.
    holds = active_demand_holds(db, context, document_key) if version is None else {}
    customer_names = historical_names_for_page(db, context,
        [(revision.customer_key, revision.customer_version)], authorize=authorize)
    origin = apply_org_filter(db.query(SalesIntentCopyOrigin).filter(
        SalesIntentCopyOrigin.org_id == context.org_id,
        SalesIntentCopyOrigin.destination_document_key == document_key,
        SalesIntentCopyOrigin.is_deleted.is_(False)), SalesIntentCopyOrigin,
        context).one_or_none()
    result = dict(document_key=str(document_key), version=revision.version, status=revision.status,
        customer_key=str(revision.customer_key), expected_customer_version=revision.customer_version,
        customer_name=customer_names.get((revision.customer_key, revision.customer_version)),
        branch_id=revision.branch_id,
        branch_name=sales_branch_labels(db, context, [revision.branch_id]).get(revision.branch_id),
        created_at=revision.created_at, created_by=revision.created_by,
        source_reference=(dict(document_key=str(origin.source_document_key),
                               version=origin.source_version)
                          if origin is not None else None),
        lines=[dict(line_key=str(line.line_key),
            product_id=line.product_id, expected_policy_version=line.policy_version,
            quantity=format(line.quantity, 'f'), unit=line.unit,
            base_quantity=format(line.base_quantity, 'f'), base_unit=line.base_unit,
            product_name=labels[line.product_id].name if line.product_id in labels else None,
            sku=labels[line.product_id].sku if line.product_id in labels else None,
            image_signed_url=sales_thumbnail(labels[line.product_id].images) if line.product_id in labels else None,
            **({'reserved_quantity': format(holds.get(line.line_key, Decimal(0)), 'f')} if version is None else {}),
            units=[line.policy['base_unit']] + [unit['unit'] for unit in line.policy['conversions']]) for line in lines])
    if version is not None:
        result['customer_version'] = result.pop('expected_customer_version')
        result.update(created_at=revision.created_at, created_by=revision.created_by,
                      read_only=True, catalogue_labels_current=True)
    return result
