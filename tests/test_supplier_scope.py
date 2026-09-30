from sqlalchemy import column

from Utils.org_filter import OrgContext, apply_shared_or_org_filter


class ScopedSupplier:
    org_id = column("org_id")
    is_shared = column("is_shared")


class CapturingQuery:
    def __init__(self):
        self.criteria = []

    def filter(self, *criteria):
        self.criteria.extend(criteria)
        return self


def _sql(query):
    return str(query.criteria[0].compile(compile_kwargs={"literal_binds": True}))


def test_selected_tenant_sees_shared_and_selected_suppliers():
    context = OrgContext(
        current_org_id=1,
        allowed_org_ids=[1, 2, 3],
        is_root=True,
        selected_org_id=2,
    )
    query = apply_shared_or_org_filter(CapturingQuery(), ScopedSupplier, context)

    sql = _sql(query)
    assert "is_shared IS true" in sql
    assert "org_id = 2" in sql


def test_unselected_context_uses_allowed_tenant_set():
    context = OrgContext(
        current_org_id=2,
        allowed_org_ids=[2, 3],
        is_root=False,
    )
    query = apply_shared_or_org_filter(CapturingQuery(), ScopedSupplier, context)

    sql = _sql(query)
    assert "is_shared IS true" in sql
    assert "org_id IN (2, 3)" in sql
