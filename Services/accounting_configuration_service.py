"""Versioned exact-branch account-role configuration; no financial posting."""
from uuid import UUID

from sqlalchemy import func, text

from Model.containermgmt.Accounting.AccountingConfiguration import (
    ACCOUNT_ROLES,
    BranchAccountMapping,
    BranchAccountMappingRevision,
)
from Model.containermgmt.Inventory.Location import InventoryBranch
from Schema.AccountingConfigurationSchema import AccountMappingSave
from Services.inventory_posting_service import PostingConflict, PostingEffect, execute_once
from Utils.org_filter import apply_org_filter


def _scope(context) -> None:
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Active organisation required")


def _identity(value: UUID) -> None:
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("Nonzero UUID identity required")


def _role(value: str) -> None:
    if value not in ACCOUNT_ROLES:
        raise ValueError("Unsupported logical account role")


def _auth(authorize, db, context) -> None:
    if not callable(authorize):
        raise ValueError("Accounting configuration authorization guard required")
    authorize(db)
    _scope(context)


def _page(query, page: int, limit: int, project):
    if type(page) is not int or page < 1 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid accounting configuration pagination")
    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "items": [project(row) for row in rows],
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
        "limit": limit,
    }


def _lock_target(db, context, branch_id: int, account_role: str) -> None:
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"account-role:{context.org_id}:{branch_id}:{account_role}"},
    )


def _mapping(db, context, mapping_key: UUID, *, lock: bool = False):
    query = apply_org_filter(
        db.query(BranchAccountMapping).filter(
            BranchAccountMapping.org_id == context.org_id,
            BranchAccountMapping.mapping_key == mapping_key,
            BranchAccountMapping.is_deleted.is_(False),
        ),
        BranchAccountMapping,
        context,
    )
    if lock:
        query = query.populate_existing().with_for_update()
    return query.one_or_none()


def _branch(db, context, branch_id: int, *, lock: bool = False):
    query = apply_org_filter(
        db.query(InventoryBranch).filter(
            InventoryBranch.org_id == context.org_id,
            InventoryBranch.id == branch_id,
            InventoryBranch.is_deleted.is_(False),
        ),
        InventoryBranch,
        context,
    )
    if lock:
        query = query.populate_existing().with_for_update()
    branch = query.one_or_none()
    if branch is None:
        raise LookupError("Branch not found")
    return branch


def _latest(db, context, mapping_key: UUID):
    return apply_org_filter(
        db.query(BranchAccountMappingRevision).filter(
            BranchAccountMappingRevision.org_id == context.org_id,
            BranchAccountMappingRevision.mapping_key == mapping_key,
            BranchAccountMappingRevision.is_deleted.is_(False),
        ),
        BranchAccountMappingRevision,
        context,
    ).order_by(BranchAccountMappingRevision.version.desc()).first()


def _mapping_read(header, revision):
    return {
        "mapping_key": header.mapping_key,
        "branch_id": header.branch_id,
        "account_role": header.account_role,
        "version": revision.version,
        "account_ref": revision.account_ref,
        "label": revision.label,
        "is_enabled": revision.is_enabled,
    }


def _revision_read(header, revision):
    return {
        **_mapping_read(header, revision),
        "operation_key": revision.operation_key,
        "reason": revision.reason,
    }


