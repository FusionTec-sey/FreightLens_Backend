import importlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from Schema.ReportDatasetSchema import DatasetQuerySpec
from Schema.ReportSchema import ReportTemplateCreate
from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Services.report_template_service import resolve_template_identity
from Utils.org_filter import OrgContext


report_router_module = importlib.import_module("Routes.Reports.ReportRouter")


def _base_template_payload():
    return {
        "name": "PO layout",
        "slug": "po_layout",
        "resolver_key": "purchase_order",
        "template_type": "DOCUMENT",
    }


def test_document_identity_is_derived_from_resolver_catalog():
    entity_type, category = resolve_template_identity("purchase_order", "DOCUMENT")

    assert entity_type == "PurchaseOrder"
    assert category == "ORDERS"


def test_dataset_identity_is_derived_from_dataset_catalog():
    entity_type, category = resolve_template_identity(
        "containers_by_vendor",
        "OPERATIONAL_TABULAR",
    )

    assert entity_type == "containers_by_vendor"
    assert category == "LOGISTICS"


def test_unknown_template_fields_are_rejected_instead_of_dropped():
    payload = _base_template_payload()
    payload["custom_html"] = "<p>lost before this fix</p>"

    with pytest.raises(ValidationError):
        ReportTemplateCreate.model_validate(payload)


def test_template_without_published_version_has_no_fabricated_version_number():
    template = ReportTemplate(active_version_id=None)
    template.versions = []

    assert template.active_version_number is None


def test_legacy_camel_case_layout_is_normalized():
    payload = _base_template_payload()
    payload.update({
        "table_config": {
            "groupBy": "supplier",
            "sortOrder": "desc",
            "selectedSuppliers": [4],
        },
        "paper_settings": {
            "pageSize": "A3",
            "orientation": "landscape",
            "repeatHeaderOnBreak": False,
        },
    })

    template = ReportTemplateCreate.model_validate(payload)

    assert template.table_config.group_by == "supplier"
    assert template.table_config.supplier_ids == [4]
    assert template.paper_settings.page_size == "A3"
    assert template.paper_settings.repeat_header is False


def test_dataset_request_uses_flat_validated_paper_contract():
    spec = DatasetQuerySpec.model_validate({
        "template_id": 12,
        "page_size": "A3",
        "margin_top": "8mm",
    })

    assert spec.template_id == 12
    assert spec.page_size == "A3"
    with pytest.raises(ValidationError):
        DatasetQuerySpec.model_validate({"paper_settings": {"page_size": "A3"}})


def test_saved_dataset_template_is_applied_server_side(monkeypatch):
    template = SimpleNamespace(
        template_type="OPERATIONAL_TABULAR",
        resolver_key="containers_by_vendor",
        is_active_for_org=True,
        table_config={
            "group_by": "supplier_name",
            "sort_by": "arrival_date",
            "sort_order": "desc",
            "columns": [{"key": "container_no", "visible": True}],
        },
        paper_settings={
            "page_size": "A3",
            "orientation": "landscape",
            "margin_top": "8mm",
            "margin_bottom": "8mm",
            "margin_left": "8mm",
            "margin_right": "8mm",
            "repeat_header": True,
            "break_per_group": True,
            "sheet_per_group": False,
        },
    )
    monkeypatch.setattr(report_router_module, "get_template", lambda *args: template)
    context = OrgContext(current_org_id=1, allowed_org_ids=[1], is_root=True)

    result = report_router_module._apply_saved_dataset_template(
        "containers_by_vendor",
        DatasetQuerySpec(template_id=12),
        object(),
        context,
    )

    assert result.group_by == "supplier_name"
    assert result.page_size == "A3"
    assert result.break_per_group is True
    assert result.layout_columns[0].key == "container_no"


def test_saved_dataset_template_must_match_route(monkeypatch):
    template = SimpleNamespace(
        template_type="OPERATIONAL_TABULAR",
        resolver_key="purchase_order_register",
        is_active_for_org=True,
    )
    monkeypatch.setattr(report_router_module, "get_template", lambda *args: template)
    context = OrgContext(current_org_id=1, allowed_org_ids=[1], is_root=True)

    with pytest.raises(HTTPException) as exc_info:
        report_router_module._apply_saved_dataset_template(
            "containers_by_vendor",
            DatasetQuerySpec(template_id=12),
            object(),
            context,
        )

    assert exc_info.value.status_code == 422
