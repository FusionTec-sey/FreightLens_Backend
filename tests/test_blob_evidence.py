from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
import pytest
from tests.test_blob_storage import storage_module


def fixture_client(**changes):
    stream = BytesIO(b'invoice')
    response = dict(Body=stream, ContentLength=7, VersionId='version-1') | changes
    calls = []
    client = storage_module.RustFSClient()
    client._s3_client = SimpleNamespace(get_object=lambda **kwargs: (calls.append(kwargs), response)[1])
    return client, stream, calls


def test_capture_complete_content_and_pin_revalidation_version():
    client, stream, calls = fixture_client()
    result = client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=7)
    assert result == dict(policy='blob-sha256-v1', bucket=client.bucket_name,
        object_key='orders/test/invoice.pdf', version_id='version-1', size=7, sha256=sha256(b'invoice').hexdigest())
    assert 'VersionId' not in calls[0]
    assert stream.closed
    client, stream, calls = fixture_client()
    assert client.fingerprint_file_version(result['object_key'], max_bytes=7, version_id=result['version_id']) == result
    assert calls[0]['VersionId'] == 'version-1'
    assert stream.closed


@pytest.mark.parametrize('changes', [
    {'VersionId': None}, {'VersionId': ''}, {'VersionId': 'null'}, {'VersionId': 'other'},
    {'DeleteMarker': True}, {'ContentRange': 'bytes 0-6/8'}, {'ContentLength': None},
    {'ContentLength': True}, {'ContentLength': 0}, {'ContentLength': 8},
    {'ContentLength': 6}, {'ContentLength': 5},
])
def test_invalid_or_unversioned_evidence_fails_closed_and_closes_stream(changes):
    client, stream, _ = fixture_client(**changes)
    with pytest.raises(ValueError):
        client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=7, version_id='version-1')
    assert stream.closed


def test_truncated_stream_is_rejected():
    client, stream, _ = fixture_client(ContentLength=8)
    with pytest.raises(ValueError, match='incomplete'):
        client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=10)
    assert stream.closed


@pytest.mark.parametrize('kwargs', [{'max_bytes': 0}, {'max_bytes': True}, {'max_bytes': 1.5},
    {'max_bytes': 8, 'version_id': 'null'}, {'max_bytes': 8, 'version_id': ''},
    {'max_bytes': 8, 'version_id': 'bad\nversion'}])
def test_invalid_limits_and_versions_rejected_before_storage_access(kwargs):
    client, _, calls = fixture_client()
    with pytest.raises(ValueError): client.fingerprint_file_version('orders/test/invoice.pdf', **kwargs)
    assert not calls


def test_storage_failure_never_uses_compatibility_or_disk_fallback(monkeypatch):
    client = storage_module.RustFSClient()
    def missing(**kwargs): raise RuntimeError('version unavailable')
    def fallback(*args, **kwargs): pytest.fail('Evidence must not use fallback')
    client._s3_client = SimpleNamespace(get_object=missing)
    monkeypatch.setattr(client, 'get_file', fallback)
    monkeypatch.setattr(storage_module, '_local_fallback_path', fallback)
    with pytest.raises(RuntimeError, match='version unavailable'):
        client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=8, version_id='version-1')


def test_same_length_replacement_has_different_content_digest():
    client, _, _ = fixture_client()
    first = client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=7)
    client, _, _ = fixture_client(Body=BytesIO(b'changed'))
    second = client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=7)
    assert first['sha256'] != second['sha256']


def test_stream_error_closes_connection():
    class FailingStream(BytesIO):
        def read(self, size): raise OSError('interrupted')
    body = FailingStream(b'invoice')
    client, _, _ = fixture_client(Body=body)
    with pytest.raises(OSError): client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=7)
    assert body.closed


def test_large_content_is_hashed_in_bounded_chunks():
    class BoundedStream(BytesIO):
        def read(self, size):
            assert 0 < size <= 64 * 1024
            return super().read(size)
    content = b'x' * (128 * 1024 + 3)
    body = BoundedStream(content)
    client, _, _ = fixture_client(Body=body, ContentLength=len(content))
    result = client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=len(content))
    assert result['sha256'] == sha256(content).hexdigest()
    assert body.closed


def test_mismatched_version_is_rejected_before_reading_bytes():
    class UnreadStream(BytesIO):
        def read(self, size): pytest.fail('Mismatched version must not be read')
    body = UnreadStream(b'invoice')
    client, _, _ = fixture_client(Body=body, VersionId='replacement')
    with pytest.raises(ValueError, match='mismatched'):
        client.fingerprint_file_version('orders/test/invoice.pdf', max_bytes=7, version_id='reviewed-version')
    assert body.closed


def test_unsafe_key_rejected_before_storage_access():
    client, _, calls = fixture_client()
    with pytest.raises(ValueError): client.fingerprint_file_version('../invoice.pdf', max_bytes=7)
    assert not calls


def test_download_returns_only_fully_verified_pinned_bytes():
    client, _, _ = fixture_client()
    fingerprint = client.fingerprint_file_version('test/invoice', max_bytes=7)
    client, stream, calls = fixture_client()
    assert client.read_verified_file_version(fingerprint, max_bytes=7) == b'invoice'
    assert calls[0]['VersionId'] == 'version-1'
    assert stream.closed
    client, _, _ = fixture_client(Body=BytesIO(b'changed'))
    with pytest.raises(ValueError, match='changed'):
        client.read_verified_file_version(fingerprint, max_bytes=7)
