from dataclasses import replace
from uuid import uuid4
import pytest
from auth.policy import AccessPolicy
from Model.Credentials.users import User
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Model.containermgmt.Inventory.StockLedger import StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Services.inventory_receipt_manifest_store import save_receipt_manifest
from tests.test_inventory_receipt_manifest import manifest
from tests.test_inventory_receipt_source import receipt  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401

BASE = '/inventory/receipt-manifests'


@pytest.fixture
def api(receipt):
    from Routes.Inventory.ReceiptManifestRouter import ReceiptManifestRouter
    f = receipt; f.key = uuid4(); f.db.connection()
    save_receipt_manifest(f.db, f.context, f.user.id, f.key, manifest(f), authorize=lambda db: None)
    f.db.commit()
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset({'View_Product', 'View_GoodsReceipt'}),
        module_names=frozenset({'INVENTORY', 'ORDERS'}), field_permissions={})
    f.app.include_router(ReceiptManifestRouter)
    replacements = {'get_db': lambda: f.db, 'get_current_user': lambda: f.user,
        'get_org_context': lambda: f.context, 'get_request_policy': lambda: f.user.access_policy}
    def override(dependant):
        for dependency in dependant.dependencies:
            name = getattr(dependency.call, '__name__', '')
            if name in replacements and getattr(dependency.call, '__module__', '').startswith(('auth.', 'Model.db')):
                f.app.dependency_overrides[dependency.call] = replacements[name]
                if name == 'get_current_user': f.user_dependencies.add(dependency.call)
            override(dependency)
    for route in f.app.routes:
        if hasattr(route, 'dependant'): override(route.dependant)
    return f


def test_historical_receipt_read_paging_and_no_posting_contract(api):
    f = api
    response = f.client.get(BASE + '?limit=1')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    row = response.json()['items'][0]
    assert row['status'] == 'SAVED' and not row['physical_posting_enabled']
    assert 'manifest' not in row and 'source' not in row
    assert f.client.get(BASE + '?page=2&limit=1').json()['items'] == []
    assert f.client.get(BASE + '?limit=101').status_code == 422
    f.receipt_line.condition_ok = False; f.db.commit()
    detail = f.client.get(f'{BASE}/{f.key}')
    assert detail.status_code == 200
    assert detail.json()['historical_snapshot'] and not detail.json()['condition_review_required']
    assert 'supplier_id' not in detail.text and 'unit_price' not in detail.text
    assert f.client.post(f'{BASE}/{f.key}/post', json={}).status_code == 404


@pytest.mark.parametrize('missing', ['View_Product', 'View_GoodsReceipt'])
def test_receipt_read_requires_both_permissions(api, missing):
    f = api
    f.user.access_policy = replace(f.user.access_policy,
        permission_names=f.user.access_policy.permission_names - {missing})
    assert f.client.get(BASE).status_code == 403
    assert f.client.get(f'{BASE}/{f.key}').status_code == 403


@pytest.mark.parametrize('module', ['INVENTORY', 'ORDERS'])
def test_receipt_read_requires_both_modules(api, module):
    f = api
    f.user.access_policy = replace(f.user.access_policy, module_names=frozenset({module}))
    assert f.client.get(BASE).status_code == 403


def test_receipt_read_denies_foreign_and_deleted_parents(api):
    f = api
    f.context.current_org_id = f.org_b; f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.is_root = True
    assert f.client.get(BASE).json()['items'] == []
    assert f.client.get(f'{BASE}/{f.key}').status_code == 404
    f.context.current_org_id = f.org_a
    f.receipt.is_deleted = True; f.db.commit()
    assert f.client.get(BASE).json()['items'] == []
    assert f.client.get(f'{BASE}/{f.key}').status_code == 404


def test_anonymous_receipt_read_denied(api):
    f = api
    for dep in f.user_dependencies: f.app.dependency_overrides.pop(dep, None)
    for dep in list(f.app.dependency_overrides):
        if getattr(dep, '__name__', '') == 'get_request_policy': f.app.dependency_overrides.pop(dep)
    assert f.client.get(BASE).status_code == 401
    assert f.client.get(f'{BASE}/{f.key}').status_code == 401


def permissions(f, *extra):
    f.user.access_policy = replace(f.user.access_policy,
        permission_names=f.user.access_policy.permission_names | frozenset(extra))


