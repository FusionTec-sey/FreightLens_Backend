from contextlib import contextmanager
from uuid import uuid4
from types import SimpleNamespace
import pytest
from Services.charge_posting_service import prepare_and_post_allocated_charge
from Services.inventory_posting_service import PostingConflict
from tests.test_charge_posting import posting  # noqa: F401
from tests.test_cost_content_reviews import content_review  # noqa: F401
from tests.test_cost_charge_reviews import charge_review, charge, allocation, valued, stock  # noqa: F401


@pytest.fixture
def prepared_post(posting):
    f = posting
    f.sessions = []; f.reads = []; f.after_read = lambda: None
    class Factory:
        def __call__(self):
            session = f.factory(); f.sessions.append(session)
            return session
        @contextmanager
        def begin(self):
            with f.factory.begin() as session:
                f.sessions.append(session)
                yield session
    f.tracked_factory = Factory()
    def read(key, **kwargs):
        assert all(not session.in_transaction() for session in f.sessions)
        f.reads.append((key, kwargs))
        f.after_read()
        return next(iter(f.content.values())).model_dump()
    f.storage = SimpleNamespace(bucket_name='synthetic-only', fingerprint_file_version=read)
    def post(**changes):
        params = dict(proposal_key=f.payload.operation_key, case_key=f.content_case,
            expected_versions={f.products[0]: 1}, authority_claim=f.central_claim, authorize=lambda db: None,
            require_central_authority=lambda db: None,
            load_allocation=f.load_allocation, storage=f.storage, max_bytes=100)
        params.update(changes)
        return prepare_and_post_allocated_charge(f.tracked_factory, f.context, f.actor, f.key, **params)
    f.prepared_post = post
    return f


def test_full_preparation_and_posting_reverify_original_on_retry(prepared_post):
    f = prepared_post
    assert not f.prepared_post().replayed
    assert f.prepared_post().replayed
    assert len(f.reads) == 2
    assert all(options == {'max_bytes': 100, 'version_id': 'v1'} for _, options in f.reads)


@pytest.mark.parametrize('guard', ['authorize', 'require_central_authority'])
def test_denied_authority_never_reads_storage(prepared_post, guard):
    f = prepared_post
    def deny(db): raise PermissionError('Synthetic denial')
    with pytest.raises(PermissionError): f.prepared_post(**{guard: deny})
    assert not f.reads and f.content_evidence()


@pytest.mark.parametrize('wrong', ['legacy', 'missing', 'proposal'])
def test_wrong_case_binding_never_reads_storage(prepared_post, wrong):
    f = prepared_post
    with pytest.raises(PermissionError):
        f.prepared_post(**({'proposal_key': uuid4()} if wrong == 'proposal' else
                          {'case_key': f.case_key if wrong == 'legacy' else uuid4()}))
    assert not f.reads


@pytest.mark.parametrize('guard', ['authorize', 'require_central_authority'])
def test_revoked_permission_between_read_and_posting_is_denied(prepared_post, guard):
    f = prepared_post
    allowed = [True]
    def permission(db):
        if not allowed[0]: raise PermissionError('Revoked during storage read')
    f.after_read = lambda: allowed.__setitem__(0, False)
    with pytest.raises(PermissionError): f.prepared_post(**{guard: permission})
    assert f.content_evidence()


def test_changed_document_between_read_and_posting_is_denied(prepared_post):
    from Model.containermgmt.Orders.OrderDocument import OrderDocument
    f = prepared_post
    def change():
        with f.factory.begin() as db:
            db.get(OrderDocument, str(f.evidence.document_id)).title = 'Synthetic changed title'
    f.after_read = change
    with pytest.raises(PostingConflict): f.prepared_post()


def test_storage_failure_does_not_consume_approval(prepared_post):
    f = prepared_post
    def fail(*args, **kwargs): raise OSError('Synthetic missing pinned version')
    f.storage.fingerprint_file_version = fail
    with pytest.raises(OSError): f.prepared_post()
    assert f.content_evidence()


def test_invalid_config_never_reads_storage(prepared_post):
    f = prepared_post
    with pytest.raises(ValueError): f.prepared_post(max_bytes=0)
    assert not f.reads


def test_missing_original_version_blocks_even_completed_replay(prepared_post):
    f = prepared_post
    result = f.prepared_post()
    def fail(*args, **kwargs): raise OSError('Original version unavailable')
    f.storage.fingerprint_file_version = fail
    with pytest.raises(OSError): f.prepared_post()
    from Model.containermgmt.Inventory.Valuation import InventoryValuation
    with f.factory() as db:
        rows = db.query(InventoryValuation).filter_by(org_id=f.orgs[0], kind='CHARGE').all()
        assert [row.id for row in rows] == result.result['valuation_ids']


@pytest.mark.parametrize('rejected', [False, True])
def test_unapproved_persisted_case_never_reads_storage(prepared_post, rejected):
    from Services.manager_case_service import request_case, review_case
    f = prepared_post; key = uuid4()
    request_case(f.factory, f.context, f.actor, key, binding=f.content_binding,
        reason='Synthetic unapproved case', load_binding=f.content_load, authorize=lambda db: None)
    if rejected:
        review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=key,
            binding=f.content_binding, expected_version=1, outcome='REJECTED',
            reason='Synthetic rejection', load_binding=f.content_load, authorize=lambda db: None)
    with pytest.raises(PermissionError): f.prepared_post(case_key=key)
    assert not f.reads


def test_root_allowed_companies_do_not_widen_case_lookup(prepared_post):
    from Utils.org_filter import OrgContext
    f = prepared_post
    f.context = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs,
                           is_root=True, selected_org_id=None)
    with pytest.raises(PermissionError): f.prepared_post()
    assert not f.reads
