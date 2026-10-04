"""Receipt-cost wrapper around the shared version-pinned evidence reader."""
from Services.document_evidence_preparation_service import (
    PreparedDocumentContent, prepare_document_content)
from Services.inventory_receipt_cost_review_service import ACTION


PreparedReceiptCostContent = PreparedDocumentContent


def prepare_receipt_cost_content(factory, *, authorize, load_binding, storage,
                                 max_bytes):
    return prepare_document_content(factory, authorize=authorize,
        load_binding=load_binding, storage=storage, max_bytes=max_bytes,
        expected_action=ACTION, min_documents=1, max_documents=2)
