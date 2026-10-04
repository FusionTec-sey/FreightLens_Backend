from decimal import Decimal as D
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker
from Model.containermgmt.Inventory.StockLedger import StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Schema.DocumentContentSchema import DocumentContentFingerprint
from Schema.ReceiptCostReviewSchema import ReceiptCostDeclaration
from Services.inventory_posting_service import PostingConflict
from Services.document_evidence_preparation_service import PreparedDocumentContent
from Services.inventory_receipt_cost_review_service import (
    approved_receipt_cost_binding, receipt_cost_binding,
    request_receipt_cost_review, review_receipt_cost)
from Services.inventory_receipt_posting_service import (
    post_reviewed_receipt, prepare_and_post_reviewed_receipt)
from tests.test_inventory_receipt_valuation import receipt_value  # noqa: F401
from tests.test_inventory_receipt_movements import movement  # noqa: F401
from tests.test_inventory_receipt_source_uses import source_use  # noqa: F401
from tests.test_inventory_receipt_reviews import review  # noqa: F401
from tests.test_inventory_receipt_source import receipt  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def receipt_cost(receipt_value):
    f = receipt_value
    f.po_item.po_unit_price = D('10.00')
    f.po_item.currency = 'USD'
    f.db.get(PurchaseOrder, f.receipt.po_id).currency = 'USD'
    price_id, fx_id = str(uuid4()), str(uuid4())
    f.db.add_all([
        OrderDocument(id=price_id, org_id=f.org_a, entity_type='PO',
            entity_id=f.receipt.po_id, po_id=f.receipt.po_id,
            doc_type='PROFORMA_INVOICE', file_name='synthetic-price.pdf',
            file_path='synthetic/price', file_size=7, created_by=f.user.id),
        OrderDocument(id=fx_id, org_id=f.org_a, entity_type='GENERAL',
            entity_id=None, po_id=None, doc_type='OTHER',
            file_name='synthetic-fx.pdf', file_path='synthetic/fx',
            file_size=7, created_by=f.user.id),
    ])
    f.db.commit()
    f.cost_declaration = ReceiptCostDeclaration(document_id=UUID(price_id),
        fx_document_id=UUID(fx_id), source_currency='USD',
        unit_price_source='10', exchange_rate_to_scr='12',
        justification='Official PO price converted with reviewed bank FX evidence')
    f.cost_content = {
        price_id: DocumentContentFingerprint(policy='blob-sha256-v1',
            bucket='synthetic', object_key='synthetic/price', version_id='v1',
            size=7, sha256='a' * 64),
        fx_id: DocumentContentFingerprint(policy='blob-sha256-v1',
            bucket='synthetic', object_key='synthetic/fx', version_id='v1',
            size=7, sha256='b' * 64),
    }
    f.cost_case = uuid4()
    return f


def binding(f, **changes):
    f.db.connection()
    declaration = changes.pop('declaration', f.cost_declaration)
    return receipt_cost_binding(f.db, f.context, f.manifest_key, declaration,
        authorize=changes.pop('authorize', lambda db: None),
        document_content=changes.pop('content', f.cost_content), **changes)


def approved_cost(f):
    f.db.connection()
    request_receipt_cost_review(f.db, f.context, f.user.id, f.cost_case,
        manifest_key=f.manifest_key, declaration=f.cost_declaration,
        reason='Verify receipt cost', authorize=lambda db: None,
        document_content=f.cost_content)
    f.db.commit(); f.db.connection()
    review_receipt_cost(f.db, f.context, f.reviewer.id, uuid4(),
        manifest_key=f.manifest_key, case_key=f.cost_case,
        expected_version=1, outcome='APPROVED', reason='Documents verified',
        authorize=lambda db: None)
    f.db.commit(); f.db.connection()
    source = approved_receipt_cost_binding(f.db, f.context, f.cost_case,
        f.manifest_key, authorize=lambda db: None,
        document_content=f.cost_content)
    return PreparedDocumentContent(source,
        tuple(sorted(f.cost_content.items())))


def post_costed_receipt(f, operation, prepared=None, **changes):
    prepared = prepared or approved_cost(f)
    params = dict(manifest_key=f.manifest_key,
        classification_case_key=f.case_key, cost_case_key=f.cost_case,
        expected_valuation_version=0, prepared_cost=prepared,
        reason='Post verified synthetic receipt', stock_authority=f.authority,
        cost_authority=f.cost_authority, authorize_stock=lambda db: None,
        authorize_cost=lambda db: None)
    params.update(changes)
    f.db.connection()
    return post_reviewed_receipt(f.db, f.context, f.user.id, operation, **params)


