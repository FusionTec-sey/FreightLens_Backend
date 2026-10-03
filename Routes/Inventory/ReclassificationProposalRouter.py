"""Saved proposals only. No physical conversion endpoint is enabled."""
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.StockReclassification import StockReclassificationProposal as Proposal
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Orders.Product import Product
from Schema.StockReclassificationSchema import (ReclassificationProposalCreate, ReclassificationProposalSaved,
    ReclassificationProposalSummary, ReclassificationProposalDetail)
from Schema.InventoryLocationSchema import LocationPage
from Services.reclassification_proposal_service import save_proposal, load_proposal_binding
from Schema.StockReclassificationSchema import ReclassificationReviewRequest
from Schema.ManagerCaseSchema import PolicyCaseRead, PolicyCaseReview, CaseActionRead
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.security_guards import require_permission

ReclassificationProposalRouter = APIRouter(prefix="/inventory/reclassification-proposals",
    tags=["Inventory Reclassification Proposals"])


def translate(error):
    if isinstance(error, LookupError): return HTTPException(404, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


def visible_proposal(db, context, key):
    row = scoped_proposals(db, context).filter(Proposal.proposal_key == key).one_or_none()
    if row is None: raise HTTPException(404, "Reclassification proposal not found")
    return row


def proposal_cases(db, context, key):
    visible_proposal(db, context, key)
    return apply_org_filter(db.query(ManagerCase).filter(ManagerCase.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False), ManagerCase.action == "inventory.stock.reclassify",
        ManagerCase.source_type == "inventory.reclassification", ManagerCase.source_key == str(key)), ManagerCase, context)


