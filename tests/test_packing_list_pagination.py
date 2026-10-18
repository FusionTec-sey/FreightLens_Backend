import asyncio
import importlib
import os


os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")
packing_router = importlib.import_module("Routes.Orders.PackingListRouter")


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.start = 0
        self.size = None

    def order_by(self, *args):
        return self

    def count(self):
        return len(self.rows)

    def offset(self, value):
        self.start = value
        return self

    def limit(self, value):
        self.size = value
        return self

    def all(self):
        return self.rows[self.start:self.start + self.size]


def test_packing_list_pagination_uses_database_offset_and_limit(monkeypatch):
    query = FakeQuery([{"id": number} for number in range(1, 6)])
    monkeypatch.setattr(packing_router, "_base_query", lambda db, org: query)
    monkeypatch.setattr(packing_router, "format_packing_list", lambda row: row)

    result = asyncio.run(packing_router.list_packing_lists(
        page=2, limit=2, po_id=None, container_id=None, status=None,
        search=None, db=object(), org_context=object(), current_user=object(),
    ))

    assert result == {
        "items": [{"id": 3}, {"id": 4}],
        "total": 5,
        "page": 2,
        "pages": 3,
        "limit": 2,
    }
    assert query.start == 2
    assert query.size == 2