def test_receipt_cost_binds_official_price_quantity_fx_and_versions(receipt_cost):
    f = receipt_cost; result = binding(f)
    assert result.source_version == 2
    assert result.details['receipt_quantity'] == '2.000000'
    assert result.details['goods_value_source'] == '20.000000'
    assert result.details['goods_value_scr'] == '240.000000'
    assert result.details['calculation_policy'] == 'receipt-po-fx-v1'
    assert set(result.details['document_content']) == set(f.cost_content)


def test_receipt_cost_review_is_independent_and_has_no_stock_effect(receipt_cost):
    f = receipt_cost; f.db.connection()
    requested = request_receipt_cost_review(f.db, f.context, f.user.id,
        f.cost_case, manifest_key=f.manifest_key,
        declaration=f.cost_declaration, reason='Verify receipt cost',
        authorize=lambda db: None, document_content=f.cost_content)
    assert requested.result['status'] == 'REQUESTED'
    f.db.commit(); f.db.connection()
    with pytest.raises(PermissionError, match='creators'):
        review_receipt_cost(f.db, f.context, f.user.id, uuid4(),
            manifest_key=f.manifest_key, case_key=f.cost_case,
            expected_version=1, outcome='APPROVED', reason='Self review',
            authorize=lambda db: None)
    result = review_receipt_cost(f.db, f.context, f.reviewer.id, uuid4(),
        manifest_key=f.manifest_key, case_key=f.cost_case,
        expected_version=1, outcome='APPROVED', reason='Documents verified',
        authorize=lambda db: None)
    assert result.result['status'] == 'APPROVED'
    assert f.db.query(StockMovement).filter_by(org_id=f.org_a).count() == 0
    assert f.db.query(InventoryValuation).filter_by(org_id=f.org_a).count() == 0


def test_approved_receipt_cost_rechecks_exact_original_content(receipt_cost):
    f = receipt_cost; f.db.connection()
    request_receipt_cost_review(f.db, f.context, f.user.id, f.cost_case,
        manifest_key=f.manifest_key, declaration=f.cost_declaration,
        reason='Verify receipt cost', authorize=lambda db: None,
        document_content=f.cost_content)
    f.db.commit(); f.db.connection()
    review_receipt_cost(f.db, f.context, f.reviewer.id, uuid4(),
        manifest_key=f.manifest_key, case_key=f.cost_case,
        expected_version=1, outcome='APPROVED', reason='Documents verified',
        authorize=lambda db: None)
    current = approved_receipt_cost_binding(f.db, f.context, f.cost_case,
        f.manifest_key, authorize=lambda db: None,
        document_content=f.cost_content)
    assert current.details['goods_value_scr'] == '240.000000'
    changed = {key: value.model_copy(update={'version_id': 'replacement'})
        for key, value in f.cost_content.items()}
    with pytest.raises(PostingConflict):
        approved_receipt_cost_binding(f.db, f.context, f.cost_case,
            f.manifest_key, authorize=lambda db: None,
            document_content=changed)


def test_atomic_receipt_derives_value_from_approved_po_fx_evidence(receipt_cost):
    f = receipt_cost; prepared = approved_cost(f); operation = uuid4()
    result = post_costed_receipt(f, operation, prepared)
    assert not result.replayed
    assert result.result['pool_value_scr'] == '240.000000'
    assert result.result['cost_case_key'] == str(f.cost_case)
    assert f.db.query(ManagerCaseUse).filter_by(
        org_id=f.org_a, operation_key=operation).count() == 2
    receipt = f.db.query(PostingOperation).filter_by(
        org_id=f.org_a, operation_key=operation).one()
    assert receipt.kind == 'inventory.receipt.post.v1'
    assert receipt.event_payload['cost_case_key'] == str(f.cost_case)
    assert f.db.query(StockMovement).filter_by(
        org_id=f.org_a, kind='RECEIPT').count() == 1
    assert f.db.query(InventoryValuation).filter_by(
        org_id=f.org_a, kind='RECEIPT').one().goods_value_scr == D('240.000000')


