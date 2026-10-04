"""T17 immutable invoice artifact and explicit print-state contracts."""
from hashlib import sha256
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from Model.containermgmt.Orders.SalesInvoicePrint import SalesInvoiceArtifact
from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile
from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Model.containermgmt.Report.ReportTemplateAssignment import ReportTemplateAssignment
from Schema.SalesInvoicePrintSchema import (
    SalesInvoicePrintHandoff, SalesInvoicePrintRequest, SalesInvoicePrintTransition,
)
from Services.inventory_posting_service import PostingConflict
from Services.sales_invoice_print_service import (
    create_invoice_print_job, handoff_print_job, read_artifact_bytes,
    resolve_print_job,
)
from auth.policy import AccessPolicy
from tests.test_sales_posting import posting, _create, _finalize  # noqa: F401
from tests.test_sales_price_floor_cases import floor_api  # noqa: F401
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


class ExactStorage:
    def __init__(self):
        self.bucket_name = "synthetic-invoice-test"
        self.objects = {}

    def upload_file(self, content, folder, original_filename):
        key = f"{folder}/{uuid4()}-{original_filename}"
        self.objects[key] = bytes(content)
        return key

    def fingerprint_file_version(self, key, *, max_bytes, version_id=None):
        content = self.objects[key]
        assert len(content) <= max_bytes
        return {"policy": "blob-sha256-v1", "bucket": self.bucket_name,
                "object_key": key, "version_id": version_id or "exact-version-1",
                "size": len(content), "sha256": sha256(content).hexdigest()}

    def read_verified_file_version(self, fingerprint, *, max_bytes):
        assert fingerprint["bucket"] == self.bucket_name
        assert fingerprint["version_id"] == "exact-version-1"
        content = self.objects[fingerprint["object_key"]]
        assert len(content) <= max_bytes and sha256(content).hexdigest() == fingerprint["sha256"]
        return content


def _configure(f):
    _create(f); _finalize(f)
    profile = f.db.query(OrgPrintProfile).filter_by(org_id=f.org_a).one_or_none()
    if profile is None:
        profile = OrgPrintProfile(org_id=f.org_a, created_by=f.user.id)
        f.db.add(profile)
    profile.legal_name = "Synthetic Retail Ltd"
    profile.address = "Synthetic address"
    profile.tax_id = "VAT-SYNTHETIC"
    profile.contact_email = "invoice@example.test"
    profile.default_terms = {"invoice": "Synthetic invoice terms"}
    template = f.db.query(ReportTemplate).filter_by(
        slug="sales_invoice", is_system=True, is_deleted=False).one()
    f.db.query(ReportTemplateAssignment).filter_by(
        org_id=f.org_a, entity_type="SalesInvoice", is_deleted=False).update(
        {"is_default": False}, synchronize_session=False)
    assignment = f.db.query(ReportTemplateAssignment).filter_by(
        org_id=f.org_a, template_id=template.id, is_deleted=False).one_or_none()
    if assignment is None:
        assignment = ReportTemplateAssignment(org_id=f.org_a, template_id=template.id,
            entity_type="SalesInvoice", is_active=True, is_default=True,
            default_options={}, created_by=f.user.id)
        f.db.add(assignment)
    else:
        assignment.is_active = assignment.is_default = True
    f.db.commit()
    return template


def _request(f, template):
    return SalesInvoicePrintRequest(
        job_key=uuid4(), operation_key=uuid4(), artifact_key=uuid4(),
        invoice_key=f.posting_invoice_key, kind="ORIGINAL",
        expected_template_id=template.id,
        expected_template_version_id=template.active_version_id)


def test_original_replay_exact_version_and_print_state(posting):
    f = posting; template = _configure(f); storage = ExactStorage()
    factory = sessionmaker(bind=f.db.get_bind())
    payload = _request(f, template)
    rendered = []
    def pdf(html):
        rendered.append(html)
        return b"%PDF-1.7\nsynthetic invoice\n%%EOF"
    first = create_invoice_print_job(factory, f.context, f.user.id, payload,
        authorize=lambda db: None, storage=storage, pdf_renderer=pdf)
    assert not first.replayed and first.result["status"] == "READY"
    assert len(rendered) == 1
    replay = create_invoice_print_job(factory, f.context, f.user.id, payload,
        authorize=lambda db: None, storage=storage, pdf_renderer=pdf)
    assert replay.replayed and len(rendered) == 1
    with factory() as db:
        artifact = db.query(SalesInvoiceArtifact).filter_by(
            artifact_key=payload.artifact_key).one()
        assert "fulfilment_status" not in artifact.data_snapshot["data"]["invoice"]
        assert all("account_ref" not in item for item in artifact.data_snapshot["data"]["payments"])
        row, content = read_artifact_bytes(db, f.context, artifact.artifact_key,
            authorize=lambda session: None, storage=storage)
        assert row.storage_fingerprint["version_id"] == "exact-version-1"
        assert content.startswith(b"%PDF")
    handoff = handoff_print_job(factory, f.context, f.user.id, payload.job_key,
        SalesInvoicePrintHandoff(operation_key=uuid4(), expected_version=1),
        authorize=lambda db: None)
    assert handoff.result["status"] == "UNCERTAIN" and handoff.result["version"] == 2
    resolved = resolve_print_job(factory, f.context, f.user.id, payload.job_key,
        SalesInvoicePrintTransition(operation_key=uuid4(), expected_version=2,
            outcome="PRINTED", note="Synthetic operator confirmed the printed page"),
        authorize=lambda db: None)
    assert resolved.result["status"] == "PRINTED" and resolved.result["version"] == 3


