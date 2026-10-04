"""Versioned synthetic methods and exact receiving accounts; no money posting."""
from uuid import UUID
from sqlalchemy import func, text

from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Orders.PaymentConfiguration import (
    PaymentMethod, PaymentMethodRevision, BranchReceivingAccount,
    BranchReceivingAccountRevision)
from Schema.PaymentConfigurationSchema import MethodSave, MappingSave
from Services.inventory_posting_service import PostingConflict, PostingEffect, execute_once
from Utils.org_filter import apply_org_filter


def _scope(context):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Active organisation required")


def _identity(value):
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("Nonzero UUID identity required")


def _auth(authorize, db, context):
    if not callable(authorize):
        raise ValueError("Payment configuration authorization guard required")
    authorize(db)
    _scope(context)


def _lock(db, context, kind, key):
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
               {"key": f"payment-config:{context.org_id}:{kind}:{key}"})


def _header(db, context, model, field, key, *, lock=False):
    query = apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, field == key, model.is_deleted.is_(False)),
        model, context)
    return (query.populate_existing().with_for_update() if lock else query).one_or_none()


def _latest(db, context, model, field, key):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, field == key, model.is_deleted.is_(False)),
        model, context).order_by(model.version.desc()).first()


def _method(db, context, key, *, lock=False):
    return _header(db, context, PaymentMethod, PaymentMethod.method_key, key, lock=lock)


def _mapping(db, context, key, *, lock=False):
    return _header(db, context, BranchReceivingAccount,
                   BranchReceivingAccount.mapping_key, key, lock=lock)


def _branch(db, context, branch_id, *, lock=False):
    branch = _header(db, context, InventoryBranch, InventoryBranch.id, branch_id, lock=lock)
    if branch is None:
        raise LookupError("Branch not found")
    return branch


def _method_read(header, rev):
    return dict(method_key=header.method_key, code=header.code, version=rev.version,
                label=rev.label, kind=rev.kind, is_enabled=rev.is_enabled)


def _mapping_read(header, rev):
    return dict(mapping_key=header.mapping_key, branch_id=header.branch_id,
                method_key=header.method_key, version=rev.version,
                account_ref=rev.account_ref, label=rev.label, is_enabled=rev.is_enabled)


