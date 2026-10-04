import importlib
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from Schema.ReportDatasetSchema import DatasetQuerySpec
from auth.policy import AccessPolicy
from Services.report_data_resolvers import get_resolver
from Services.report_dataset_service import (
    DEFAULT_FREE_DAYS,
    PDF_ROW_LIMIT,
    _apply_container_date_range,
    _fetch_query_rows,
)
from Services.report_render_engine import build_full_html
from Utils.org_filter import OrgContext


report_router_module = importlib.import_module("Routes.Reports.ReportRouter")


class _Query:
    def __init__(self, count, rows):
        self.count_value = count
        self.rows = rows
        self.offset_value = None
        self.limit_value = None

    def count(self):
        return self.count_value

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        return self.rows


class _CapturingQuery:
    def __init__(self):
        self.criteria = []

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self


def _role(*permissions):
    return SimpleNamespace(
        name="Tenant_User",
        permissions=[SimpleNamespace(name=permission) for permission in permissions],
    )


def test_screen_dataset_query_applies_limit_and_offset():
    query = _Query(count=125, rows=["page"])

    rows, total = _fetch_query_rows(query, DatasetQuerySpec(page=3, limit=25))

    assert rows == ["page"]
    assert total == 125
    assert query.offset_value == 50
    assert query.limit_value == 25


def test_pdf_dataset_query_refuses_unbounded_export():
    query = _Query(count=PDF_ROW_LIMIT + 1, rows=[])

    with pytest.raises(HTTPException) as exc_info:
        _fetch_query_rows(query, DatasetQuerySpec(format="pdf"))

    assert exc_info.value.status_code == 413


def test_container_date_bounds_use_the_same_coalesced_date():
    query = _CapturingQuery()

    _apply_container_date_range(
        query,
        DatasetQuerySpec(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)),
    )

    assert len(query.criteria) == 2
    expressions = [str(criterion) for criterion in query.criteria]
    assert all("coalesce" in expression.lower() for expression in expressions)
    assert all("ArrivalDate" in expression for expression in expressions)
    assert all("unloaded_at_port" in expression for expression in expressions)


def test_each_document_resolver_declares_print_permissions():
    assert get_resolver("defect_report").print_permissions == ("View_Defect",)
    assert "Print_PurchaseOrder" in get_resolver("purchase_order").print_permissions


def test_render_requires_active_template_and_explicit_org_selection():
    template = SimpleNamespace(
        resolver_key="purchase_order",
        is_active_for_org=True,
    )
    multi_org = OrgContext(
        current_org_id=1,
        allowed_org_ids=[1, 2],
        is_root=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        report_router_module._authorize_document_render(
            template,
            SimpleNamespace(roles=[_role("Print_PurchaseOrder")]),
            multi_org,
        )

    assert exc_info.value.status_code == 400


def test_render_uses_resolver_permission_and_activation():
    context = OrgContext(
        current_org_id=1,
        allowed_org_ids=[1],
        is_root=True,
        selected_org_id=1,
    )
    inactive = SimpleNamespace(
        resolver_key="defect_report",
        is_active_for_org=False,
    )
    user = SimpleNamespace(roles=[_role("View_Defect")])

    with pytest.raises(HTTPException) as exc_info:
        report_router_module._authorize_document_render(inactive, user, context)
    assert exc_info.value.status_code == 403

    active = SimpleNamespace(resolver_key="defect_report", is_active_for_org=True)
    assert report_router_module._authorize_document_render(active, user, context).key == "defect_report"


def test_document_header_and_footer_are_running_page_elements():
    html = build_full_html(
        html_body="<p>Body</p>",
        header_html="Header",
        footer_html="Footer",
    )

    assert "position: running(report-header)" in html
    assert "content: element(report-header)" in html
    assert "position: running(report-footer)" in html
    assert "content: element(report-footer)" in html


def test_default_free_days_matches_document_resolver():
    assert DEFAULT_FREE_DAYS == 14


def test_multi_org_dataset_requires_cross_org_permission():
    context = OrgContext(current_org_id=1, allowed_org_ids=[1, 2], is_root=False)
    policy = AccessPolicy(
        user=SimpleNamespace(id=7),
        org_ids=(1, 2),
        permission_names=frozenset(),
        module_names=frozenset({"ORDERS"}),
        field_permissions={},
    )

    with pytest.raises(HTTPException) as exc_info:
        report_router_module._enforce_dataset_org_scope(
            DatasetQuerySpec(), MagicMock(), context, policy
        )

    assert exc_info.value.status_code == 403


def test_all_org_dataset_requires_every_active_org():
    context = OrgContext(current_org_id=1, allowed_org_ids=[1, 2], is_root=False)
    policy = AccessPolicy(
        user=SimpleNamespace(id=7),
        org_ids=(1, 2),
        permission_names=frozenset({"Cross_Org_Report"}),
        module_names=frozenset({"ORDERS"}),
        field_permissions={},
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [(1,), (2,), (3,)]

    with pytest.raises(HTTPException) as exc_info:
        report_router_module._enforce_dataset_org_scope(
            DatasetQuerySpec(custom_filters={"all_organisations": True}),
            db,
            context,
            policy,
        )

    assert exc_info.value.status_code == 403
