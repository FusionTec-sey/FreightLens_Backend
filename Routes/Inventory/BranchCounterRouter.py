from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
from Schema.BranchCounterSchema import CounterRead, CounterSave
from Schema.InventoryLocationSchema import LocationPage
from Routes.Inventory.BranchSettingsRouter import branch_scope
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission
from Services.settings_revision_service import (lock_settings_operation, require_matching_retry,
    require_current_version, SettingsConflict)
from Services.default_stock_area_service import require_owned_stock_area

BranchCounterRouter = APIRouter(prefix="/inventory/branches", tags=["Branch Counters"])


def counters(db, context):
    return apply_org_filter(db.query(BranchCounter).filter(BranchCounter.org_id == context.org_id,
        BranchCounter.is_deleted.is_(False)), BranchCounter, context)


def revisions(db, context):
    return apply_org_filter(db.query(CounterSettingsRevision).filter(CounterSettingsRevision.org_id == context.org_id,
        CounterSettingsRevision.is_deleted.is_(False)), CounterSettingsRevision, context)


def result(counter, revision):
    return CounterRead(id=counter.id, branch_id=counter.branch_id, counter_key=counter.counter_key,
                       code=counter.code, version=revision.version, config=revision.config)


@BranchCounterRouter.get("/{branch_id}/counters", response_model=LocationPage[CounterRead])
def list_counters(branch_id: int, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                  db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                  user=Depends(require_permission("View_Product"))):
    branch_scope(db, context, branch_id)
    query = counters(db, context).filter_by(branch_id=branch_id)
    total = query.count()
    # Limit counter identities first, then fetch latest revisions in one grouped
    # query; no N+1 queries and no full-history materialization.
    rows = query.order_by(BranchCounter.code, BranchCounter.id).offset((page - 1) * limit).limit(limit).all()
    ids = [row.id for row in rows]
    latest = revisions(db, context).filter(CounterSettingsRevision.counter_id.in_(ids)).with_entities(
        CounterSettingsRevision.counter_id, func.max(CounterSettingsRevision.version).label("version")
        ).group_by(CounterSettingsRevision.counter_id).subquery()
    configs = revisions(db, context).join(latest, (CounterSettingsRevision.counter_id == latest.c.counter_id) &
        (CounterSettingsRevision.version == latest.c.version)).all() if ids else []
    by_id = {row.counter_id: row for row in configs}
    return {"items": [result(row, by_id[row.id]) for row in rows], "total": total, "page": page,
            "pages": max(1, (total + limit - 1) // limit), "limit": limit}


@BranchCounterRouter.put("/{branch_id}/counters/{counter_key}", response_model=CounterRead)
def save_counter(branch_id: int, counter_key: UUID, payload: CounterSave, db: Session = Depends(get_db),
                 context: OrgContext = Depends(get_org_context), user=Depends(require_permission("Manage_BranchSettings"))):
    if not counter_key.int:
        raise HTTPException(422, "Counter key must be nonzero")
    try:
        lock_settings_operation(db, "counter-settings", context.org_id, payload.operation_key)
        branch_scope(db, context, branch_id, lock=True)
        if payload.config.default_stock_location_id is not None:
            try: require_owned_stock_area(db, context, branch_id, payload.config.default_stock_location_id)
            except LookupError as error: raise HTTPException(404, str(error)) from error
        counter = counters(db, context).filter_by(counter_key=counter_key).one_or_none()
        if counter and counter.branch_id != branch_id:
            raise HTTPException(404, "Counter not found in this branch")
        if counter and counter.code != payload.code:
            raise HTTPException(409, "Counter code is permanent; edit the display name instead")
        prior = revisions(db, context).filter_by(operation_key=payload.operation_key).one_or_none()
        config = payload.config.model_dump(mode="json", exclude_none=True)
        if prior:
            require_matching_retry(prior, target_matches=counter is not None and prior.counter_id == counter.id,
                expected_version=payload.expected_version, actor_id=user.id, config=config,
                message="Operation key belongs to another counter change")
            response = result(counter, prior)
        else:
            latest = revisions(db, context).filter_by(counter_id=counter.id).order_by(CounterSettingsRevision.version.desc()).first() if counter else None
            require_current_version(latest, payload.expected_version, "Counter changed; reload and review before saving")
            if counter is None:
                counter = BranchCounter(org_id=context.org_id, branch_id=branch_id, counter_key=counter_key,
                    code=payload.code, created_by=user.id)
                db.add(counter); db.flush()
            revision = CounterSettingsRevision(org_id=context.org_id, counter_id=counter.id,
                version=payload.expected_version + 1, operation_key=payload.operation_key, config=config, created_by=user.id)
            db.add(revision); db.flush()
            response = result(counter, revision)
        db.commit()
        return response
    except SettingsConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Counter identity or code conflicts; reload and review") from exc
    except Exception:
        db.rollback()
        raise
