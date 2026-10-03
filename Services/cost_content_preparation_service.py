"""Two-stage internal evidence preparation; never a public hash-input endpoint."""
from dataclasses import dataclass
from Schema.DocumentContentSchema import DocumentContentFingerprint
from Services.manager_case_service import CaseBinding
from Services.cost_charge_review_service import ACTION
from Services.inventory_posting_service import PostingConflict


@dataclass(frozen=True)
class PreparedChargeContent:
    source: CaseBinding
    fingerprints: tuple

    def content_map(self):
        return dict(self.fingerprints)

    def require_current(self, current):
        """Call with a newly locked authoritative source before request/review."""
        if not isinstance(current, CaseBinding) or current.snapshot() != self.source.snapshot():
            raise PostingConflict('Evidence source changed during file preparation')


def prepare_charge_content(factory, *, authorize, load_binding, storage, max_bytes):
    """Authorize/snapshot in a short transaction, then read storage after it closes.

    load_binding must load the scoped authoritative metadata (new request) or
    persisted content-bound case (review/retry). Never supply a client binding.
    Caller MUST reauthorize and compare newly locked source using require_current
    before using content_map in the existing charge-review adapter. No cache,
    receipt, approval or financial record is created here.
    """
    if not callable(factory) or not callable(authorize) or not callable(load_binding):
        raise ValueError('Explicit session factory, permission and source loaders required')
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('Configured positive evidence size limit required')
    with factory.begin() as db:
        authorize(db)
        source = load_binding(db)
        if not isinstance(source, CaseBinding) or source.action != ACTION or source.source_version not in (1, 2):
            raise ValueError('Authoritative charge evidence binding required')
        # Detach the immutable JSON snapshot from ORM/session-owned dictionaries.
        source = CaseBinding(**source.snapshot())
        documents = source.details.get('documents', [])
        ids = [doc['id'] for doc in documents]
        if not 1 <= len(ids) <= 2 or len(set(ids)) != len(ids):
            raise ValueError('One invoice and optional FX document required')
        expected = source.details.get('document_content')
        if source.source_version == 2 and (not isinstance(expected, dict) or set(expected) != set(ids)):
            raise PostingConflict('Reviewed content identities are incomplete')
    fingerprints = []
    for doc in sorted(documents, key=lambda item: item['id']):
        prior = DocumentContentFingerprint(**expected[doc['id']]) if source.source_version == 2 else None
        if prior and (prior.bucket != storage.bucket_name or prior.object_key != doc['file_path']):
            raise PostingConflict('Reviewed storage identity changed')
        actual = DocumentContentFingerprint(**storage.fingerprint_file_version(
            doc['file_path'], max_bytes=max_bytes, version_id=prior.version_id if prior else None))
        if actual.object_key != doc['file_path'] or actual.bucket != storage.bucket_name:
            raise PostingConflict('Storage response does not match the requested evidence')
        if doc.get('file_size') is not None and doc['file_size'] != actual.size:
            raise PostingConflict('Evidence file size differs from the saved document')
        if prior and prior != actual:
            raise PostingConflict('Reviewed evidence content changed')
        fingerprints.append((doc['id'], actual))
    return PreparedChargeContent(source, tuple(fingerprints))
