"""Post one reviewed non-serial quarantine-to-damaged transition."""
from decimal import Decimal
from uuid import UUID

from Services.inventory_posting_service import PostingConflict
from Services.inventory_quantity_service import QuantityBreakdown
from Services.manager_case_service import CaseBinding, consume_case
from Services.stock_condition_service import (
    ACTION,
    MOVEMENT_KIND,
    SOURCE_TYPE,
    reload_return_condition_binding,
)
from Services.stock_ledger_service import _locked_balance, _post_stock, _record, _snapshot


def transition_return_condition(factory, context, actor_id, operation_key, *,
                                case_key, binding, reason, authority, authorize):
    if not isinstance(operation_key, UUID) or not operation_key.int:
        raise ValueError("A nonzero operation key is required")
    if not isinstance(case_key, UUID) or not case_key.int:
        raise ValueError("A nonzero case key is required")
    if not isinstance(binding, CaseBinding) or binding.action != ACTION or binding.source_type != SOURCE_TYPE:
        raise ValueError("Exact return-stock condition binding required")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValueError("A reason of 1-500 characters is required")
    details = binding.details
    request = {
        "case_key": str(case_key),
        "binding": binding.snapshot(),
        "reason": reason,
    }

    def load(db):
        return reload_return_condition_binding(
            db, context, binding, replay_operation=operation_key,
            current_case_key=case_key)

    def apply(db):
        consume_case(
            db, context, actor_id, operation_key,
            case_key=case_key, binding=binding, load_binding=load, authorize=authorize)
        balance = _locked_balance(db, context, details["balance_id"])
        before = _snapshot(balance)
        expected = QuantityBreakdown(
            Decimal(details["before_on_hand"]), Decimal(details["before_reserved"]),
            Decimal(details["before_damaged"]), Decimal(details["before_quarantined"]),
        )
        if before != expected or balance.version != binding.source_version:
            raise PostingConflict("Reviewed return-stock condition source changed")
        if balance.tracking_policy not in ("UNTRACKED", "BATCH"):
            raise ValueError("Serial stock requires exact serial-identity condition workflow")
        quantity = Decimal(details["quantity"])
        target = QuantityBreakdown(
            before.on_hand, before.reserved,
            before.damaged + quantity, before.quarantined - quantity)
        balance.damaged = target.damaged
        balance.quarantined = target.quarantined
        balance.version += 1
        balance.updated_by = actor_id
        return _record(db, balance, operation_key, actor_id, MOVEMENT_KIND, reason, before)

    return _post_stock(
        factory, context, actor_id, operation_key, "stock.condition-transition.v1",
        request, apply, authority=authority, authorize=authorize,
        balance_id=details["balance_id"])
