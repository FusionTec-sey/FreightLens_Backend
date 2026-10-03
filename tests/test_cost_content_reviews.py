from uuid import uuid4
import pytest
from pydantic import ValidationError
from Schema.DocumentContentSchema import DocumentContentFingerprint
from Services.cost_charge_review_service import charge_review_binding, approved_charge_evidence
from Services.manager_case_service import request_case, review_case
from Services.inventory_posting_service import PostingConflict
from tests.test_cost_charge_reviews import charge_review, charge, allocation, valued, stock  # noqa: F401


@pytest.fixture
def content_review(charge_review):
    f = charge_review
    f.content = {str(f.evidence.document_id): DocumentContentFingerprint(policy='blob-sha256-v1',
        bucket='synthetic-only', object_key='synthetic/not-a-real-file', version_id='v1', size=7, sha256='a' * 64)}
    f.content_case = uuid4()
    def load(db, content=None):
        return charge_review_binding(db, f.context, f.payload.operation_key, f.declaration,
            authorize=lambda session: None, load_allocation=f.load_allocation,
            document_content=f.content if content is None else content)
    f.content_load = load
    with f.factory.begin() as db:
        f.content_binding = load(db)
        request_case(db, f.context, f.actor, f.content_case, binding=f.content_binding,
            reason='Synthetic pinned content', load_binding=load, authorize=lambda session: None)
        review_case(db, f.context, f.reviewer, uuid4(), case_key=f.content_case,
            binding=f.content_binding, expected_version=1, outcome='APPROVED', reason='Synthetic reviewed bytes',
            load_binding=load, authorize=lambda session: None)
    def evidence(content=None, case_key=None):
        with f.factory.begin() as db:
            return approved_charge_evidence(db, f.context, case_key or f.content_case, f.payload.operation_key,
                authorize=lambda session: None, load_allocation=f.load_allocation,
                document_content=f.content if content is None else content)
    f.content_evidence = evidence
    return f


def test_persisted_content_review_produces_exact_evidence(content_review):
    f = content_review
    assert f.content_binding.source_version == 2
    assert f.content_binding.details['document_content'][str(f.evidence.document_id)]['version_id'] == 'v1'
    evidence = f.content_evidence()
    assert evidence.amount_scr == '12.340000'
    assert evidence.document_id == f.evidence.document_id
    assert evidence == f.content_evidence()


@pytest.mark.parametrize('changes', [{'sha256': 'b' * 64}, {'version_id': 'replacement'},
    {'bucket': 'other'}, {'object_key': 'other/key'}, {'size': 8}])
def test_changed_content_identity_invalidates_approval(content_review, changes):
    f = content_review
    changed = {key: value.model_copy(update=changes) for key, value in f.content.items()}
    with pytest.raises(PostingConflict): f.content_evidence(changed)


def test_missing_extra_and_untyped_content_are_denied(content_review):
    f = content_review
    for content in ({}, {**f.content, str(uuid4()): next(iter(f.content.values()))}):
        with pytest.raises(PostingConflict): f.content_evidence(content)
    with pytest.raises(ValueError):
        f.content_evidence({key: value.model_dump() for key, value in f.content.items()})


def test_legacy_case_cannot_be_upgraded_by_supplying_content(content_review):
    f = content_review; f.decide()
    with pytest.raises(PermissionError): f.content_evidence(case_key=f.case_key)


def test_no_verified_content_callback_result_means_no_financial_evidence(content_review):
    f = content_review
    with f.factory.begin() as db, pytest.raises(PermissionError):
        approved_charge_evidence(db, f.context, f.content_case, f.payload.operation_key,
            authorize=lambda session: None, load_allocation=f.load_allocation)


def test_content_case_remains_single_use(content_review):
    from Services.manager_case_service import consume_case
    from Services.inventory_posting_service import execute_once, PostingEffect
    f = content_review; key = uuid4()
    def consume(db):
        consume_case(db, f.context, f.actor, key, case_key=f.content_case, binding=f.content_binding,
            load_binding=f.content_load, authorize=lambda session: None)
        return PostingEffect({}, {'kind': 'test.content-review-use'})
    execute_once(f.factory, f.context, f.actor, key, 'test.content-review-use', {}, consume, authorize=lambda session: None)
    with pytest.raises(PostingConflict): f.content_evidence()


def test_permission_revocation_denies_content_evidence(content_review):
    f = content_review
    def deny(db): raise PermissionError('revoked')
    with f.factory.begin() as db, pytest.raises(PermissionError, match='revoked'):
        approved_charge_evidence(db, f.context, f.content_case, f.payload.operation_key,
            authorize=deny, load_allocation=f.load_allocation, document_content=f.content)


@pytest.mark.parametrize('changes', [{'version_id': 'null'}, {'version_id': ''}, {'size': True},
    {'size': 0}, {'sha256': 'not-a-hash'}, {'object_key': 'bad\nkey'}])
def test_content_contract_rejects_invalid_identity(changes):
    values = dict(policy='blob-sha256-v1', bucket='synthetic', object_key='test/file', version_id='v1', size=1, sha256='a' * 64)
    with pytest.raises(ValidationError): DocumentContentFingerprint(**(values | changes))
