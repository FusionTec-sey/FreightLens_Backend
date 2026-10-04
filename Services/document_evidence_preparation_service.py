"""Reusable two-stage, version-pinned document evidence preparation."""
from dataclasses import dataclass
from Schema.DocumentContentSchema import DocumentContentFingerprint
from Services.manager_case_service import CaseBinding
from Services.inventory_posting_service import PostingConflict


@dataclass(frozen=True)
class PreparedDocumentContent:
    source: CaseBinding
    fingerprints: tuple

    def content_map(self):
        return dict(self.fingerprints)

    def require_current(self, current):
        if not isinstance(current, CaseBinding) or current.snapshot() != self.source.snapshot():
            raise PostingConflict('Evidence source changed during file preparation')


def prepare_document_content(factory, *, authorize, load_binding, storage,
        max_bytes, expected_action, min_documents=1, max_documents=2):
    """Snapshot database metadata, release locks, then hash bounded blob versions."""
    if not callable(factory) or not callable(authorize) or not callable(load_binding):
        raise ValueError('Explicit session factory, permission and source loaders required')
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('Configured positive evidence size limit required')
    if (not isinstance(expected_action, str) or not expected_action
            or type(min_documents) is not int or type(max_documents) is not int
            or min_documents < 1 or max_documents < min_documents or max_documents > 20):
        raise ValueError('Bounded evidence action and document limits required')
    with factory.begin() as db:
        authorize(db)
        source = load_binding(db)
        if (not isinstance(source, CaseBinding) or source.action != expected_action
                or source.source_version not in (1, 2)):
            raise ValueError('Authoritative evidence binding required')
        source = CaseBinding(**source.snapshot())
        documents = source.details.get('documents', [])
        ids = [doc['id'] for doc in documents]
        if not min_documents <= len(ids) <= max_documents or len(set(ids)) != len(ids):
            raise ValueError('Evidence requires a bounded distinct document set')
        expected = source.details.get('document_content')
        if source.source_version == 2 and (
                not isinstance(expected, dict) or set(expected) != set(ids)):
            raise PostingConflict('Reviewed content identities are incomplete')
    fingerprints = []
    for doc in sorted(documents, key=lambda item: item['id']):
        prior = DocumentContentFingerprint(**expected[doc['id']]) \
            if source.source_version == 2 else None
        if prior and (prior.bucket != storage.bucket_name
                or prior.object_key != doc['file_path']):
            raise PostingConflict('Reviewed storage identity changed')
        actual = DocumentContentFingerprint(**storage.fingerprint_file_version(
            doc['file_path'], max_bytes=max_bytes,
            version_id=prior.version_id if prior else None))
        if actual.object_key != doc['file_path'] or actual.bucket != storage.bucket_name:
            raise PostingConflict('Storage response does not match the requested evidence')
        if doc.get('file_size') is not None and doc['file_size'] != actual.size:
            raise PostingConflict('Evidence file size differs from the saved document')
        if prior and prior != actual:
            raise PostingConflict('Reviewed evidence content changed')
        fingerprints.append((doc['id'], actual))
    return PreparedDocumentContent(source, tuple(fingerprints))
