from types import SimpleNamespace
from unittest.mock import MagicMock
import importlib

from Services.report_data_resolvers import _asset_data_uri, _resolve_company_profile
from Routes.Reports.ReportRouter import _print_asset_extension
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
