from sqlalchemy.dialects import postgresql

from Services.dashboard_registry import (
    ACTIVE_PO_EXCLUDED_STATUSES,
    PENDING_PO_STATUSES,
    build_demurrage_overdue_clause,
)


def test_demurrage_clause_uses_real_orm_table_and_column_names():
    sql = str(
        build_demurrage_overdue_clause().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "containermgmt.bill_of_landing" in sql
    assert "containermgmt.container_details" in sql
    assert '"ArrivalDate"' in sql
    assert '"FreeDays"' in sql
    assert '"BillOfLanding"."ArrivalDate"' not in sql
    assert '"free_days"' not in sql


def test_purchase_order_dashboard_statuses_match_stored_case():
    assert ACTIVE_PO_EXCLUDED_STATUSES == ("COMPLETED", "CANCELLED", "DRAFT")
    assert PENDING_PO_STATUSES == ("DRAFT", "SUBMITTED", "PENDING_APPROVAL")