@ReclassificationProposalRouter.post("/{proposal_key}/request-review", response_model=CaseActionRead)
def request_proposal_review(proposal_key: UUID, payload: ReclassificationReviewRequest,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission("Request_InventoryReview"))):
    try:
        visible_proposal(db, context, proposal_key)
        load = lambda session: load_proposal_binding(session, context, proposal_key)
        binding = load(db)
        outcome = request_case(db, context, user.id, payload.operation_key, binding=binding,
            reason=payload.reason, load_binding=load, authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReclassificationProposalRouter.get("/{proposal_key}/cases", response_model=LocationPage[PolicyCaseRead])
def list_proposal_reviews(proposal_key: UUID, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        view: Literal["ALL", "NEEDS_MY_REVIEW", "MY_REQUESTS"] = Query("ALL"),
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission("Review_InventoryPolicy"))):
    total, rows = case_page(db, proposal_cases(db, context, proposal_key), user.id, view, page, limit)
    items = []
    for case, decision, used in rows:
        snapshot = case.binding["details"]["snapshot"]
        items.append(PolicyCaseRead(case_key=case.case_key, version=3 if used else 2 if decision else 1,
            status="CONSUMED" if used else decision.outcome if decision else "REQUESTED",
            product_id=snapshot["product_id"], product_name=f"Product #{snapshot['product_id']} / stock #{snapshot['balance_id']}",
            source_version=1, expected_active_version=snapshot["active_version"], config=snapshot["target_policy"],
            reason=case.reason, requestor_id=case.created_by, reviewer_id=decision.created_by if decision else None,
            review_reason=decision.reason if decision else None, requested_at=case.created_at))
    return {"items": items, "total": total, "page": page, "limit": limit, "pages": max(1, (total + limit - 1) // limit)}


@ReclassificationProposalRouter.post("/{proposal_key}/cases/{case_key}/review", response_model=CaseActionRead)
def review_proposal(proposal_key: UUID, case_key: UUID, payload: PolicyCaseReview,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission("Review_InventoryPolicy"))):
    try:
        case = proposal_cases(db, context, proposal_key).filter(ManagerCase.case_key == case_key).one_or_none()
        if case is None: raise HTTPException(404, "Proposal review not found")
        outcome = review_case(db, context, user.id, payload.operation_key, case_key=case_key,
            binding=CaseBinding(**case.binding), expected_version=payload.expected_version,
            outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: load_proposal_binding(session, context, proposal_key), authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


def scoped_proposals(db, context):
    return apply_org_filter(db.query(Proposal).join(StockBalance,
        (StockBalance.id == Proposal.balance_id) & (StockBalance.org_id == Proposal.org_id))
        .join(Product, (Product.id == StockBalance.product_id) & (Product.org_id == Proposal.org_id))
        .join(StockLocation, (StockLocation.id == StockBalance.location_id) & (StockLocation.org_id == Proposal.org_id))
        .join(InventoryBranch, (InventoryBranch.id == StockBalance.branch_id) & (InventoryBranch.org_id == Proposal.org_id))
        .filter(Proposal.org_id == context.org_id, Proposal.is_deleted.is_(False),
            StockBalance.is_deleted.is_(False), Product.is_deleted.is_(False), Product.is_shared.is_(False),
            StockLocation.is_deleted.is_(False), InventoryBranch.is_deleted.is_(False)), Proposal, context)


def summary(row, reason=None):
    return {"proposal_key": row.proposal_key, "balance_id": row.balance_id,
        **{key: row.snapshot[key] for key in ("product_id", "branch_id", "location_id", "balance_version",
                                             "active_version", "draft_version")},
        "target_tracking": row.snapshot["target_policy"]["tracking"],
        "reason": row.manifest["reason"] if reason is None else reason,
        "created_at": row.created_at, "created_by": row.created_by}


@ReclassificationProposalRouter.post("", response_model=ReclassificationProposalSaved)
def create_proposal(payload: ReclassificationProposalCreate, db: Session = Depends(get_db),
                    context: OrgContext = Depends(get_org_context),
                    user=Depends(require_permission("Request_InventoryReview"))):
    try:
        if not db.in_transaction():
            db.begin()
        outcome = save_proposal(db, context, user.id, payload, authorize=lambda session: None)
        db.commit()
        return ReclassificationProposalSaved(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback()
        if isinstance(error, LookupError): raise HTTPException(404, str(error)) from error
        if isinstance(error, PostingConflict): raise HTTPException(409, str(error)) from error
        if isinstance(error, PermissionError): raise HTTPException(403, str(error)) from error
        if isinstance(error, ValueError): raise HTTPException(422, str(error)) from error
        raise


@ReclassificationProposalRouter.get("", response_model=LocationPage[ReclassificationProposalSummary])
def list_proposals(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                   balance_id: int | None = Query(None, gt=0), db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context), user=Depends(require_permission("View_Product"))):
    query = scoped_proposals(db, context)
    if balance_id is not None:
        query = query.filter(Proposal.balance_id == balance_id)
    total = query.count()
    # Do not load up to100 full 1000-identity manifests for a summary page.
    rows = query.with_entities(Proposal.proposal_key, Proposal.balance_id, Proposal.snapshot,
        Proposal.manifest["reason"].astext.label("reason"), Proposal.created_at, Proposal.created_by
        ).order_by(Proposal.created_at.desc(), Proposal.proposal_key.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"items": [summary(row, row.reason) for row in rows], "total": total, "page": page,
        "pages": max(1, (total + limit - 1) // limit), "limit": limit}


@ReclassificationProposalRouter.get("/{proposal_key}", response_model=ReclassificationProposalDetail)
def read_proposal(proposal_key: UUID, db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context), user=Depends(require_permission("View_Product"))):
    row = scoped_proposals(db, context).filter(Proposal.proposal_key == proposal_key).one_or_none()
    if row is None:
        raise HTTPException(404, "Reclassification proposal not found")
    # Historical read deliberately does not claim current eligibility or take
    # stock locks. Review/posting independently revalidate the immutable source.
    return {**summary(row), "snapshot": row.snapshot,
        "manifest": {"operation_key": row.proposal_key, **row.manifest}}