def test_receipt_replay_rechecks_exact_evidence_and_permissions(receipt_cost):
    f = receipt_cost; prepared = approved_cost(f); operation = uuid4()
    post_costed_receipt(f, operation, prepared); f.db.commit()
    assert post_costed_receipt(f, operation, prepared).replayed
    changed = PreparedDocumentContent(prepared.source, tuple(
        (key, value.model_copy(update={'sha256': 'c' * 64}))
        for key, value in prepared.fingerprints))
    with pytest.raises(PostingConflict):
        post_costed_receipt(f, operation, changed)
    def denied(db): raise PermissionError('Financial access revoked')
    with pytest.raises(PermissionError, match='revoked'):
        post_costed_receipt(f, operation, prepared, authorize_cost=denied)


def test_receipt_failure_rolls_back_both_approvals_stock_and_value(receipt_cost):
    f = receipt_cost; prepared = approved_cost(f); operation = uuid4()
    with pytest.raises(RuntimeError):
        with f.db.begin_nested():
            post_costed_receipt(f, operation, prepared)
            raise RuntimeError('Synthetic downstream outbox failure')
    assert f.db.query(ManagerCaseUse).filter_by(
        org_id=f.org_a, operation_key=operation).count() == 0
    assert f.db.query(StockMovement).filter_by(org_id=f.org_a).count() == 0
    assert f.db.query(InventoryValuation).filter_by(org_id=f.org_a).count() == 0
    assert f.db.query(PostingOperation).filter_by(
        org_id=f.org_a, operation_key=operation).count() == 0


def test_receipt_preparation_reads_pinned_blob_versions_before_atomic_post(receipt_cost):
    f = receipt_cost; approved_cost(f); f.db.commit()
    factory = sessionmaker(bind=f.db.get_bind())
    reads = []
    by_path = {value.object_key: value for value in f.cost_content.values()}
    def read(path, **options):
        reads.append((path, options))
        return by_path[path].model_dump()
    storage = SimpleNamespace(bucket_name='synthetic',
        fingerprint_file_version=read)
    operation = uuid4()
    params = dict(manifest_key=f.manifest_key,
        classification_case_key=f.case_key, cost_case_key=f.cost_case,
        expected_valuation_version=0, reason='Post verified synthetic receipt',
        stock_authority=f.authority, cost_authority=f.cost_authority,
        authorize_stock=lambda db: None, authorize_cost=lambda db: None,
        storage=storage, max_bytes=100)
    first = prepare_and_post_reviewed_receipt(factory, f.context, f.user.id,
        operation, **params)
    second = prepare_and_post_reviewed_receipt(factory, f.context, f.user.id,
        operation, **params)
    assert not first.replayed and second.replayed
    assert len(reads) == 4
    assert all(options == {'max_bytes': 100, 'version_id': 'v1'}
        for _, options in reads)


def test_receipt_cost_changes_and_unscoped_documents_fail_closed(receipt_cost):
    f = receipt_cost
    f.po_item.po_unit_price = D('11.00'); f.db.commit()
    with pytest.raises(PostingConflict, match='unit price'):
        binding(f)
    f.po_item.po_unit_price = D('10.00')
    price = f.db.get(OrderDocument, str(f.cost_declaration.document_id))
    price.po_id = None; price.entity_type = 'GENERAL'; price.entity_id = None
    f.db.commit()
    with pytest.raises(PostingConflict, match='exact purchase order'):
        binding(f)


def test_receipt_cost_requires_typed_complete_versioned_content_and_permission(receipt_cost):
    f = receipt_cost
    with pytest.raises(PostingConflict): binding(f, content={})
    with pytest.raises(ValueError):
        binding(f, content={key: value.model_dump()
            for key, value in f.cost_content.items()})
    def denied(db): raise PermissionError('Financial access revoked')
    with pytest.raises(PermissionError, match='revoked'):
        binding(f, authorize=denied)


@pytest.mark.parametrize('changes', [
    {'source_currency': 'USD', 'fx_document_id': None},
    {'source_currency': 'SCR', 'exchange_rate_to_scr': '12'},
    {'unit_price_source': '1.0000001'},
    {'exchange_rate_to_scr': '1.000000001'},
])
def test_receipt_cost_declaration_rejects_ambiguous_values(receipt_cost, changes):
    values = receipt_cost.cost_declaration.model_dump() | changes
    with pytest.raises(ValidationError):
        ReceiptCostDeclaration(**values)
