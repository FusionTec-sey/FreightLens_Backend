"""Internal charge coordinator; no HTTP writer or implicit central authority.

The runtime adapter must prepare pinned bytes outside this transaction and supply
permission and central-writer guards. Guards run again on retries. No callback may
commit or perform external I/O; shared-session results remain provisional.
"""
from uuid import UUID
from Services.cost_content_preparation_service import PreparedChargeContent, prepare_charge_content
from Services.cost_charge_review_service import (
    ACTION, CHARGE_POSTING_KIND, approved_charge_evidence, charge_review_binding, reviewed_charge_binding)
from Schema.CostChargeReviewSchema import CostChargeDeclaration
from Services.cost_charge_use_service import check_cost_charge, consume_cost_charge
from Services.charge_valuation_service import append_allocated_charge_values
from Services.manager_case_service import consume_case
from Services.inventory_posting_service import execute_once, PostingEffect
from Services.posting_authority_service import CostPoolAuthorityClaim, require_cost_pool_authority
from Model.containermgmt.Inventory.CostAllocation import CostAllocationProposal
from Utils.org_filter import apply_org_filter


def _authority_identity(claim, context):
    if not isinstance(claim, CostPoolAuthorityClaim) or claim.org_id != context.org_id:
        raise PermissionError('Trusted central cost-pool claim required')
    return dict(org_id=claim.org_id, cost_pool_id=claim.cost_pool_id,
                node_key=str(claim.node_key), epoch=claim.epoch)


def _require_charge_authority(db, context, claim, proposal_key):
    require_cost_pool_authority(db, context, claim, cost_pool_id=claim.cost_pool_id)
    proposal = apply_org_filter(db.query(CostAllocationProposal.proposal_key).filter_by(
        org_id=context.org_id, cost_pool_id=claim.cost_pool_id, proposal_key=proposal_key,
        is_deleted=False), CostAllocationProposal, context).first()
    if proposal is None: raise PermissionError('Charge proposal outside central authority scope')


def prepare_and_post_allocated_charge(factory, context, actor_id, operation_key, *,
        proposal_key, case_key, expected_versions, authority_claim, authorize, require_central_authority,
        load_allocation, storage, max_bytes):
    """Fresh version verification, then atomic posting; never accepts client hashes.

    Factory-owned only: callers must not wrap this operation in a transaction.
    The persisted approved case is resolved internally in the exact company scope.
    A retry re-reads the ORIGINAL versions; unavailable evidence blocks replay.
    """
    if not all(callable(fn) for fn in (factory, authorize, require_central_authority,
                                       load_allocation)):
        raise ValueError('Session factory and explicit trusted guards/loaders required')
    if any(not isinstance(key, UUID) or not key.int for key in (operation_key, proposal_key, case_key)):
        raise ValueError('Nonzero operation, proposal and case identities required')
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Charge company scope denied')
    _authority_identity(authority_claim, context)

    def permissions(db):
        authorize(db)
        _require_charge_authority(db, context, authority_claim, proposal_key)
        require_central_authority(db)

    def reviewed(db):
        return reviewed_charge_binding(db, context, case_key, proposal_key,
            authorize=permissions, load_allocation=load_allocation,
            replay_operation_key=operation_key, replay_actor_id=actor_id)

    prepared = prepare_charge_content(factory, authorize=permissions, load_binding=reviewed,
                                     storage=storage, max_bytes=max_bytes)
    return post_allocated_charge(factory, context, actor_id, operation_key,
        proposal_key=proposal_key, case_key=case_key, prepared=prepared,
        expected_versions=expected_versions, authority_claim=authority_claim, authorize=authorize,
        require_central_authority=require_central_authority, load_allocation=load_allocation)


def post_allocated_charge(factory, context, actor_id, operation_key, *, proposal_key,
                          case_key, prepared, expected_versions, authority_claim, authorize,
                          require_central_authority, load_allocation):
    if not all(callable(fn) for fn in (authorize, require_central_authority, load_allocation)):
        raise ValueError('Explicit permission, central authority and allocation guards required')
    authority = _authority_identity(authority_claim, context)
    if any(not isinstance(key, UUID) or not key.int for key in (proposal_key, case_key)):
        raise ValueError('Nonzero proposal and case identities required')
    if not isinstance(prepared, PreparedChargeContent):
        raise ValueError('Server-prepared version-pinned content required')
    source = prepared.source
    if (source.org_id != context.org_id or source.action != ACTION or source.source_version != 2
            or source.source_type != 'inventory.cost-allocation' or source.source_key != str(proposal_key)):
        raise PermissionError('Prepared evidence scope denied')
    if (not isinstance(expected_versions, dict) or not 1 <= len(expected_versions) <= 100
            or any(type(key) is not int or key <= 0 or type(value) is not int or value < 1
                   for key, value in expected_versions.items())):
        raise ValueError('Bounded positive product stream versions required')
    versions = dict(expected_versions)
    declaration = CostChargeDeclaration(**source.details['declaration'])
    content = prepared.content_map()
    request = dict(proposal_key=str(proposal_key), case_key=str(case_key),
        binding=source.snapshot(), authority=authority,
        expected_versions={str(key): versions[key] for key in sorted(versions)})
    loaded = {}

    def permissions(db):
        authorize(db)
        _require_charge_authority(db, context, authority_claim, proposal_key)
        require_central_authority(db)

    def binding(db):
        current = charge_review_binding(db, context, proposal_key, declaration,
            authorize=permissions, load_allocation=load_allocation, document_content=content)
        prepared.require_current(current)
        return current

    def evidence(db):
        return approved_charge_evidence(db, context, case_key, proposal_key,
            authorize=permissions, load_allocation=load_allocation, document_content=content,
            replay_operation_key=operation_key, replay_actor_id=actor_id)

    def guard(db):
        permissions(db)
        loaded['binding'] = binding(db)
        loaded['evidence'] = evidence(db)
        check_cost_charge(db, context, actor_id, operation_key, proposal_key, loaded['evidence'],
            authorize=permissions, load_evidence=evidence)

    def effect(db):
        consume_cost_charge(db, context, actor_id, operation_key, proposal_key, loaded['evidence'],
            authorize=permissions, load_evidence=evidence)
        consume_case(db, context, actor_id, operation_key, case_key=case_key,
            binding=loaded['binding'], load_binding=binding, authorize=permissions)
        ids = append_allocated_charge_values(db, context, actor_id, operation_key,
            expected_versions=versions, authorize=permissions)
        return PostingEffect(dict(valuation_ids=ids, proposal_key=str(proposal_key),
            case_key=str(case_key), status='UNRECONCILED'),
            dict(kind='inventory.valuation.charge-recorded', valuation_ids=ids,
                 proposal_key=str(proposal_key)))

    return execute_once(factory, context, actor_id, operation_key, CHARGE_POSTING_KIND,
                        request, effect, authorize=guard)
