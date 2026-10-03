"""Save unposted evidence declarations using the authoritative allocation loader.

A charge reference is declared evidence, not proof of invoice validity or a unique
supplier invoice. Independent review and charge deduplication precede any posting.
"""
from decimal import Decimal
from Model.containermgmt.Inventory.CostAllocation import CostAllocationProposal
from Schema.InventoryValuationSchema import CostAllocationPreview
from Services.inventory_posting_service import execute_once, PostingEffect
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding
from Utils.org_filter import apply_org_filter


def load_allocation_binding(db, context, pool_id, key, *, load_snapshot, reviewer_id=None):
    """Lock the immutable declaration; recheck authoritative eligibility on retries."""
    if not callable(load_snapshot):
        raise ValueError('An authoritative allocation loader is required')
    row = apply_org_filter(db.query(CostAllocationProposal).filter_by(org_id=context.org_id,
        cost_pool_id=pool_id, proposal_key=key, is_deleted=False), CostAllocationProposal,
        context).with_for_update().one_or_none()
    if row is None: raise LookupError('Cost allocation proposal not found')
    if reviewer_id == row.created_by:
        raise PermissionError('Proposal creators cannot review their own allocation')
    current = CostAllocationPreview.model_validate(load_snapshot(db, row.manifest)).model_dump(mode='json')
    if current != row.snapshot:
        raise PostingConflict('Allocation sources or reviewed details changed')
    return CaseBinding(context.org_id, 'inventory.cost.allocate', 'inventory.cost-allocation', str(key), 1,
        dict(manifest=row.manifest, snapshot=row.snapshot, creator_id=row.created_by))


def save_allocation_proposal(factory, context, actor_id, pool_id, payload, *, authorize, load_snapshot):
    if not callable(authorize) or not callable(load_snapshot):
        raise ValueError('Cost proposal requires permission and authoritative source loaders')
    manifest = payload.model_dump(mode='json', exclude={'operation_key'})
    manifest['valuation_ids'] = sorted(manifest['valuation_ids'])
    manifest['total_scr'] = format(Decimal(manifest['total_scr']), '.6f')
    current = {}
    def guard(db):
        authorize(db)
        # The loader reuses the protected exact pool/company/source calculation.
        current['snapshot'] = CostAllocationPreview.model_validate(load_snapshot(db)).model_dump(mode='json')
    def apply(db):
        db.add(CostAllocationProposal(org_id=context.org_id, proposal_key=payload.operation_key,
            cost_pool_id=pool_id, manifest=manifest, snapshot=current['snapshot'], created_by=actor_id))
        db.flush()
        return PostingEffect({'proposal_key': str(payload.operation_key), 'status': 'PROPOSED', 'posting_enabled': False},
            {'kind': 'inventory.cost-allocation.proposed', 'proposal_key': str(payload.operation_key)})
    return execute_once(factory, context, actor_id, payload.operation_key, 'inventory.cost-allocation.propose.v1',
        {'cost_pool_id': pool_id, **manifest}, apply, authorize=guard)