@pytest.fixture
def cost_evidence(api, monkeypatch):
    from Routes.Inventory import ReceiptManifestRouter as router
    f = api
    f.po_item.po_unit_price = 10
    f.po_item.currency = 'USD'
    f.db.get(PurchaseOrder, f.receipt.po_id).currency = 'USD'
    f.price_document, f.fx_document = str(uuid4()), str(uuid4())
    f.db.add_all([
        OrderDocument(id=f.price_document, org_id=f.org_a, entity_type='PO',
            entity_id=f.receipt.po_id, po_id=f.receipt.po_id,
            doc_type='PROFORMA_INVOICE', file_name='synthetic-price.pdf',
            file_path='synthetic/price', file_size=7, created_by=f.user.id),
        OrderDocument(id=f.fx_document, org_id=f.org_a, entity_type='GENERAL',
            entity_id=None, po_id=None, doc_type='OTHER',
            file_name='synthetic-fx.pdf', file_path='synthetic/fx',
            file_size=7, created_by=f.user.id),
    ])
    f.db.commit()
    f.user.access_policy = replace(f.user.access_policy,
        field_permissions={'FINANCIAL': 'View_Financials',
            'SUPPLIER_IDENTITY': 'View_Supplier'})
    monkeypatch.setenv('COST_EVIDENCE_MAX_BYTES', '100')
    monkeypatch.setattr(router.blob_storage, 'bucket_name', 'synthetic')

    def fingerprint(path, *, max_bytes, version_id=None):
        return {'policy': 'blob-sha256-v1', 'bucket': 'synthetic',
            'object_key': path, 'version_id': version_id or 'v1', 'size': 7,
            'sha256': ('a' if path.endswith('price') else 'b') * 64}

    monkeypatch.setattr(router.blob_storage, 'fingerprint_file_version', fingerprint)
    monkeypatch.setattr(router.blob_storage, 'read_verified_file_version',
        lambda content, *, max_bytes: b'content')
    return f


def cost_request(f, operation):
    return {'operation_key': str(operation), 'reason': 'Verify exact PO and FX evidence',
        'declaration': {'document_id': f.price_document,
            'fx_document_id': f.fx_document, 'source_currency': 'USD',
            'unit_price_source': '10', 'exchange_rate_to_scr': '12',
            'justification': 'Official PO price and reviewed bank FX evidence'}}


def create_body(f, operation_key):
    return {'operation_key': str(operation_key), **manifest(f).model_dump(mode='json')}


def test_manifest_save_requires_receipt_authority_and_replays_exact_intent(api):
    f = api; operation = uuid4(); body = create_body(f, operation)
    assert f.client.post(BASE, json=body).status_code == 403
    permissions(f, 'Verify_Receipt')
    first = f.client.post(BASE, json=body)
    assert first.status_code == 200 and first.json() == {
        'manifest_key': str(operation), 'status': 'SAVED', 'replayed': False,
        'physical_posting_enabled': False,
    }
    replay = f.client.post(BASE, json=body)
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    changed = {**body, 'reason': 'Changed classification under the same operation'}
    assert f.client.post(BASE, json=changed).status_code == 409
    assert f.product.current_stock == 0


def test_manifest_preview_is_exact_read_only_and_permission_scoped(api):
    f = api; body = manifest(f).model_dump(mode='json')
    before = f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count()
    assert f.client.post(BASE + '/preview', json=body).status_code == 403
    permissions(f, 'Verify_Receipt')
    response = f.client.post(BASE + '/preview', json=body)
    assert response.status_code == 200
    result = response.json()
    assert result['source']['product_id'] == f.product.id
    assert result['source']['base_quantities']['received_quantity'] == '24.000000'
    assert result['quantities']['on_hand'] == '24.000000'
    assert result['manifest']['reason'] == body['reason']
    assert result['physical_posting_enabled'] is False
    assert f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count() == before
    assert f.product.current_stock == 0
    assert 'manifest_key' not in result and 'unit_price' not in response.text