def test_copy_uses_frozen_original_and_server_owned_visible_mark(posting):
    f = posting; template = _configure(f); storage = ExactStorage()
    factory = sessionmaker(bind=f.db.get_bind())
    original = _request(f, template)
    create_invoice_print_job(factory, f.context, f.user.id, original,
        authorize=lambda db: None, storage=storage,
        pdf_renderer=lambda html: b"%PDF original")
    handoff_print_job(factory, f.context, f.user.id, original.job_key,
        SalesInvoicePrintHandoff(operation_key=uuid4(), expected_version=1),
        authorize=lambda db: None)
    resolve_print_job(factory, f.context, f.user.id, original.job_key,
        SalesInvoicePrintTransition(operation_key=uuid4(), expected_version=2,
            outcome="PRINTED", note="Synthetic original print confirmed"),
        authorize=lambda db: None)
    f.db.query(OrgPrintProfile).filter_by(org_id=f.org_a).update(
        {"legal_name": "Changed after original"}, synchronize_session=False)
    f.db.commit()
    captured = []
    copy = SalesInvoicePrintRequest(job_key=uuid4(), operation_key=uuid4(),
        artifact_key=uuid4(), invoice_key=f.posting_invoice_key, kind="COPY",
        source_artifact_key=original.artifact_key)
    outcome = create_invoice_print_job(factory, f.context, f.user.id, copy,
        authorize=lambda db: None, storage=storage,
        pdf_renderer=lambda html: captured.append(html) or b"%PDF copy")
    assert outcome.result["artifact"]["artifact_kind"] == "COPY"
    assert "COPY 1" in captured[0]
    with factory() as db:
        original_row = db.query(SalesInvoiceArtifact).filter_by(
            artifact_key=original.artifact_key).one()
        copy_row = db.query(SalesInvoiceArtifact).filter_by(
            artifact_key=copy.artifact_key).one()
        assert copy_row.copy_number == 1
        assert copy_row.source_artifact_key == original_row.artifact_key
        assert copy_row.data_snapshot == original_row.data_snapshot
        assert copy_row.data_snapshot["data"]["company"]["legal_name"] == "Synthetic Retail Ltd"


def test_unresolved_job_blocks_another_invoice_artifact(posting):
    f = posting; template = _configure(f); storage = ExactStorage()
    factory = sessionmaker(bind=f.db.get_bind())
    original = _request(f, template)
    create_invoice_print_job(factory, f.context, f.user.id, original,
        authorize=lambda db: None, storage=storage,
        pdf_renderer=lambda html: b"%PDF original")
    copy = SalesInvoicePrintRequest(job_key=uuid4(), operation_key=uuid4(),
        artifact_key=uuid4(), invoice_key=f.posting_invoice_key, kind="COPY",
        source_artifact_key=original.artifact_key)
    with pytest.raises(PostingConflict, match="Resolve the current invoice print job"):
        create_invoice_print_job(factory, f.context, f.user.id, copy,
            authorize=lambda db: None, storage=storage,
            pdf_renderer=lambda html: b"%PDF copy")
    with factory() as db:
        assert db.query(SalesInvoiceArtifact).filter_by(
            artifact_key=copy.artifact_key).count() == 0


def test_missing_exact_blob_version_fails_without_artifact(posting):
    f = posting; template = _configure(f); storage = ExactStorage()
    storage.fingerprint_file_version = lambda *args, **kwargs: (_ for _ in ()).throw(
        ValueError("object version unavailable"))
    payload = _request(f, template)
    factory = sessionmaker(bind=f.db.get_bind())
    with pytest.raises(ValueError, match="version unavailable"):
        create_invoice_print_job(factory, f.context, f.user.id, payload,
            authorize=lambda db: None, storage=storage,
            pdf_renderer=lambda html: b"%PDF unavailable")
    with factory() as db:
        assert db.query(SalesInvoiceArtifact).filter_by(
            artifact_key=payload.artifact_key).count() == 0


def test_print_options_endpoint_permission_tenant_and_anonymous_guards(posting):
    from Routes.Orders.SalesInvoicePrintRouter import SalesInvoicePrintRouter
    from auth.policy import get_request_policy
    f = posting; template = _configure(f)
    f.app.include_router(SalesInvoicePrintRouter)
    f.permissions |= {"View_Sale", "Print_SaleInvoice", "Resolve_SalePrint"}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions), module_names=frozenset({"SALES"}),
        field_permissions={"PERSONAL": "View_Personal_Data"})
    url = f"/sales/invoices/{f.posting_invoice_key}/print-options"
    allowed = f.client.get(url)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["template_version_id"] == template.active_version_id
    assert allowed.headers["cache-control"] == "private, no-store"
    policy = f.user.access_policy
    f.user.access_policy = replace(policy, permission_names=frozenset(
        f.permissions - {"Print_SaleInvoice"}))
    assert f.client.get(url).status_code == 403
    f.user.access_policy = policy
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.get(url).status_code == 404
    f.context.current_org_id = f.org_a
    f.context.allowed_org_ids = [f.org_a]
    f.context.is_root = False
    saved = dict(f.app.dependency_overrides)
    try:
        for dependency in f.user_dependencies:
            f.app.dependency_overrides.pop(dependency, None)
        f.app.dependency_overrides.pop(get_request_policy, None)
        assert f.client.get(url).status_code == 401
    finally:
        f.app.dependency_overrides.clear()
        f.app.dependency_overrides.update(saved)
