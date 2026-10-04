from types import SimpleNamespace
from unittest.mock import MagicMock
import importlib

from Services.report_data_resolvers import _asset_data_uri, _resolve_company_profile
from Routes.Reports.ReportRouter import _print_asset_extension
from Services.report_customization_service import initialize_org_reporting
from Services.report_time_service import DEFAULT_REPORT_TIMEZONE, report_timezone
from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile
from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Model.containermgmt.Report.ReportTemplateAssignment import ReportTemplateAssignment
blob_storage_module = importlib.import_module("Utils.blob_storage")


def test_company_profile_prefers_tenant_print_identity():
    organisation = SimpleNamespace(name="Tenant Ltd", display_name="Tenant")
    profile = SimpleNamespace(
        legal_name="Tenant Legal Ltd",
        address="Victoria, Mahe",
        tax_id="TIN-42",
        contact_phone="+248 400 0000",
        contact_email="buying@tenant.sc",
        logo_asset_key="reports/1/logo.png",
        stamp_asset_key=None,
        signature_asset_key=None,
        bank_details={"bank_name": "Island Bank"},
        default_terms={"rfq": ["Reply before closing."]},
        brand_color="#123456",
        font_family="Inter",
        locale="en-SC",
        timezone="Indian/Mahe",
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [organisation, profile]

    result = _resolve_company_profile(db, 7)

    assert result["name"] == "Tenant Legal Ltd"
    assert result["email"] == "buying@tenant.sc"
    assert result["bank_details"] == {"bank_name": "Island Bank"}
    assert result["default_terms"]["rfq"] == ["Reply before closing."]
    assert result["brand_color"] == "#123456"


def test_company_profile_has_neutral_fallback_without_org():
    result = _resolve_company_profile(MagicMock(), None)

    assert result["name"] == "Organisation"
    assert result["locale"] == "en-SC"
    assert result["timezone"] == "Indian/Mahe"


def test_asset_data_uri_embeds_stored_image(monkeypatch):
    body = MagicMock()
    body.read.return_value = b"image-bytes"
    monkeypatch.setattr(
        blob_storage_module.blob_storage,
        "get_file",
        lambda key: (body, "image/png", "logo.png"),
    )

    result = _asset_data_uri("reports/org-1/logo/file.png")

    assert result == "data:image/png;base64,aW1hZ2UtYnl0ZXM="


def test_print_asset_type_uses_file_signature_not_claimed_content_type():
    assert _print_asset_extension(b"\x89PNG\r\n\x1a\nrest") == ".png"
    assert _print_asset_extension(b"<script>alert(1)</script>") is None


def test_report_timezone_falls_back_when_tenant_value_is_invalid():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        timezone="Not/A-Timezone"
    )

    assert report_timezone(db, 7).key == DEFAULT_REPORT_TIMEZONE


class _InitQuery:
    def __init__(self, model, templates):
        self.model = model
        self.templates = templates

    def filter(self, *criteria):
        return self

    def order_by(self, *criteria):
        return self

    def first(self):
        return None

    def all(self):
        return self.templates if self.model is ReportTemplate else []


class _InitDb:
    def __init__(self, templates):
        self.templates = templates
        self.added = []

    def query(self, model):
        return _InitQuery(model, self.templates)

    def add(self, value):
        self.added.append(value)


def test_new_org_gets_profile_and_one_default_per_entity_type():
    templates = [
        SimpleNamespace(id=1, entity_type="PurchaseOrder", default_params={"copies": 1}),
        SimpleNamespace(id=2, entity_type="PurchaseOrder", default_params={}),
        SimpleNamespace(id=3, entity_type="DefectReport", default_params={}),
    ]
    db = _InitDb(templates)

    initialize_org_reporting(db, org_id=11, user_id=42)

    profiles = [item for item in db.added if isinstance(item, OrgPrintProfile)]
    assignments = [item for item in db.added if isinstance(item, ReportTemplateAssignment)]
    assert len(profiles) == 1
    assert profiles[0].org_id == 11
    assert [item.is_default for item in assignments] == [True, False, True]
    assert assignments[0].default_options == {"copies": 1}
    assert all(item.created_by == 42 for item in assignments)
