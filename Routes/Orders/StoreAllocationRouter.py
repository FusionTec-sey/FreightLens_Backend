"""Opt-in local store allocation; clients cannot supply node authority or dates."""
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Orders.SalesIntent import SalesIntentRevision
from Schema.StoreAllocationSchema import StoreAllocationRequest, StoreAllocationRead
from Services.sales_reservation_source_service import owned
from Services.stock_runtime_service import local_stock_runtime, StockRuntimeUnavailable
from Services.branch_action_context_service import require_branch_action_context
from Services.store_allocation_service import allocate_store_stock
from Routes.Inventory.ReservationReleaseCaseRouter import guard, translate
from Routes.Orders.SalesIntentRouter import draft_access
from Routes.MasterData.CustomerRouter import private_response
from auth.module_guard import require_module
from auth.policy import AccessPolicy
from auth.dependencies import get_org_context
from auth.security_guards import require_permission
from Utils.org_filter import OrgContext

StoreAllocationRouter = APIRouter(prefix='/sales/draft-allocations', tags=['Sales draft allocations'],
    dependencies=[Depends(require_module('SALES')), Depends(require_module('INVENTORY')),
        Depends(draft_access), Depends(private_response)])


@StoreAllocationRouter.post('', response_model=StoreAllocationRead)
def allocate_draft(payload: StoreAllocationRequest, db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                   user=Depends(require_permission('Allocate_SalesDraftStock'))):
    try:
        if not db.in_transaction(): db.begin()
        runtime = local_stock_runtime()
        source = owned(db, SalesIntentRevision, context).filter_by(document_key=payload.source.document_key,
            version=payload.source.version).one_or_none()
        if source is None: raise LookupError('Saved draft not found')
        authority = runtime.claim_for(db, context, source.branch_id)
        authorize = guard(policy, 'Allocate_SalesDraftStock')
        action = require_branch_action_context(db, context, branch_id=source.branch_id,
            counter_key=payload.counter_key, branch_version=payload.branch_version,
            counter_version=payload.counter_version, instant=datetime.now(timezone.utc),
            action='CHECKOUT', authorize=authorize)
        result = allocate_store_stock(db, context, user.id, payload.operation_key, source=payload.source,
            action_context=action, quantity=Decimal(payload.quantity), input_unit=payload.input_unit,
            review_at=payload.review_at, reason=payload.reason, authority=authority, authorize=authorize,
            assignment_version=payload.assignment_version)
        db.commit()
        return dict(operation_key=result.operation_key, replayed=result.replayed, **result.result)
    except StockRuntimeUnavailable as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise translate(error) from error