def _page(query, page, limit, project):
    if type(page) is not int or page < 1 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid payment configuration pagination")
    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return dict(items=[project(*row) for row in rows], total=total, page=page,
                pages=max(1, (total + limit - 1) // limit), limit=limit)


def list_methods(db, context, *, page, limit, authorize):
    _auth(authorize, db, context)
    latest = db.query(PaymentMethodRevision.method_key,
        func.max(PaymentMethodRevision.version).label("version")).filter(
        PaymentMethodRevision.org_id == context.org_id,
        PaymentMethodRevision.is_deleted.is_(False)).group_by(
        PaymentMethodRevision.method_key).subquery()
    query = db.query(PaymentMethod, PaymentMethodRevision).join(latest,
        latest.c.method_key == PaymentMethod.method_key).join(PaymentMethodRevision,
        (PaymentMethodRevision.org_id == context.org_id)
        & (PaymentMethodRevision.method_key == latest.c.method_key)
        & (PaymentMethodRevision.version == latest.c.version)).filter(
        PaymentMethod.org_id == context.org_id,
        PaymentMethod.is_deleted.is_(False)).order_by(PaymentMethod.code)
    return _page(query, page, limit, _method_read)


def list_branch_options(db, context, *, page, limit, authorize):
    _auth(authorize, db, context)
    query = apply_org_filter(db.query(InventoryBranch).filter(
        InventoryBranch.org_id == context.org_id,
        InventoryBranch.is_deleted.is_(False)), InventoryBranch, context)
    total = query.count()
    rows = query.order_by(InventoryBranch.code).offset((page - 1) * limit).limit(limit).all()
    return dict(items=[dict(id=row.id, code=row.code, name=row.name,
                            is_active=row.is_active) for row in rows],
                total=total, page=page, pages=max(1, (total + limit - 1) // limit),
                limit=limit)


def list_mappings(db, context, *, page, limit, authorize, branch_id=None):
    _auth(authorize, db, context)
    if branch_id is not None:
        _branch(db, context, branch_id)
    latest = db.query(BranchReceivingAccountRevision.mapping_key,
        func.max(BranchReceivingAccountRevision.version).label("version")).filter(
        BranchReceivingAccountRevision.org_id == context.org_id,
        BranchReceivingAccountRevision.is_deleted.is_(False)).group_by(
        BranchReceivingAccountRevision.mapping_key).subquery()
    query = db.query(BranchReceivingAccount, BranchReceivingAccountRevision).join(
        latest, latest.c.mapping_key == BranchReceivingAccount.mapping_key).join(
        BranchReceivingAccountRevision,
        (BranchReceivingAccountRevision.org_id == context.org_id)
        & (BranchReceivingAccountRevision.mapping_key == latest.c.mapping_key)
        & (BranchReceivingAccountRevision.version == latest.c.version)).filter(
        BranchReceivingAccount.org_id == context.org_id,
        BranchReceivingAccount.is_deleted.is_(False))
    if branch_id is not None:
        query = query.filter(BranchReceivingAccount.branch_id == branch_id)
    return _page(query.order_by(BranchReceivingAccount.branch_id,
        BranchReceivingAccount.method_key), page, limit, _mapping_read)


def save_method(db, context, actor_id, method_key, payload: MethodSave, *, authorize):
    _identity(method_key)
    payload = MethodSave.model_validate(payload)
    request = payload.model_dump(mode="json", exclude={"operation_key"})
    request["method_key"] = str(method_key)

    def guard(session):
        _auth(authorize, session, context)
        if payload.expected_version:
            if _method(session, context, method_key) is None:
                raise LookupError("Payment method not found")

    def effect(session):
        _lock(session, context, "method-code", payload.code)
        header = _method(session, context, method_key, lock=True)
        if header is None:
            if payload.expected_version != 0:
                raise PostingConflict("Payment method changed; reload")
            existing = apply_org_filter(session.query(PaymentMethod).filter_by(
                org_id=context.org_id, code=payload.code, is_deleted=False),
                PaymentMethod, context).one_or_none()
            if existing:
                raise PostingConflict("Payment method code already exists")
            header = PaymentMethod(org_id=context.org_id, method_key=method_key,
                code=payload.code, creation_operation_key=payload.operation_key,
                created_by=actor_id)
            session.add(header); session.flush()
            current = None
        else:
            if header.code != payload.code:
                raise PostingConflict("Payment method code is immutable")
            current = _latest(session, context, PaymentMethodRevision,
                              PaymentMethodRevision.method_key, method_key)
        version = current.version if current else 0
        if version != payload.expected_version:
            raise PostingConflict("Payment method changed; reload")
        if current and current.kind != payload.config.kind:
            raise PostingConflict("Payment method type is immutable")
        if current and (current.label, current.kind, current.is_enabled) == (
                payload.config.label, payload.config.kind, payload.config.is_enabled):
            raise ValueError("Payment method has no changes")
        revision = PaymentMethodRevision(org_id=context.org_id,
            method_key=method_key, operation_key=payload.operation_key,
            version=version + 1, label=payload.config.label,
            kind=payload.config.kind, is_enabled=payload.config.is_enabled,
            reason=payload.reason, created_by=actor_id)
        session.add(revision); session.flush()
        result = dict(key=str(method_key), version=revision.version)
        return PostingEffect(result, {"kind": "payment.method.configured", **result})

    return execute_once(db, context, actor_id, payload.operation_key,
        "payment.method.save.v1", request, effect, authorize=guard)


def save_mapping(db, context, actor_id, mapping_key, payload: MappingSave, *, authorize):
    _identity(mapping_key)
    payload = MappingSave.model_validate(payload)
    request = payload.model_dump(mode="json", exclude={"operation_key"})
    request["mapping_key"] = str(mapping_key)

    def guard(session):
        _auth(authorize, session, context)
        # Lock configuration parents before the mapping target so a method or
        # branch cannot be disabled between validation and revision append.
        branch = _branch(session, context, payload.branch_id, lock=True)
        method = _method(session, context, payload.method_key, lock=True)
        if method is None:
            raise LookupError("Payment method not found")
        current = _latest(session, context, PaymentMethodRevision,
                          PaymentMethodRevision.method_key, payload.method_key)
        if not branch.is_active or not current or not current.is_enabled:
            raise PostingConflict("Active branch and payment method required")
        if payload.expected_version and _mapping(session, context, mapping_key) is None:
            raise LookupError("Receiving account mapping not found")

    def effect(session):
        _lock(session, context, "mapping-target", f"{payload.branch_id}:{payload.method_key}")
        header = _mapping(session, context, mapping_key, lock=True)
        if header is None:
            if payload.expected_version != 0:
                raise PostingConflict("Receiving account mapping changed; reload")
            existing = apply_org_filter(session.query(BranchReceivingAccount).filter_by(
                org_id=context.org_id, branch_id=payload.branch_id,
                method_key=payload.method_key, is_deleted=False),
                BranchReceivingAccount, context).one_or_none()
            if existing:
                raise PostingConflict("Branch/method mapping already exists")
            header = BranchReceivingAccount(org_id=context.org_id,
                mapping_key=mapping_key, branch_id=payload.branch_id,
                method_key=payload.method_key, creation_operation_key=payload.operation_key,
                created_by=actor_id)
            session.add(header); session.flush()
            current = None
        else:
            if (header.branch_id, header.method_key) != (payload.branch_id, payload.method_key):
                raise PostingConflict("Receiving account target is immutable")
            current = _latest(session, context, BranchReceivingAccountRevision,
                              BranchReceivingAccountRevision.mapping_key, mapping_key)
        version = current.version if current else 0
        if version != payload.expected_version:
            raise PostingConflict("Receiving account mapping changed; reload")
        if current and (current.account_ref, current.label, current.is_enabled) == (
                payload.config.account_ref, payload.config.label, payload.config.is_enabled):
            raise ValueError("Receiving account mapping has no changes")
        revision = BranchReceivingAccountRevision(org_id=context.org_id,
            mapping_key=mapping_key, operation_key=payload.operation_key,
            version=version + 1, account_ref=payload.config.account_ref,
            label=payload.config.label, is_enabled=payload.config.is_enabled,
            reason=payload.reason, created_by=actor_id)
        session.add(revision); session.flush()
        result = dict(key=str(mapping_key), version=revision.version)
        return PostingEffect(result, {"kind": "payment.receiving-account.configured", **result})

    return execute_once(db, context, actor_id, payload.operation_key,
        "payment.receiving-account.save.v1", request, effect, authorize=guard)


def lookup_receiving_account(db, context, branch_id, method_key, *, authorize):
    """Fail closed for the exact branch/method. Never chooses a fallback account."""
    _identity(method_key)
    _auth(authorize, db, context)
    branch = _branch(db, context, branch_id)
    method = _method(db, context, method_key)
    if method is None:
        raise LookupError("Payment method not found")
    base = dict(branch_id=branch_id, method_key=method_key)
    if not branch.is_active:
        return dict(status="BLOCKED", reason="BRANCH_DISABLED", **base)
    method_revision = _latest(db, context, PaymentMethodRevision,
                              PaymentMethodRevision.method_key, method_key)
    if method_revision is None or not method_revision.is_enabled:
        return dict(status="BLOCKED", reason="METHOD_DISABLED", **base)
    mapping = apply_org_filter(db.query(BranchReceivingAccount).filter_by(
        org_id=context.org_id, branch_id=branch_id, method_key=method_key,
        is_deleted=False), BranchReceivingAccount, context).one_or_none()
    if mapping is None:
        return dict(status="BLOCKED", reason="MAPPING_MISSING", **base)
    revision = _latest(db, context, BranchReceivingAccountRevision,
                       BranchReceivingAccountRevision.mapping_key, mapping.mapping_key)
    if revision is None or not revision.is_enabled:
        return dict(status="BLOCKED", reason="MAPPING_DISABLED", **base)
    return dict(status="READY", reason=None, mapping_key=mapping.mapping_key,
                mapping_version=revision.version, account_ref=revision.account_ref,
                label=revision.label, **base)


def require_receiving_account(db, context, branch_id, method_key, *,
        expected_method_version, expected_mapping_key,
        expected_mapping_version, authorize):
    """Lock and revalidate the exact READY mapping for a future money post."""
    _identity(method_key)
    _identity(expected_mapping_key)
    if (type(expected_method_version) is not int or expected_method_version <= 0
            or type(expected_mapping_version) is not int
            or expected_mapping_version <= 0):
        raise ValueError("Positive payment configuration versions required")
    _auth(authorize, db, context)
    branch = _branch(db, context, branch_id, lock=True)
    method = _method(db, context, method_key, lock=True)
    if method is None:
        raise LookupError("Payment method not found")
    method_revision = _latest(db, context, PaymentMethodRevision,
        PaymentMethodRevision.method_key, method_key)
    if (not branch.is_active or method_revision is None
            or not method_revision.is_enabled):
        raise PostingConflict("Branch or payment method is disabled")
    if method_revision.version != expected_method_version:
        raise PostingConflict("Payment method changed; refresh before posting")
    mapping = apply_org_filter(db.query(BranchReceivingAccount).filter_by(
        org_id=context.org_id, branch_id=branch_id, method_key=method_key,
        is_deleted=False), BranchReceivingAccount, context).with_for_update().one_or_none()
    if mapping is None or mapping.mapping_key != expected_mapping_key:
        raise PostingConflict("Exact receiving-account mapping is unavailable")
    revision = _latest(db, context, BranchReceivingAccountRevision,
        BranchReceivingAccountRevision.mapping_key, mapping.mapping_key)
    if revision is None or not revision.is_enabled:
        raise PostingConflict("Receiving-account mapping is disabled")
    if revision.version != expected_mapping_version:
        raise PostingConflict("Receiving-account mapping changed; refresh before posting")
    return _mapping_read(mapping, revision)
