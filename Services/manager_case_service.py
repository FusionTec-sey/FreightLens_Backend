"""Internal request/review/consume engine; no arbitrary client-authored approvals.

Adapters must load and LOCK authoritative source rows and return their exact
action/scope/version snapshot on every attempt, including retries. Permission
callbacks must authorize the specific action. Inventory policy reviews use a
source-specific HTTP adapter; arbitrary client-authored bindings are not exposed.
"""
from dataclasses import dataclass
import re
from uuid import UUID
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseDecision, ManagerCaseUse
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict, _json_snapshot
from Utils.org_filter import apply_org_filter


@dataclass(frozen=True)
class CaseBinding:
    org_id: int
    action: str
    source_type: str
    source_key: str
    source_version: int
    details: dict

    def snapshot(self):
        if type(self.org_id) is not int or self.org_id <= 0 or type(self.source_version) is not int or self.source_version <= 0:
            raise ValueError("Positive organisation and source version are required")
        if any(not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value)
               for value in (self.action, self.source_type)):
            raise ValueError("Explicit action and source type are required")
        if not isinstance(self.source_key, str) or not self.source_key.strip() or len(self.source_key) > 100:
            raise ValueError("Explicit source key is required")
        snapshot, _ = _json_snapshot({"org_id": self.org_id, "action": self.action, "source_type": self.source_type,
            "source_key": self.source_key, "source_version": self.source_version, "details": self.details})
        return snapshot


def _reason(reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError("An explicit reason of 1-1000 characters is required")


def _query(db, model, context):
    return apply_org_filter(db.query(model).filter(model.org_id == context.org_id,
        model.is_deleted.is_(False)), model, context)


def _current(db, context, binding, load_binding, authorize):
    if not callable(load_binding) or not callable(authorize):
        raise ValueError("A locked source loader and action permission guard are required")
    authorize(db)
    if binding.org_id != context.org_id:
        raise PermissionError("Manager case scope denied")
    current = load_binding(db)
    if not isinstance(current, CaseBinding) or current.snapshot() != binding.snapshot():
        raise PostingConflict("Case source, action or reviewed details changed")


def request_case(factory, context, actor_id, operation_key, *, binding: CaseBinding, reason,
                 load_binding, authorize):
    _reason(reason)
    snapshot = binding.snapshot()
    def guard(db):
        _current(db, context, binding, load_binding, authorize)
    def apply(db):
        row = ManagerCase(org_id=context.org_id, case_key=operation_key, action=binding.action,
            source_type=binding.source_type, source_key=binding.source_key, source_version=binding.source_version,
            binding=snapshot, reason=reason, created_by=actor_id)
        db.add(row); db.flush()
        return PostingEffect({"case_key": str(operation_key), "version": 1, "status": "REQUESTED"},
                             {"kind": "manager.case.requested", "case_key": str(operation_key)})
    return execute_once(factory, context, actor_id, operation_key, "manager.case.request.v1",
                        {"binding": snapshot, "reason": reason}, apply, authorize=guard)


def _locked_case(db, context, key, binding):
    row = _query(db, ManagerCase, context).filter_by(case_key=key).with_for_update().one_or_none()
    if row is None:
        raise PermissionError("Manager case not found")
    if row.binding != binding.snapshot():
        raise PostingConflict("Approval does not match this exact action and source version")
    return row


def review_case(factory, context, actor_id, operation_key, *, case_key: UUID, binding: CaseBinding,
                expected_version: int, outcome: str, reason, load_binding, authorize):
    _reason(reason)
    if type(expected_version) is not int or expected_version != 1 or outcome not in ("APPROVED", "REJECTED"):
        raise ValueError("Review requires case version 1 and APPROVED or REJECTED")
    def guard(db):
        # Source then case lock order is shared with consumption.
        _current(db, context, binding, load_binding, authorize)
        row = _locked_case(db, context, case_key, binding)
        if row.created_by == actor_id:
            raise PermissionError("Requestors cannot review their own case")
    def apply(db):
        row = _locked_case(db, context, case_key, binding)
        if _query(db, ManagerCaseDecision, context).filter_by(case_id=row.id).first():
            raise PostingConflict("Case has already been reviewed")
        db.add(ManagerCaseDecision(org_id=context.org_id, case_id=row.id, outcome=outcome,
                                  reason=reason, created_by=actor_id))
        return PostingEffect({"case_key": str(case_key), "version": 2, "status": outcome},
                             {"kind": "manager.case.reviewed", "case_key": str(case_key), "outcome": outcome})
    return execute_once(factory, context, actor_id, operation_key, "manager.case.review.v1",
        {"case_key": str(case_key), "binding": binding.snapshot(), "expected_version": expected_version,
         "outcome": outcome, "reason": reason}, apply, authorize=guard)


def consume_case(db, context, actor_id, operation_key, *, case_key: UUID, binding: CaseBinding,
                 load_binding, authorize):
    """Call inside the domain effect, never outside its atomic posting transaction.

    Deferred posting FK and unique case-use enforce one committed business use.
    Replay belongs to the outer posting receipt, not a second call to this method.
    """
    if not db.in_transaction():
        raise ValueError("Case consumption requires an active posting transaction")
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Manager case scope denied")
    _current(db, context, binding, load_binding, authorize)
    row = _locked_case(db, context, case_key, binding)
    decision = _query(db, ManagerCaseDecision, context).filter_by(case_id=row.id).one_or_none()
    if decision is None or decision.outcome != "APPROVED":
        raise PermissionError("This action requires an approved case")
    if _query(db, ManagerCaseUse, context).filter_by(case_id=row.id).first():
        raise PostingConflict("Approval has already been consumed")
    db.add(ManagerCaseUse(org_id=context.org_id, case_id=row.id, operation_key=operation_key, created_by=actor_id))
    db.flush()
