"""Charge-specific wrapper around reusable document evidence preparation."""
from Services.cost_charge_review_service import ACTION
from Services.document_evidence_preparation_service import (
    PreparedDocumentContent, prepare_document_content)

PreparedChargeContent = PreparedDocumentContent


def prepare_charge_content(factory, *, authorize, load_binding, storage, max_bytes):
    """Authorize/snapshot in a short transaction, then read storage after it closes.

    load_binding must load the scoped authoritative metadata (new request) or
    persisted content-bound case (review/retry). Never supply a client binding.
    Caller MUST reauthorize and compare newly locked source using require_current
    before using content_map in the existing charge-review adapter. No cache,
    receipt, approval or financial record is created here.
    """
    return prepare_document_content(factory, authorize=authorize,
        load_binding=load_binding, storage=storage, max_bytes=max_bytes,
        expected_action=ACTION, min_documents=1, max_documents=2)