def list_account_mappings(
    db,
    context,
    *,
    page: int,
    limit: int,
    authorize,
    branch_id: int | None = None,
    account_role: str | None = None,
):
    _auth(authorize, db, context)
    if branch_id is not None:
        _branch(db, context, branch_id)
    if account_role is not None:
        _role(account_role)
    latest = db.query(
        BranchAccountMappingRevision.mapping_key,
        func.max(BranchAccountMappingRevision.version).label("version"),
    ).filter(
        BranchAccountMappingRevision.org_id == context.org_id,
        BranchAccountMappingRevision.is_deleted.is_(False),
    ).group_by(BranchAccountMappingRevision.mapping_key).subquery()
    query = db.query(BranchAccountMapping, BranchAccountMappingRevision).join(
        latest, latest.c.mapping_key == BranchAccountMapping.mapping_key
    ).join(
        BranchAccountMappingRevision,
        (BranchAccountMappingRevision.org_id == context.org_id)
        & (BranchAccountMappingRevision.mapping_key == latest.c.mapping_key)
        & (BranchAccountMappingRevision.version == latest.c.version),
    ).filter(
        BranchAccountMapping.org_id == context.org_id,
        BranchAccountMapping.is_deleted.is_(False),
    )
    if branch_id is not None:
        query = query.filter(BranchAccountMapping.branch_id == branch_id)
    if account_role is not None:
        query = query.filter(BranchAccountMapping.account_role == account_role)
    query = query.order_by(
        BranchAccountMapping.branch_id,
        BranchAccountMapping.account_role,
        BranchAccountMapping.mapping_key,
    )
    return _page(query, page, limit, lambda row: _mapping_read(row[0], row[1]))


def get_account_mapping(db, context, mapping_key: UUID, *, authorize):
    _identity(mapping_key)
    _auth(authorize, db, context)
    header = _mapping(db, context, mapping_key)
    if header is None:
        raise LookupError("Account mapping not found")
    revision = _latest(db, context, mapping_key)
    if revision is None:
        raise LookupError("Account mapping revision not found")
    return _mapping_read(header, revision)


def list_account_mapping_revisions(
    db, context, mapping_key: UUID, *, page: int, limit: int, authorize
):
    _identity(mapping_key)
    _auth(authorize, db, context)
    header = _mapping(db, context, mapping_key)
    if header is None:
        raise LookupError("Account mapping not found")
    query = apply_org_filter(
        db.query(BranchAccountMappingRevision).filter(
            BranchAccountMappingRevision.org_id == context.org_id,
            BranchAccountMappingRevision.mapping_key == mapping_key,
            BranchAccountMappingRevision.is_deleted.is_(False),
        ),
        BranchAccountMappingRevision,
        context,
    ).order_by(BranchAccountMappingRevision.version.desc())
    return _page(query, page, limit, lambda revision: _revision_read(header, revision))


def save_account_mapping(
    db,
    context,
    actor_id: int,
    mapping_key: UUID,
    payload: AccountMappingSave,
    *,
    authorize,
):
    _identity(mapping_key)
    payload = AccountMappingSave.model_validate(payload)
    request = payload.model_dump(mode="json", exclude={"operation_key"})
    request["mapping_key"] = str(mapping_key)

    def guard(session):
        _auth(authorize, session, context)
        branch = _branch(session, context, payload.branch_id, lock=True)
        if not branch.is_active:
            raise PostingConflict("Active branch required")
        if payload.expected_version and _mapping(session, context, mapping_key) is None:
            raise LookupError("Account mapping not found")

    def effect(session):
        _lock_target(session, context, payload.branch_id, payload.account_role)
        header = _mapping(session, context, mapping_key, lock=True)
        if header is None:
            if payload.expected_version != 0:
                raise PostingConflict("Account mapping changed; reload")
            existing = apply_org_filter(
                session.query(BranchAccountMapping).filter(
                    BranchAccountMapping.org_id == context.org_id,
                    BranchAccountMapping.branch_id == payload.branch_id,
                    BranchAccountMapping.account_role == payload.account_role,
                    BranchAccountMapping.is_deleted.is_(False),
                ),
                BranchAccountMapping,
                context,
            ).one_or_none()
            if existing is not None:
                raise PostingConflict("Branch/account-role mapping already exists")
            header = BranchAccountMapping(
                org_id=context.org_id,
                mapping_key=mapping_key,
                branch_id=payload.branch_id,
                account_role=payload.account_role,
                creation_operation_key=payload.operation_key,
                created_by=actor_id,
            )
            session.add(header)
            session.flush()
            current = None
        else:
            if (header.branch_id, header.account_role) != (
                payload.branch_id,
                payload.account_role,
            ):
                raise PostingConflict("Account mapping target is immutable")
            current = _latest(session, context, mapping_key)
        version = current.version if current else 0
        if version != payload.expected_version:
            raise PostingConflict("Account mapping changed; reload")
        if current and (current.account_ref, current.label, current.is_enabled) == (
            payload.config.account_ref,
            payload.config.label,
            payload.config.is_enabled,
        ):
            raise ValueError("Account mapping has no changes")
        revision = BranchAccountMappingRevision(
            org_id=context.org_id,
            mapping_key=mapping_key,
            operation_key=payload.operation_key,
            version=version + 1,
            account_ref=payload.config.account_ref,
            label=payload.config.label,
            is_enabled=payload.config.is_enabled,
            reason=payload.reason,
            created_by=actor_id,
        )
        session.add(revision)
        session.flush()
        result = {"key": str(mapping_key), "version": revision.version}
        return PostingEffect(
            result,
            {"kind": "accounting.branch-account.configured", **result},
        )

    return execute_once(
        db,
        context,
        actor_id,
        payload.operation_key,
        "accounting.branch-account.save.v1",
        request,
        effect,
        authorize=guard,
    )


