from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from auth.policy import AccessPolicy
from tests.test_cost_charge_reviews import charge_review, charge, allocation, valued, stock  # noqa: F401

PERMISSIONS = {'View_Product', 'View_Supplier', 'View_OrderDocument', 'View_Financials', 'Manage_Financials'}


@pytest.fixture
def evidence_api(charge_review, monkeypatch):
    from Routes.Inventory.CostEvidenceRouter import CostEvidenceRouter, blob_storage
    monkeypatch.setenv('COST_EVIDENCE_MAX_BYTES', '1024')
    monkeypatch.setattr(blob_storage, 'fingerprint_file_version', lambda key, **kwargs: dict(
        policy='blob-sha256-v1', bucket=blob_storage.bucket_name, object_key=key,
        version_id=kwargs.get('version_id') or 'synthetic-version', size=7, sha256='a' * 64))
    f = charge_review
    app = FastAPI(); app.include_router(CostEvidenceRouter)
    f.user = SimpleNamespace(id=f.reviewer, roles=[])
    def policy(permissions=PERMISSIONS, modules={'INVENTORY', 'ORDERS'}):
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.orgs[0],),
            permission_names=frozenset(permissions), module_names=frozenset(modules),
            field_permissions={'FINANCIAL': 'View_Financials', 'SUPPLIER_IDENTITY': 'View_Supplier'})
    policy(); f.policy = policy
    def database():
        with f.factory() as db: yield db
    replacements = {'get_db': database, 'get_current_user': lambda: f.user,
        'get_org_context': lambda: f.context, 'get_request_policy': lambda: f.user.access_policy}
    def override(dependant):
        for dep in dependant.dependencies:
            name = getattr(dep.call, '__name__', '')
            if name in replacements: app.dependency_overrides[dep.call] = replacements[name]
            override(dep)
    for route in app.routes:
        if hasattr(route, 'dependant'): override(route.dependant)
    f.url = f'/inventory/cost-evidence/pools/{f.pool}/proposals/{f.payload.operation_key}/cases'
    with TestClient(app) as client:
        f.client = client
        yield f


def test_evidence_list_is_explicit_safe_projection(evidence_api):
    f = evidence_api
    response = f.client.get(f.url)
    assert response.status_code == 200, response.text
    row = response.json()['items'][0]
    assert row['declaration']['eligible_amount'] == '12.340000'
    assert row['supplier_name'] == 'Synthetic charge issuer'
    assert set(row['documents'][0]) == {'id', 'label', 'doc_type'}
    assert 'file_path' not in response.text and 'synthetic/not-a-real-file' not in response.text
    assert f.client.get('/inventory/cost-evidence/documents?limit=1').json()['total'] == 1
    assert f.client.get('/inventory/cost-evidence/suppliers?limit=1').json()['total'] == 1


@pytest.mark.parametrize('missing', sorted(PERMISSIONS - {'Manage_Financials'}))
def test_every_read_requires_all_evidence_permissions(evidence_api, missing):
    f = evidence_api; f.policy(PERMISSIONS - {missing})
    for url in [f.url, '/inventory/cost-evidence/suppliers', '/inventory/cost-evidence/documents']:
        assert f.client.get(url).status_code == 403


@pytest.mark.parametrize('module', ['INVENTORY', 'ORDERS'])
def test_evidence_requires_both_modules(evidence_api, module):
    f = evidence_api; f.policy(modules={module})
    assert f.client.get(f.url).status_code == 403


def test_independent_review_retry_and_readonly_user(evidence_api):
    f = evidence_api
    body = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Checked synthetic invoice')
    url = f.url + f'/{f.case_key}/review'
    f.policy(PERMISSIONS - {'Manage_Financials'})
    assert f.client.post(url, json=body).status_code == 403
    f.policy()
    first = f.client.post(url, json=body)
    assert first.status_code == 200, first.text
    assert not first.json()['replayed']
    assert f.client.post(url, json=body).json()['replayed']
    assert f.client.get(f.url).json()['items'][0]['status'] == 'APPROVED'


def test_request_retry_and_self_review_denied(evidence_api):
    f = evidence_api
    body = dict(operation_key=str(uuid4()), reason='Check original evidence', declaration=f.declaration.model_dump(mode='json'))
    response = f.client.post(f.url, json=body)
    assert response.status_code == 200, response.text
    assert f.client.post(f.url, json=body).json()['replayed']
    decision = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Self')
    assert f.client.post(f.url + '/' + response.json()['case_key'] + '/review', json=decision).status_code == 403


def test_foreign_company_and_invalid_pagination_denied(evidence_api):
    from Utils.org_filter import OrgContext
    f = evidence_api
    assert f.client.get(f.url + '?limit=101').status_code == 422
    f.context = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    assert f.client.get(f.url).status_code == 404
    assert f.client.get('/inventory/cost-evidence/documents').json()['items'] == []


def test_document_download_is_scoped_and_hides_storage_key(evidence_api, monkeypatch):
    from io import BytesIO
    from Routes.Inventory.CostEvidenceRouter import blob_storage
    from Utils.org_filter import OrgContext
    f = evidence_api; calls = []
    def load(key):
        calls.append(key)
        return BytesIO(b'synthetic invoice'), 'application/pdf', 'synthetic.pdf'
    monkeypatch.setattr(blob_storage, 'get_file', load)
    url = f'/inventory/cost-evidence/documents/{f.evidence.document_id}/download'
    response = f.client.get(url)
    assert response.status_code == 200, response.text
    assert response.content == b'synthetic invoice'
    assert response.headers['cache-control'] == 'no-store'
    assert 'synthetic/not-a-real-file' not in str(response.headers)
    f.context = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    assert f.client.get(url).status_code == 404
    assert len(calls) == 1


