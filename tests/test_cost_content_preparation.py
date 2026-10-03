from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4
import pytest
from Services.cost_content_preparation_service import prepare_charge_content
from Services.cost_charge_review_service import ACTION
from Services.manager_case_service import CaseBinding
from Services.inventory_posting_service import PostingConflict


@pytest.fixture
def setup():
    f = SimpleNamespace(active=False, calls=[], doc=str(uuid4()))
    f.fingerprint = dict(policy='blob-sha256-v1', bucket='synthetic', object_key='test/invoice',
        version_id='original', size=7, sha256='a' * 64)
    f.binding = CaseBinding(1, ACTION, 'inventory.cost-allocation', str(uuid4()), 1,
        {'documents': [{'id': f.doc, 'file_path': 'test/invoice', 'file_size': 7}]})
    @contextmanager
    def begin():
        f.active = True
        try: yield object()
        finally: f.active = False
    def read(key, **kwargs):
        assert not f.active, 'Storage I/O must be outside the database transaction'
        f.calls.append((key, kwargs))
        return f.fingerprint.copy()
    f.storage = SimpleNamespace(bucket_name='synthetic', fingerprint_file_version=read)
    f.factory = SimpleNamespace(begin=begin)
    # Real SQLAlchemy sessionmaker is callable; model that contract too.
    class Factory:
        def __call__(self): pass
        def begin(self): return begin()
    f.factory = Factory()
    f.run = lambda **kw: prepare_charge_content(f.factory, authorize=kw.pop('authorize', lambda db: None),
        load_binding=lambda db: f.binding, storage=f.storage, max_bytes=kw.pop('max_bytes', 100), **kw)
    return f


def test_capture_closes_transaction_and_rechecks_locked_source(setup):
    f = setup; prepared = f.run()
    assert prepared.content_map()[f.doc].version_id == 'original'
    prepared.require_current(f.binding)
    with pytest.raises(PostingConflict): prepared.require_current(replace(f.binding, source_version=2))
    assert f.calls == [('test/invoice', {'max_bytes': 100, 'version_id': None})]


def test_review_reads_exact_saved_version(setup):
    f = setup
    f.binding = replace(f.binding, source_version=2, details={**f.binding.details, 'document_content': {f.doc: f.fingerprint.copy()}})
    f.run()
    assert f.calls[0][1]['version_id'] == 'original'
    f.fingerprint['sha256'] = 'b' * 64
    with pytest.raises(PostingConflict): f.run()


def test_permission_denial_precedes_storage(setup):
    def deny(db): raise PermissionError('revoked')
    with pytest.raises(PermissionError): setup.run(authorize=deny)
    assert not setup.calls


@pytest.mark.parametrize('change', [{'bucket': 'foreign'}, {'object_key': 'other'}, {'size': 8}])
def test_storage_identity_and_size_mismatch_rejected(setup, change):
    setup.fingerprint.update(change)
    with pytest.raises(PostingConflict): setup.run()


def test_missing_reviewed_fingerprints_do_not_fall_back_to_latest(setup):
    setup.binding = replace(setup.binding, source_version=2)
    with pytest.raises(PostingConflict): setup.run()
    assert not setup.calls


def test_invalid_limit_blocks_before_storage(setup):
    with pytest.raises(ValueError): setup.run(max_bytes=0)
    assert not setup.calls
