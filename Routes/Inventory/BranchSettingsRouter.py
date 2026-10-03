"""Versioned branch configuration; no public checkout activation."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.BranchSettings import BranchSettingsRevision
from Schema.BranchSettingsSchema import BranchSettingsConfig, BranchSettingsRead, BranchSettingsSave
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission
from Services.settings_revision_service import (lock_settings_operation, require_matching_retry,
    require_current_version, SettingsConflict)

BranchSettingsRouter = APIRouter(prefix="/inventory/branches", tags=["Branch Settings"])


def branch_scope(db, context, branch_id, lock=False):
    query = apply_org_filter(db.query(InventoryBranch).filter(
        InventoryBranch.id == branch_id, InventoryBranch.org_id == context.org_id,
        InventoryBranch.is_deleted.is_(False)), InventoryBranch, context)
    row = query.populate_existing().with_for_update().one_or_none() if lock else query.one_or_none()
    if row is None:
        raise HTTPException(404, "Branch not found")
    if lock and not row.is_active:
        raise HTTPException(409, "Inactive branch settings cannot be changed")
    return row


def revisions(db, context):
    return apply_org_filter(db.query(BranchSettingsRevision).filter(
        BranchSettingsRevision.org_id == context.org_id,
        BranchSettingsRevision.is_deleted.is_(False)), BranchSettingsRevision, context)


def result(branch_id, row):
    config = BranchSettingsConfig.model_validate(row.config) if row else BranchSettingsConfig()
    missing = config.missing()
    return BranchSettingsRead(branch_id=branch_id, version=row.version if row else 0,
        status="NOT_CONFIGURED" if row is None else "INCOMPLETE" if missing else "CONFIGURED",
        config=config, missing_fields=missing)


@BranchSettingsRouter.get("/{branch_id}/settings", response_model=BranchSettingsRead)
def read_settings(branch_id: int, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                  user=Depends(require_permission("View_Product"))):
    branch_scope(db, context, branch_id)
    row = revisions(db, context).filter_by(branch_id=branch_id).order_by(BranchSettingsRevision.version.desc()).first()
    return result(branch_id, row)


@BranchSettingsRouter.put("/{branch_id}/settings", response_model=BranchSettingsRead)
def save_settings(branch_id: int, payload: BranchSettingsSave, db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context),
                  user=Depends(require_permission("Manage_BranchSettings"))):
    try:
        # Serialize key reuse across different branches before taking branch locks.
        lock_settings_operation(db, "branch-settings", context.org_id, payload.operation_key)
        branch_scope(db, context, branch_id, lock=True)
        config = payload.config.model_dump(mode="json")
        previous = revisions(db, context).filter_by(operation_key=payload.operation_key).one_or_none()
        if previous:
            require_matching_retry(previous, target_matches=previous.branch_id == branch_id,
                expected_version=payload.expected_version, actor_id=user.id, config=config,
                message="Operation key belongs to another settings change")
            response = result(branch_id, previous)
        else:
            latest = revisions(db, context).filter_by(branch_id=branch_id).order_by(BranchSettingsRevision.version.desc()).first()
            require_current_version(latest, payload.expected_version, "Settings changed; reload and review before saving")
            row = BranchSettingsRevision(org_id=context.org_id, branch_id=branch_id,
                version=payload.expected_version + 1, operation_key=payload.operation_key,
                config=config, created_by=user.id)
            db.add(row); db.flush()
            response = result(branch_id, row)
        db.commit()
        return response
    except SettingsConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
