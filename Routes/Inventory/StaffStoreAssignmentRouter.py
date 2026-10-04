from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.Credentials.users import User
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.StaffStoreAssignment import StaffStoreAssignment as Assignment
from Schema.InventoryLocationSchema import LocationPage
from Schema.StaffStoreAssignmentSchema import StaffStoreRead, StaffStoreSave
from Services.staff_store_assignment_service import eligible_staff, save_staff_store_assignment
from Services.inventory_posting_service import PostingConflict
from Routes.Inventory.BranchSettingsRouter import branch_scope
from Utils.org_filter import OrgContext
from auth.dependencies import get_org_context
from auth.security_guards import require_permission


StaffStoreAssignmentRouter = APIRouter(prefix='/inventory/branches', tags=['Staff working stores'],
    dependencies=[Depends(require_permission('View_User')), Depends(require_permission('View_Product'))])


@StaffStoreAssignmentRouter.get('/{branch_id}/staff-assignments', response_model=LocationPage[StaffStoreRead])
def list_assignments(branch_id: int, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                     db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context)):
    branch_scope(db, context, branch_id)
    members = eligible_staff(db, context)
    total = members.count()
    latest = select(func.max(Assignment.version)).where(Assignment.org_id == context.org_id,
        Assignment.user_id == User.id, Assignment.is_deleted.is_(False)).correlate(User).scalar_subquery()
    rows = members.outerjoin(Assignment, (Assignment.user_id == User.id) &
        (Assignment.org_id == context.org_id) & (Assignment.version == latest) & Assignment.is_deleted.is_(False))
    rows = rows.outerjoin(InventoryBranch, (InventoryBranch.id == Assignment.branch_id) &
        (InventoryBranch.org_id == context.org_id)).add_columns(Assignment.version, Assignment.branch_id,
        Assignment.counter_id, Assignment.is_enabled, InventoryBranch.name).order_by(User.username, User.id)
    items = [dict(user_id=r.id, username=r.username, version=r.version or 0, branch_name=r.name,
        config=None if r.version is None else dict(branch_id=r.branch_id, counter_id=r.counter_id, is_enabled=r.is_enabled))
        for r in rows.offset((page-1)*limit).limit(limit).all()]
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total+limit-1)//limit))


@StaffStoreAssignmentRouter.put('/{branch_id}/staff-assignments/{user_id}', response_model=StaffStoreRead,
    dependencies=[Depends(require_permission('Manage_BranchSettings'))])
def save_assignment(branch_id: int, user_id: int, payload: StaffStoreSave, db: Session = Depends(get_db),
                    context: OrgContext = Depends(get_org_context), actor=Depends(require_permission('Edit_User'))):
    if payload.config.branch_id != branch_id: raise HTTPException(422, 'Assignment must match the selected store')
    try:
        if not db.in_transaction(): db.begin()
        result = save_staff_store_assignment(db, context, actor.id, payload.operation_key, user_id=user_id,
            config=payload.config, expected_version=payload.expected_version, authorize=lambda session: None)
        # Route dependencies above supply RBAC on every attempt, including retry.
        member = eligible_staff(db, context).filter(User.id == user_id).one()
        branch = branch_scope(db, context, branch_id)
        response = StaffStoreRead(**result.result, username=member.username, branch_name=branch.name)
        db.commit()
        return response
    except PostingConflict as error:
        db.rollback(); raise HTTPException(409, str(error)) from error
    except LookupError as error:
        db.rollback(); raise HTTPException(404, str(error)) from error
    except PermissionError as error:
        db.rollback(); raise HTTPException(403, str(error)) from error
    except Exception:
        db.rollback(); raise
