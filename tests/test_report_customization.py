from types import SimpleNamespace
from unittest.mock import MagicMock

from Services.report_data_resolvers import _resolve_company_profile


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
