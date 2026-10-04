"""Reviewed below-floor pricing cases bound to exact draft/configuration versions.

Approval records the manager decision only. The eventual atomic sale must re-load
this same binding and consume the case in its posting transaction.
"""
from datetime import datetime, timezone
from uuid import UUID

from Model.containermgmt.Inventory.ManagerCase import (
    ManagerCase, ManagerCaseDecision, ManagerCaseUse,
)
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.sales_intent_service import get_sales_intent
from Services.sales_pricing_preview_service import (
    preview_sales_pricing, transaction_pricing_payload,
)
from Utils.org_filter import apply_org_filter

ACTION = "sales.price-floor.approve"
SOURCE = "sales.intent"


def floor_binding_from_preview(context, document_key, draft_version, preview):
    """Build the one exact binding without resolving pricing a second time."""
    key = UUID(str(document_key))
    floor_lines = [line for line in preview["lines"]
        if line["requires_floor_approval"]]
    if not floor_lines:
        raise ValueError("Current pricing does not require a below-floor approval")
    pricing, fingerprint = transaction_pricing_payload(preview)
    details = {"document_key": str(key), "draft_version": draft_version,
        "pricing": pricing, "floor_line_count": len(floor_lines),
        "pricing_fingerprint": fingerprint}
    return CaseBinding(context.org_id, ACTION, SOURCE, str(key), draft_version,
        details)


def floor_binding(db, context, document_key, *, expected_draft_version=None,
                  authorize, now=None):
    if not callable(authorize):
        raise ValueError("Sales draft and floor-approval authorization required")
    authorize(db)
    key = UUID(str(document_key))
    draft = get_sales_intent(db, context, key, authorize=authorize)
    if expected_draft_version is not None and draft["version"] != expected_draft_version:
        raise PostingConflict("Sales draft changed; refresh pricing before requesting approval")
    preview = preview_sales_pricing(db, context, draft,
        priced_at=now or datetime.now(timezone.utc), authorize=authorize)
    return floor_binding_from_preview(context, key, draft["version"], preview)


def request_floor_case(db, context, actor_id, payload, *, authorize):
    def load(session):
        return floor_binding(session, context, payload.document_key,
            expected_draft_version=payload.expected_draft_version, authorize=authorize)
    binding = load(db)
    return request_case(db, context, actor_id, payload.operation_key,
        binding=binding, reason=payload.reason, load_binding=load, authorize=authorize)


def scoped_floor_cases(db, context):
    return apply_org_filter(db.query(ManagerCase).filter_by(org_id=context.org_id,
        action=ACTION, source_type=SOURCE, is_deleted=False), ManagerCase, context)


def require_approved_floor_case(db, context, case_key, binding, *, authorize):
    """Validate but never consume the exact approval for prepared pricing."""
    if not callable(authorize) or not isinstance(binding, CaseBinding):
        raise ValueError("Exact floor approval authorization and binding are required")
    authorize(db)
    row = scoped_floor_cases(db, context).filter_by(
        case_key=case_key).with_for_update().one_or_none()
    if row is None:
        raise PermissionError("Approved price-floor case not found")
    if row.binding != binding.snapshot():
        raise PostingConflict("Price-floor approval does not match these exact pricing inputs")
    decision = apply_org_filter(db.query(ManagerCaseDecision).filter_by(
        org_id=context.org_id, case_id=row.id, is_deleted=False),
        ManagerCaseDecision, context).one_or_none()
    if decision is None or decision.outcome != "APPROVED":
        raise PermissionError("These prices require an approved price-floor case")
    used = apply_org_filter(db.query(ManagerCaseUse).filter_by(
        org_id=context.org_id, case_id=row.id, is_deleted=False),
        ManagerCaseUse, context).first()
    if used is not None:
        raise PostingConflict("Price-floor approval has already been consumed")
    return row


def review_floor_case(db, context, actor_id, operation_key, *, case_key,
                      expected_version, outcome, reason, authorize):
    row = scoped_floor_cases(db, context).filter_by(case_key=case_key).one_or_none()
    if row is None:
        raise LookupError("Price-floor case not found")
    binding = CaseBinding(**row.binding)

    def load(session):
        return floor_binding(session, context, UUID(binding.source_key),
            expected_draft_version=binding.source_version, authorize=authorize)

    return review_case(db, context, actor_id, operation_key, case_key=case_key,
        binding=binding, expected_version=expected_version, outcome=outcome,
        reason=reason, load_binding=load, authorize=authorize)