def test_explicit_field_denial_overrides_route_permissions(evidence_api):
    f = evidence_api
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.orgs[0],),
        permission_names=frozenset(PERMISSIONS), module_names=frozenset({'INVENTORY', 'ORDERS'}), field_permissions={})
    assert f.client.get(f.url).status_code == 403


def test_changed_document_blocks_decision(evidence_api):
    from Model.containermgmt.Orders.OrderDocument import OrderDocument
    f = evidence_api
    with f.factory.begin() as db: db.get(OrderDocument, str(f.evidence.document_id)).file_size = 987
    body = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Changed source')
    assert f.client.post(f.url + f'/{f.case_key}/review', json=body).status_code == 409


@pytest.mark.parametrize('kind', ['PAYMENT', 'VENDOR_QUOTE', 'PO'])
def test_unsupported_or_unbound_parent_documents_are_not_selectable(evidence_api, kind):
    from Model.containermgmt.Orders.OrderDocument import OrderDocument
    f = evidence_api
    with f.factory.begin() as db: db.get(OrderDocument, str(f.evidence.document_id)).entity_type = kind
    assert f.client.get('/inventory/cost-evidence/documents').json()['items'] == []
    body = dict(operation_key=str(uuid4()), reason='Cannot use hidden document', declaration=f.declaration.model_dump(mode='json'))
    assert f.client.post(f.url, json=body).status_code == 404


def test_public_content_request_review_and_exact_download(evidence_api, monkeypatch):
    from Routes.Inventory.CostEvidenceRouter import blob_storage
    f = evidence_api
    f.user.id = f.actor
    request = dict(operation_key=str(uuid4()), reason='Check content', declaration=f.declaration.model_dump(mode='json'))
    response = f.client.post(f.url, json=request)
    assert response.status_code == 200, response.text
    case_key = response.json()['case_key']
    assert f.client.post(f.url, json=request).json()['replayed']
    row = next(item for item in f.client.get(f.url).json()['items'] if item['case_key'] == case_key)
    assert row['source_version'] == 2
    assert 'document_content' not in row
    f.user.id = f.reviewer
    decision = dict(operation_key=str(uuid4()), expected_version=1, outcome='APPROVED', reason='Inspected pinned evidence')
    response = f.client.post(f.url + f'/{case_key}/review', json=decision)
    assert response.status_code == 200, response.text
    assert f.client.post(f.url + f'/{case_key}/review', json=decision).json()['replayed']
    seen = []
    def read(fingerprint, **kwargs):
        seen.append(fingerprint)
        return b'invoice'
    monkeypatch.setattr(blob_storage, 'read_verified_file_version', read)
    url = f.url + f'/{case_key}/documents/{f.evidence.document_id}/download'
    assert f.client.get(url).content == b'invoice'
    assert seen[0]['version_id'] == 'synthetic-version'
    from Utils.org_filter import OrgContext
    f.context = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    assert f.client.get(url).status_code == 404
    assert len(seen) == 1


def test_missing_capture_configuration_blocks_without_save(evidence_api, monkeypatch):
    f = evidence_api; monkeypatch.delenv('COST_EVIDENCE_MAX_BYTES')
    body = dict(operation_key=str(uuid4()), reason='Capture', declaration=f.declaration.model_dump(mode='json'))
    assert f.client.post(f.url, json=body).status_code == 503


def test_metadata_only_download_cannot_masquerade_as_pinned(evidence_api):
    f = evidence_api
    url = f.url + f'/{f.case_key}/documents/{f.evidence.document_id}/download'
    assert f.client.get(url).status_code == 409
    f.policy(PERMISSIONS - {'View_OrderDocument'})
    assert f.client.get(url).status_code == 403


def test_source_change_during_storage_read_blocks_request(evidence_api, monkeypatch):
    from Routes.Inventory.CostEvidenceRouter import blob_storage
    from Model.containermgmt.Orders.OrderDocument import OrderDocument
    f = evidence_api
    original = blob_storage.fingerprint_file_version
    def changed(key, **kwargs):
        value = original(key, **kwargs)
        with f.factory.begin() as db:
            db.get(OrderDocument, str(f.evidence.document_id)).title = 'changed during I/O'
        return value
    monkeypatch.setattr(blob_storage, 'fingerprint_file_version', changed)
    body = dict(operation_key=str(uuid4()), reason='Capture', declaration=f.declaration.model_dump(mode='json'))
    assert f.client.post(f.url, json=body).status_code == 409
    assert f.client.get(f.url).json()['total'] == 1


def test_anonymous_pinned_download_denied(evidence_api):
    f = evidence_api
    for dependency in list(f.client.app.dependency_overrides):
        if getattr(dependency, '__name__', '') == 'get_current_user':
            del f.client.app.dependency_overrides[dependency]
    response = f.client.get(f.url + f'/{f.case_key}/documents/{f.evidence.document_id}/download')
    assert response.status_code in (401, 403)
