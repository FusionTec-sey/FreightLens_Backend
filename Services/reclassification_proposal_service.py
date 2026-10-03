"""Internal proposal persistence and exact-source adapter for manager cases.

No public writer or conversion consumer. Saving does not require/claim physical
posting authority; conversion must independently enforce node fencing and valuation.
"""
from Model.containermgmt.Inventory.StockReclassification import StockReclassificationProposal
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Schema.StockReclassificationSchema import ReclassificationProposalCreate
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.inventory_quantity_service import QuantityBreakdown
from Services.manager_case_service import CaseBinding
from Services.policy_case_binding_service import load_policy_case_binding
from Services.policy_activation_service import active_policy
from Services.policy_compatibility_service import extends_policy
from Services.stock_ledger_service import _locked_balance
from Services.stock_reclassification_service import BatchAllocation, validate_reclassification
from Utils.org_filter import apply_org_filter


def _source(db, context, payload):
    product_id = apply_org_filter(db.query(StockBalance.product_id).filter(
        StockBalance.id == payload.balance_id, StockBalance.org_id == context.org_id,
        StockBalance.is_deleted.is_(False)), StockBalance, context).scalar()
    if product_id is None:
        raise LookupError("Reclassification source not found")
    # Product -> balance order serializes draft/activation/opening and quantity
    # changes while capturing the proposal; source loader retains locks for review.
    draft = load_policy_case_binding(db, context, product_id)
    active = active_policy(db, context, product_id)
    balance = _locked_balance(db, context, payload.balance_id)
    if (balance.version != payload.expected_balance_version or active is None or
            active.version != payload.expected_active_version or
            draft.source_version != payload.expected_draft_version):
        raise PostingConflict("Stock or policy version changed; prepare a new proposal")
    if not extends_policy(balance.policy_config, active.config):
        raise PostingConflict("Current stock rules do not match the reviewed active policy")
    quantities = QuantityBreakdown(balance.on_hand, balance.reserved, balance.damaged, balance.quarantined)
    validate_reclassification(balance.policy_config, draft.details["config"], quantities,
        batches=tuple(BatchAllocation(row.identity, row.quantities()) for row in payload.batches),
        serials=payload.serials)
    return {"product_id": product_id, "branch_id": balance.branch_id, "location_id": balance.location_id,
        "balance_id": balance.id, "balance_version": balance.version,
        "active_version": active.version, "draft_version": draft.source_version,
        "original_policy": balance.policy_config, "active_policy": active.config,
        "target_policy": draft.details["config"],
        "quantities": {name: format(getattr(quantities, name), ".6f")
            for name in ("on_hand", "reserved", "damaged", "quarantined")}}


def save_proposal(factory, context, actor_id, payload: ReclassificationProposalCreate, *, authorize):
    if not callable(authorize):
        raise ValueError("Proposal save requires an action permission guard")
    manifest = payload.model_dump(mode="json", exclude={"operation_key"})
    source = {}
    def guard(db):
        authorize(db)
        source["snapshot"] = _source(db, context, payload)  # even retries reject stale source
    def apply(db):
        snapshot = source["snapshot"]
        db.add(StockReclassificationProposal(proposal_key=payload.operation_key,
            org_id=context.org_id, balance_id=payload.balance_id, snapshot=snapshot,
            manifest=manifest, created_by=actor_id))
        db.flush()
        return PostingEffect({"proposal_key": str(payload.operation_key), "status": "SAVED",
            "balance_id": payload.balance_id, "balance_version": payload.expected_balance_version},
            {"kind": "inventory.reclassification.proposed", "proposal_key": str(payload.operation_key)})
    return execute_once(factory, context, actor_id, payload.operation_key,
        "inventory.reclassification.propose.v1", manifest, apply, authorize=guard)


def load_proposal_binding(db, context, proposal_key):
    row = apply_org_filter(db.query(StockReclassificationProposal).filter(
        StockReclassificationProposal.proposal_key == proposal_key,
        StockReclassificationProposal.org_id == context.org_id,
        StockReclassificationProposal.is_deleted.is_(False)), StockReclassificationProposal, context).one_or_none()
    if row is None:
        raise LookupError("Reclassification proposal not found")
    payload = ReclassificationProposalCreate(operation_key=proposal_key, **row.manifest)
    if _source(db, context, payload) != row.snapshot:
        raise PostingConflict("Proposal source changed; a new proposal and review are required")
    return CaseBinding(context.org_id, "inventory.stock.reclassify", "inventory.reclassification",
        str(proposal_key), 1, {"snapshot": row.snapshot, "manifest": row.manifest})
