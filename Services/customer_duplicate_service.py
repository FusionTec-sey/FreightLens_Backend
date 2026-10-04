"""Exact-profile duplicate assessments through the existing manager-case engine.

Approval confirms the proposed assessment only. It does not retire an identity,
redirect sales references, combine contacts or authorize any balance movement.
"""
from uuid import UUID

from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.CustomerDuplicateSchema import CustomerDuplicateRequest
from Services.customer_profile_service import read_customer_profile
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding, request_case, review_case
from Utils.org_filter import apply_org_filter

ACTION = 'customer.duplicate.assess'
SOURCE = 'customer.identity.pair'


def duplicate_binding(db, context, customer_key, other_customer_key, *, assessment, authorize):
    if not callable(authorize):
        raise ValueError('Customer personal-data and duplicate-review guard required')
    authorize(db)
    if assessment not in ('SAME_CUSTOMER', 'DISTINCT_CUSTOMERS'):
        raise ValueError('Explicit duplicate assessment required')
    keys = sorted((UUID(str(customer_key)), UUID(str(other_customer_key))), key=str)
    if keys[0] == keys[1] or any(not key.int for key in keys):
        raise ValueError('Two distinct nonzero customer identities required')
    # Stable lock order for overlapping pairs; profile edits use the same parents.
    profiles = [read_customer_profile(db, context, key, authorize=authorize, lock=True) for key in keys]
    return CaseBinding(context.org_id, ACTION, SOURCE, ':'.join(str(key) for key in keys), 1,
        {'customers': [{'customer_key': str(profile.customer_key), 'version': profile.version}
                       for profile in profiles], 'assessment': assessment, 'merge_authorized': False})


def request_duplicate_review(db, context, actor_id, payload, *, authorize):
    if not isinstance(payload, CustomerDuplicateRequest):
        raise ValueError('Typed duplicate assessment request required')
    payload = CustomerDuplicateRequest.model_validate(payload.model_dump())

    def load(session):
        current = duplicate_binding(session, context, payload.customer_key, payload.other_customer_key,
            assessment=payload.assessment, authorize=authorize)
        expected = {str(payload.customer_key): payload.expected_customer_version,
                    str(payload.other_customer_key): payload.expected_other_version}
        if any(expected[item['customer_key']] != item['version'] for item in current.details['customers']):
            raise PostingConflict('Customer profile changed; refresh both identities before requesting review')
        return current

    binding = load(db)
    return request_case(db, context, actor_id, payload.operation_key, binding=binding,
                        reason=payload.reason, load_binding=load, authorize=authorize)


def review_duplicate(db, context, actor_id, operation_key, *, case_key, expected_version,
                     outcome, reason, authorize):
    if not callable(authorize):
        raise ValueError('Customer duplicate-review guard required')
    authorize(db)
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Customer company scope denied')
    row = apply_org_filter(db.query(ManagerCase).filter_by(org_id=context.org_id,
        case_key=case_key, action=ACTION, source_type=SOURCE, is_deleted=False),
        ManagerCase, context).one_or_none()
    if row is None:
        raise LookupError('Customer duplicate case not found')
    binding = CaseBinding(**row.binding)

    def load(session):
        pair = binding.details['customers']
        if len(pair) != 2:
            raise ValueError('Invalid duplicate assessment binding')
        return duplicate_binding(session, context, pair[0]['customer_key'], pair[1]['customer_key'],
            assessment=binding.details['assessment'], authorize=authorize)

    # Engine compares every version, rejects self-review and records one decision.
    # An approval deliberately has no consume/execute adapter or merge effect.
    return review_case(db, context, actor_id, operation_key, case_key=case_key,
        binding=binding, expected_version=expected_version, outcome=outcome, reason=reason,
        load_binding=load, authorize=authorize)