def lookup_account_mapping(
    db, context, branch_id: int, account_role: str, *, authorize
):
    """Resolve only the exact branch and role, returning typed blocked states."""
    _role(account_role)
    _auth(authorize, db, context)
    branch = _branch(db, context, branch_id)
    base = {"branch_id": branch_id, "account_role": account_role}
    if not branch.is_active:
        return {"status": "BLOCKED", "reason": "BRANCH_DISABLED", **base}
    mapping = apply_org_filter(
        db.query(BranchAccountMapping).filter(
            BranchAccountMapping.org_id == context.org_id,
            BranchAccountMapping.branch_id == branch_id,
            BranchAccountMapping.account_role == account_role,
            BranchAccountMapping.is_deleted.is_(False),
        ),
        BranchAccountMapping,
        context,
    ).one_or_none()
    if mapping is None:
        return {"status": "BLOCKED", "reason": "MAPPING_MISSING", **base}
    revision = _latest(db, context, mapping.mapping_key)
    if revision is None or not revision.is_enabled:
        return {"status": "BLOCKED", "reason": "MAPPING_DISABLED", **base}
    return {
        "status": "READY",
        "reason": None,
        "mapping_key": mapping.mapping_key,
        "mapping_version": revision.version,
        "account_ref": revision.account_ref,
        "label": revision.label,
        **base,
    }


def require_account_mapping(
    db,
    context,
    branch_id: int,
    account_role: str,
    *,
    expected_mapping_key: UUID,
    expected_mapping_version: int,
    authorize,
):
    """Lock and fail closed unless the exact configured revision remains READY."""
    _role(account_role)
    _identity(expected_mapping_key)
    if type(expected_mapping_version) is not int or expected_mapping_version <= 0:
        raise ValueError("Positive account mapping version required")
    _auth(authorize, db, context)
    branch = _branch(db, context, branch_id, lock=True)
    if not branch.is_active:
        raise PostingConflict("Branch is disabled")
    mapping = apply_org_filter(
        db.query(BranchAccountMapping).filter(
            BranchAccountMapping.org_id == context.org_id,
            BranchAccountMapping.branch_id == branch_id,
            BranchAccountMapping.account_role == account_role,
            BranchAccountMapping.is_deleted.is_(False),
        ),
        BranchAccountMapping,
        context,
    ).populate_existing().with_for_update().one_or_none()
    if mapping is None or mapping.mapping_key != expected_mapping_key:
        raise PostingConflict("Exact account mapping is unavailable")
    revision = _latest(db, context, mapping.mapping_key)
    if revision is None or not revision.is_enabled:
        raise PostingConflict("Account mapping is disabled")
    if revision.version != expected_mapping_version:
        raise PostingConflict("Account mapping changed; refresh before composing")
    return _mapping_read(mapping, revision)
