from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from reporting.catalog.builtin import PURCHASE_ORDER_DATASET
from reporting.policy import AccessPolicy
from reporting.query import QueryCompiler, QueryFilter, QueryRequest


def _policy(*permissions, org_ids=(7,)):
    return AccessPolicy(
        user=SimpleNamespace(id=1, username="reporter", org_id=org_ids[0]),
        org_ids=org_ids,
        permission_names=frozenset(permissions),
        module_names=frozenset({"ORDERS"}),
        field_permissions={
            "FINANCIAL": "View_Financials",
            "SUPPLIER_IDENTITY": "View_Supplier",
        },
    )


def _sql(compiled):
    return str(compiled.statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))


def test_compiler_forces_organisation_scope_and_row_cap():
    compiled = QueryCompiler().compile(
        PURCHASE_ORDER_DATASET,
        QueryRequest(fields=("po_number", "status"), limit=50_000),
        _policy("View_Report", org_ids=(7, 9)),
    )

    sql = _sql(compiled)
    assert "purchase_orders.org_id IN (7, 9)" in sql
    assert "purchase_orders.is_deleted IS false" in sql
    assert compiled.effective_limit == 10_000


def test_compiler_rejects_restricted_field_without_field_permission():
    with pytest.raises(HTTPException) as exc_info:
        QueryCompiler().compile(
            PURCHASE_ORDER_DATASET,
            QueryRequest(fields=("po_number", "total_amount_base")),
            _policy("View_Report"),
        )

    assert exc_info.value.status_code == 403


def test_compiler_accepts_declared_filters_and_status_values():
    compiled = QueryCompiler().compile(
        PURCHASE_ORDER_DATASET,
        QueryRequest(
            fields=("po_number", "status", "total_amount_base"),
            filters=(
                QueryFilter("status", "in", ["ORDERED", "COMPLETED"]),
                QueryFilter("total_amount_base", "gte", 1000),
            ),
            sort_by="total_amount_base",
            sort_desc=True,
        ),
        _policy("View_Report", "View_Financials"),
    )

    sql = _sql(compiled)
    assert "status IN ('ORDERED', 'COMPLETED')" in sql
    assert "total_amount_base >= 1000" in sql
    assert "total_amount_base DESC NULLS LAST" in sql


def test_compiler_rejects_unknown_fields_operators_and_enum_values():
    compiler = QueryCompiler()
    policy = _policy("View_Report")

    for request in (
        QueryRequest(fields=("database_password",)),
        QueryRequest(fields=("status",), filters=(QueryFilter("status", "contains", "ORD"),)),
        QueryRequest(fields=("status",), filters=(QueryFilter("status", "eq", "completed"),)),
        QueryRequest(fields=("status",), filters=(QueryFilter("status", "in", "ORDERED"),)),
    ):
        with pytest.raises(HTTPException) as exc_info:
            compiler.compile(PURCHASE_ORDER_DATASET, request, policy)
        assert exc_info.value.status_code == 400


def test_compiler_rejects_dataset_without_module_or_permission():
    with pytest.raises(HTTPException) as exc_info:
        QueryCompiler().compile(
            PURCHASE_ORDER_DATASET,
            QueryRequest(fields=("po_number",)),
            _policy(),
        )

    assert exc_info.value.status_code == 403