def test_source_preview_supplies_exact_base_context_without_classification_or_write(api):
    f = api; source = manifest(f).source.model_dump(mode='json')
    assert f.client.post(BASE + '/source-preview', json=source).status_code == 403
    permissions(f, 'Verify_Receipt')
    response = f.client.post(BASE + '/source-preview', json=source)
    assert response.status_code == 200
    result = response.json()
    assert result['base_quantities'] == {
        'received_quantity': '24.000000', 'damaged_quantity': '0.000000',
        'incorrect_quantity': '0.000000',
    }
    assert result['unit'] == 'BOX' and result['base_unit'] == 'PCS'
    assert result['physical_posting_enabled'] is False
    assert 'manifest' not in result and 'unit_price' not in response.text
    assert f.product.current_stock == 0


def test_manifest_review_is_scoped_independent_and_never_posts_stock(api):
    f = api; use_count = f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count()
    request_key = uuid4()
    request_body = {'operation_key': str(request_key), 'reason': 'Synthetic receipt classification review'}
    assert f.client.post(f'{BASE}/{f.key}/request-review', json=request_body).status_code == 403
    permissions(f, 'Request_InventoryReview')
    requested = f.client.post(f'{BASE}/{f.key}/request-review', json=request_body)
    assert requested.status_code == 200 and requested.json()['status'] == 'REQUESTED'
    assert f.client.post(f'{BASE}/{f.key}/request-review', json=request_body).json()['replayed'] is True
    own = f.client.get(f'{BASE}/{f.key}/cases?view=MY_REQUESTS')
    assert own.status_code == 200 and own.json()['items'][0]['manifest_key'] == str(f.key)
    assert own.json()['items'][0]['physical_posting_enabled'] is False
    assert f.client.get(f'{BASE}/{f.key}/cases?view=ALL').status_code == 403

    case_key = requested.json()['case_key']
    permissions(f, 'Review_InventoryPolicy')
    self_review = f.client.post(f'{BASE}/{f.key}/cases/{case_key}/review', json={
        'operation_key': str(uuid4()), 'expected_version': 1, 'outcome': 'APPROVED', 'reason': 'Invalid self review'})
    assert self_review.status_code == 403

    reviewer = User(org_id=f.org_a, username='api-review-' + uuid4().hex, password_hash='unusable-test-only')
    f.db.add(reviewer); f.db.commit()
    reviewer.access_policy = AccessPolicy(user=reviewer, org_ids=(f.org_a,),
        permission_names=frozenset({'View_Product', 'View_GoodsReceipt', 'Review_InventoryPolicy'}),
        module_names=frozenset({'INVENTORY', 'ORDERS'}), field_permissions={})
    f.user = reviewer
    reviewed = f.client.post(f'{BASE}/{f.key}/cases/{case_key}/review', json={
        'operation_key': str(uuid4()), 'expected_version': 1, 'outcome': 'APPROVED', 'reason': 'Inspected classification'})
    assert reviewed.status_code == 200 and reviewed.json()['status'] == 'APPROVED'
    listed = f.client.get(f'{BASE}/{f.key}/cases?view=ALL')
    assert listed.status_code == 200 and listed.json()['items'][0]['status'] == 'APPROVED'
    assert f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count() == use_count
    assert f.product.current_stock == 0


def test_manifest_write_and_review_paths_reject_foreign_company(api):
    f = api
    f.context.current_org_id = f.org_b; f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.is_root = True
    permissions(f, 'Verify_Receipt', 'Request_InventoryReview', 'Review_InventoryPolicy')
    assert f.client.post(BASE + '/source-preview', json=manifest(f).source.model_dump(mode='json')).status_code == 404
    assert f.client.post(BASE + '/preview', json=manifest(f).model_dump(mode='json')).status_code == 404
    assert f.client.post(BASE, json=create_body(f, uuid4())).status_code == 404
    assert f.client.post(f'{BASE}/{f.key}/request-review', json={
        'operation_key': str(uuid4()), 'reason': 'Foreign request'}).status_code == 404
    assert f.client.get(f'{BASE}/{f.key}/cases?view=ALL').status_code == 404


