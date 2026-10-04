"""Append-only customer edits; no balance merge or historical sales rewrite.

Callers must provide the customer-management and personal-data authorization
boundary. External search synchronization occurs only after commit.
"""
from sqlalchemy import func, tuple_

from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Model.containermgmt.MasterData.CustomerProfileRevision import CustomerProfileRevision
from Schema.CustomerSchema import CustomerIdentityRead, CustomerProfileHistory, CustomerProfileUpdate
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Utils.org_filter import apply_org_filter


def _customer(db, context, customer_key, authorize, *, lock=False):
    if not callable(authorize):
        raise ValueError('Customer and personal-data permission guard required')
    authorize(db)
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Customer company scope denied')
    query = apply_org_filter(db.query(RetailCustomer).filter_by(
        org_id=context.org_id, customer_key=customer_key, is_deleted=False),
        RetailCustomer, context)
    if lock:
        query = query.with_for_update()
    row = query.one_or_none()
    if row is None:
        raise LookupError('Customer not found')
    return row


def _revisions(db, context, customer_key):
    return apply_org_filter(db.query(CustomerProfileRevision).filter_by(
        org_id=context.org_id, customer_key=customer_key, is_deleted=False),
        CustomerProfileRevision, context)


def current_profiles_for_page(db, context, rows):
    """Project an already-authorized bounded customer page without N+1 reads."""
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Customer company scope denied')
    if len(rows) > 100 or any(row.org_id != context.org_id for row in rows):
        raise ValueError('A bounded same-company customer page is required')
    if not rows:
        return []
    revisions = apply_org_filter(db.query(CustomerProfileRevision).filter(
        CustomerProfileRevision.org_id == context.org_id,
        CustomerProfileRevision.customer_key.in_([row.customer_key for row in rows]),
        CustomerProfileRevision.is_deleted.is_(False)), CustomerProfileRevision, context
    ).distinct(CustomerProfileRevision.customer_key).order_by(
        CustomerProfileRevision.customer_key, CustomerProfileRevision.version.desc()).all()
    latest = {revision.customer_key: revision for revision in revisions}
    return [CustomerIdentityRead(customer_key=row.customer_key,
        version=latest[row.customer_key].version if row.customer_key in latest else 1,
        **(latest[row.customer_key].profile if row.customer_key in latest else row.initial_profile))
        for row in rows]


def historical_names_for_page(db, context, references, *, authorize):
    """Names only, keyed by exact historical identity/version; never latest fallback."""
    if not callable(authorize):
        raise ValueError('Customer and personal-data permission guard required')
    authorize(db)
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Customer company scope denied')
    if len(references) > 100 or any(type(version) is not int or version < 1 for _, version in references):
        raise ValueError('A bounded historical customer page is required')
    pairs = set(references)
    if not pairs:
        return {}
    original = [key for key, version in pairs if version == 1]
    names = {}
    if original:
        rows = apply_org_filter(db.query(RetailCustomer.customer_key,
            RetailCustomer.initial_profile['name'].astext.label('name')).filter(
            RetailCustomer.org_id == context.org_id, RetailCustomer.is_deleted.is_(False),
            RetailCustomer.customer_key.in_(original)), RetailCustomer, context).all()
        names.update({(row.customer_key, 1): row.name for row in rows})
    revised = [(key, version) for key, version in pairs if version > 1]
    if revised:
        model = CustomerProfileRevision
        rows = apply_org_filter(db.query(model.customer_key, model.version,
            model.profile['name'].astext.label('name')).join(RetailCustomer,
            (RetailCustomer.customer_key == model.customer_key) &
            (RetailCustomer.org_id == model.org_id)).filter(
            model.org_id == context.org_id, model.is_deleted.is_(False),
            RetailCustomer.is_deleted.is_(False),
            tuple_(model.customer_key, model.version).in_(revised)), model, context).all()
        names.update({(row.customer_key, row.version): row.name for row in rows})
    return names


def read_customer_profile(db, context, customer_key, *, authorize, version=None, lock=False):
    """Exact historical version, or latest profile. Optional lock pins a save."""
    if version is not None and (type(version) is not int or version < 1):
        raise ValueError('Positive customer profile version required')
    row = _customer(db, context, customer_key, authorize, lock=lock)
    revision = None
    if version != 1:
        query = _revisions(db, context, customer_key)
        if version is not None:
            query = query.filter(CustomerProfileRevision.version == version)
        revision = query.order_by(CustomerProfileRevision.version.desc()).first()
        if version is not None and revision is None:
            raise LookupError('Customer profile version not found')
    return CustomerIdentityRead(customer_key=row.customer_key,
        version=revision.version if revision else 1,
        **(revision.profile if revision else row.initial_profile))


def update_customer_profile(factory, context, actor_id, customer_key, payload, *, authorize):
    if not isinstance(payload, CustomerProfileUpdate):
        raise ValueError('Typed customer profile update required')
    payload = CustomerProfileUpdate.model_validate(payload.model_dump())
    if not callable(authorize):
        raise ValueError('Customer management and personal-data permission guard required')
    request = payload.model_dump(mode='json', exclude={'operation_key'})
    request['customer_key'] = str(customer_key)

    def guard(db):
        # Recheck scope/permissions even for an already committed operation.
        _customer(db, context, customer_key, authorize, lock=True)

    def effect(db):
        current = read_customer_profile(db, context, customer_key, authorize=authorize)
        if current.version != payload.expected_version:
            raise PostingConflict('Customer profile changed; reload before editing')
        snapshot = payload.profile.model_dump(mode='json')
        if snapshot == current.model_dump(mode='json', exclude={'customer_key', 'version'}):
            raise ValueError('Customer profile has no changes')
        version = current.version + 1
        db.add(CustomerProfileRevision(org_id=context.org_id, customer_key=customer_key,
            version=version, operation_key=payload.operation_key, profile=snapshot,
            reason=payload.reason, created_by=actor_id))
        db.flush()
        result = dict(customer_key=str(customer_key), version=version)
        # Personal details and edit reasons stay out of generic event envelopes.
        return PostingEffect(result, dict(kind='customer.profile.updated', **result))

    return execute_once(factory, context, actor_id, payload.operation_key,
        'customer.profile.update.v1', request, effect, authorize=guard)


def customer_profile_history(db, context, customer_key, *, authorize, page=1, limit=25):
    if type(page) is not int or page < 1 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid customer history pagination')
    # Pin the identity while counting/paging so concurrent appends cannot move
    # the original version into or out of this page between READ COMMITTED reads.
    row = _customer(db, context, customer_key, authorize, lock=True)
    query = _revisions(db, context, customer_key)
    count = query.with_entities(func.count()).scalar()
    offset = (page - 1) * limit
    revisions = query.order_by(CustomerProfileRevision.version.desc()).offset(offset).limit(limit).all()
    items = [CustomerProfileHistory(customer_key=row.customer_key, version=item.version,
        reason=item.reason, created_by=item.created_by, created_at=item.created_at,
        **item.profile) for item in revisions]
    if offset <= count < offset + limit:
        items.append(CustomerProfileHistory(customer_key=row.customer_key, version=1,
            reason='Initial customer profile', created_by=row.created_by,
            created_at=row.created_at, **row.initial_profile))
    total = count + 1
    return dict(items=items, total=total, page=page, limit=limit,
                pages=(total + limit - 1) // limit)
