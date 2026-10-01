import importlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from pydantic import ValidationError

from Schema.ReportDatasetSchema import ColumnDefinition, DatasetQuerySpec
from Services.report_render_engine import (
    build_safe_url_fetcher,
    compile_pdf_from_html,
    sanitize_html_fragment,
)
from Services.report_template_validator import validate_template
from Utils.excel_exporter import _format_cell_value
from Utils import reportGenerator


report_router_module = importlib.import_module("Routes.Reports.ReportRouter")


def test_pdf_fetcher_refuses_files_internal_urls_and_relative_paths():
    fetcher = build_safe_url_fetcher()

    for url in ("file:///app/.env", "http://rustfs:9000/private", "../secret.txt"):
        with pytest.raises(ValueError, match="Blocked report resource"):
            fetcher(url)


def test_pdf_fetcher_allows_only_scoped_asset_loader():
    calls = []
    fetcher = build_safe_url_fetcher(
        lambda key: calls.append(key) or {"string": b"image", "mime_type": "image/png"}
    )

    assert fetcher("asset:org/logo.png")["string"] == b"image"
    assert calls == ["org/logo.png"]
    with pytest.raises(ValueError, match="Invalid report asset key"):
        fetcher("asset:../secret")


def test_compile_pdf_always_passes_safe_fetcher(monkeypatch):
    captured = {}

    class FakeHtml:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def write_pdf(self):
            return b"pdf"

    monkeypatch.setattr("Services.report_render_engine.weasyprint.HTML", FakeHtml)

    assert compile_pdf_from_html("<p>ok</p>") == b"pdf"
    with pytest.raises(ValueError):
        captured["url_fetcher"]("http://127.0.0.1/admin")


def test_rendered_fragment_removes_scripts_handlers_and_external_images():
    cleaned = sanitize_html_fragment(
        '<div class="ok" onclick="steal()"><script>steal()</script>'
        '<img src="http://internal/private"><img src="data:image/png;base64,AA=="></div>'
    )

    assert "script" not in cleaned
    assert "onclick" not in cleaned
    assert "http://internal" not in cleaned
    assert "data:image/png" in cleaned


def test_validator_rejects_entity_encoded_javascript_and_external_css_urls():
    valid, errors, _ = validate_template(
        '<a href="jav&#x61;script:alert(1)">bad</a>',
        'body { background-image: url("file:///app/.env"); }',
    )

    assert not valid
    assert any("JavaScript" in error for error in errors)
    assert any("approved data: or asset:" in error for error in errors)


def test_preview_rejects_unsafe_html_before_resolving_data(monkeypatch):
    monkeypatch.setattr(
        report_router_module,
        "resolve_report_data",
        lambda **kwargs: pytest.fail("unsafe preview must be rejected before data resolution"),
    )
    request = SimpleNamespace(
        template_id=None,
        html_content="<script>steal()</script>",
        css_content=None,
        header_html=None,
        footer_html=None,
        resolver_key="purchase_order",
        entity_id=None,
        params=None,
    )

    with pytest.raises(HTTPException) as exc:
        report_router_module.render_report_preview(
            request,
            db=SimpleNamespace(),
            current_user=SimpleNamespace(),
            org_context=SimpleNamespace(),
        )
    assert exc.value.status_code == 422


def test_dataset_query_rejects_code_overrides_and_invalid_margins():
    with pytest.raises(ValidationError):
        DatasetQuerySpec(custom_html="<p>unsafe</p>")
    with pytest.raises(ValidationError):
        DatasetQuerySpec(margin_top='12mm; content: "leak"')


def test_legacy_defect_values_are_html_escaped(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        reportGenerator,
        "compile_pdf_from_html",
        lambda html: captured.setdefault("html", html) and b"pdf",
    )
    defect = SimpleNamespace(
        items=[
            SimpleNamespace(
                is_deleted=False,
                item_description='<img src="file:///app/.env">',
                quantity_affected=1,
                unit="PCS",
                notes="<script>steal()</script>",
            )
        ],
        report_type="GOODS_DEFECT",
        discovery_date="2026-10-01",
        created_at=None,
        container=None,
        purchase_order=None,
        status="OPEN",
        resolution_type=None,
        resolution_notes=None,
        defect_number="DEF-1",
        bill_of_lading_no=None,
        title="Unsafe <b>title</b>",
        description="<script>steal()</script>",
    )

    assert reportGenerator.generate_defect_report_pdf(defect) == b"pdf"
    assert '<img src="file:///app/.env">' not in captured["html"]
    assert "<script>steal()</script>" not in captured["html"]
    assert "&lt;script&gt;steal()&lt;/script&gt;" in captured["html"]


@pytest.mark.parametrize("value", ["=2+2", "+cmd", "-cmd", "@SUM(A1:A2)"])
def test_excel_text_values_are_not_formulas(value):
    worksheet = Workbook().active
    cell = worksheet.cell(row=1, column=1)
    _format_cell_value(cell, value, ColumnDefinition(key="name", label="Name"))

    assert cell.value == f"'{value}"
    assert cell.data_type != "f"