def test_receipt_cost_request_review_and_versioned_download_never_post(cost_evidence):
    f = cost_evidence
    before = (f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count(),
        f.db.query(StockMovement).filter_by(org_id=f.org_a).count(),
        f.db.query(InventoryValuation).filter_by(org_id=f.org_a).count())
    base_permissions = ('View_Financials', 'Manage_Financials', 'View_Supplier',
        'View_OrderDocument', 'Request_ReceiptCostReview')
    permissions(f, *base_permissions)
    operation = uuid4(); body = cost_request(f, operation)
    requested = f.client.post(f'{BASE}/{f.key}/cost-cases', json=body)
    assert requested.status_code == 200, requested.text
    assert requested.json()['status'] == 'REQUESTED'
    assert f.client.post(f'{BASE}/{f.key}/cost-cases', json=body).json()['replayed'] is True
    case_key = requested.json()['case_key']
    own = f.client.get(f'{BASE}/{f.key}/cost-cases?view=MY_REQUESTS')
    assert own.status_code == 200
    row = own.json()['items'][0]
    assert row['case_key'] == case_key and row['goods_value_source'] == '20.000000'
    assert row['goods_value_scr'] == '240.000000' and not row['physical_posting_enabled']
    assert 'document_content' not in own.text and 'file_path' not in own.text

    reviewer = User(org_id=f.org_a, username='rc-' + uuid4().hex,
        password_hash='unusable-test-only')
    f.db.add(reviewer); f.db.commit()
    reviewer.access_policy = AccessPolicy(user=reviewer, org_ids=(f.org_a,),
        permission_names=frozenset({'View_Product', 'View_GoodsReceipt',
            'View_Financials', 'Manage_Financials', 'View_Supplier',
            'View_OrderDocument', 'Review_ReceiptCostReview'}),
        module_names=frozenset({'INVENTORY', 'ORDERS'}),
        field_permissions={'FINANCIAL': 'View_Financials',
            'SUPPLIER_IDENTITY': 'View_Supplier'})
    f.user = reviewer
    decision = {'operation_key': str(uuid4()), 'expected_version': 1,
        'outcome': 'APPROVED',
        'reason': 'Original price and FX versions inspected'}
    reviewed = f.client.post(
        f'{BASE}/{f.key}/cost-cases/{case_key}/review', json=decision)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()['status'] == 'APPROVED'
    download = f.client.get(
        f'{BASE}/{f.key}/cost-cases/{case_key}/documents/{f.price_document}')
    assert download.status_code == 200 and download.content == b'content'
    assert download.headers['cache-control'] == 'no-store'
    after = (f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count(),
        f.db.query(StockMovement).filter_by(org_id=f.org_a).count(),
        f.db.query(InventoryValuation).filter_by(org_id=f.org_a).count())
    assert after == before


def test_receipt_cost_permissions_storage_and_foreign_scope_fail_closed(cost_evidence, monkeypatch):
    f = cost_evidence; body = cost_request(f, uuid4())
    assert f.client.post(f'{BASE}/{f.key}/cost-cases', json=body).status_code == 403
    permissions(f, 'View_Financials', 'Manage_Financials', 'View_Supplier',
        'View_OrderDocument', 'Request_ReceiptCostReview')
    monkeypatch.delenv('COST_EVIDENCE_MAX_BYTES', raising=False)
    disabled = f.client.post(f'{BASE}/{f.key}/cost-cases', json=body)
    assert disabled.status_code == 503
    assert f.client.get(f'{BASE}/{f.key}/cost-cases?view=MY_REQUESTS').json()['items'] == []
    monkeypatch.setenv('COST_EVIDENCE_MAX_BYTES', '100')
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.post(f'{BASE}/{f.key}/cost-cases', json=body).status_code == 404
    assert f.client.get(f'{BASE}/{f.key}/cost-cases?view=MY_REQUESTS').status_code == 404


def test_receipt_cost_self_review_is_denied(cost_evidence):
    f = cost_evidence
    permissions(f, 'View_Financials', 'Manage_Financials', 'View_Supplier',
        'View_OrderDocument', 'Request_ReceiptCostReview',
        'Review_ReceiptCostReview')
    requested = f.client.post(f'{BASE}/{f.key}/cost-cases',
        json=cost_request(f, uuid4()))
    assert requested.status_code == 200
    response = f.client.post(
        f"{BASE}/{f.key}/cost-cases/{requested.json()['case_key']}/review",
        json={'operation_key': str(uuid4()), 'expected_version': 1,
            'outcome': 'APPROVED', 'reason': 'Invalid self review'})
    assert response.status_code == 403
