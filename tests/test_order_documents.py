import asyncio
import importlib
import os
import sys
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost/test")
if "auth.dependencies" in sys.modules and not hasattr(sys.modules["auth.dependencies"], "get_org_context"):
    sys.modules.pop("auth.dependencies", None)
    sys.modules.pop("auth", None)
order_router = importlib.import_module("Routes.Orders.OrderRouter")


class FakeQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args):
        return self

    def join(self, *args):
        return self

    def order_by(self, *args):
        return self

    def limit(self, *args):
        return self

    def first(self):
        return self.value

    def all(self):
        return self.value if isinstance(self.value, list) else [self.value]


class FakeSession:
    def __init__(self, value):
        self.value = value
        self.committed = False

    def query(self, model):
        return FakeQuery(self.value)

    def commit(self):
        self.committed = True


def _user(*permissions, role="employee"):
    permission_objects = [SimpleNamespace(name=name) for name in permissions]
    return SimpleNamespace(roles=[SimpleNamespace(name=role, permissions=permission_objects)])


def _document(**overrides):
    values = {
        "file_path": "orders/PO-1/po_documents/file.pdf",
        "file_name": "file.pdf",
        "mime_type": "application/pdf",
        "is_confidential": False,
        "payment_id": None,
        "entity_type": "PO",
        "doc_type": "PO_DOCUMENT",
        "is_deleted": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_cross_org_document_is_hidden_before_blob_access(monkeypatch):
    doc = _document()
    db = FakeSession(doc)
    monkeypatch.setattr(order_router, "apply_org_filter", lambda query, model, ctx: FakeQuery(None))
    monkeypatch.setattr(
        order_router.blob_storage,
        "get_file",
        lambda key: pytest.fail("cross-organisation blob must not be accessed"),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(order_router.download_order_document(
            str(uuid4()), db=db, org_context=SimpleNamespace(), current_user=_user("View_Document")
        ))
    assert exc.value.status_code == 404


def test_payment_document_requires_financial_clearance(monkeypatch):
    db = FakeSession(_document(payment_id=7, entity_type="PAYMENT"))
    monkeypatch.setattr(order_router, "apply_org_filter", lambda query, model, ctx: query)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(order_router.download_order_document(
            str(uuid4()), db=db, org_context=SimpleNamespace(), current_user=_user("View_Document")
        ))
    assert exc.value.status_code == 403


def test_soft_delete_keeps_the_blob(monkeypatch):
    doc = _document()
    db = FakeSession(doc)
    monkeypatch.setattr(order_router, "apply_org_filter", lambda query, model, ctx: query)
    monkeypatch.setattr(
        order_router.blob_storage,
        "delete_file",
        lambda key: pytest.fail("soft delete must retain the blob"),
    )

    result = asyncio.run(order_router.delete_order_document(
        str(uuid4()), db=db, org_context=SimpleNamespace(), current_user=_user("Delete_Document")
    ))

    assert result == {"success": True}
    assert doc.is_deleted is True
    assert db.committed is True


def test_authorized_document_download_streams_blob(monkeypatch):
    db = FakeSession(_document())
    monkeypatch.setattr(order_router, "apply_org_filter", lambda query, model, ctx: query)
    monkeypatch.setattr(
        order_router.blob_storage,
        "get_file",
        lambda key: (BytesIO(b"pdf"), "application/pdf", "file.pdf"),
    )

    response = asyncio.run(order_router.download_order_document(
        str(uuid4()), db=db, org_context=SimpleNamespace(), current_user=_user("View_Document")
    ))
    assert response.media_type == "application/pdf"


def test_document_list_requires_document_permission():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(order_router.list_documents(
            defect_report_id=None,
            purchase_order_id=None,
            request_id=None,
            payment_id=None,
            vendor_quote_id=None,
            db=FakeSession([]),
            org_context=SimpleNamespace(),
            current_user=_user(),
        ))
    assert exc.value.status_code == 403


def test_document_list_applies_org_scope(monkeypatch):
    scoped = []

    def apply_scope(query, model, context):
        scoped.append(model)
        return query

    monkeypatch.setattr(order_router, "apply_org_filter", apply_scope)
    result = asyncio.run(order_router.list_documents(
        defect_report_id=None,
        purchase_order_id=None,
        request_id=None,
        payment_id=None,
        vendor_quote_id=None,
        db=FakeSession([]),
        org_context=SimpleNamespace(),
        current_user=_user("View_Document"),
    ))

    assert result == []
    assert order_router.OrderDocument in scoped


def test_payment_document_list_requires_financial_clearance():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(order_router.list_documents(
            defect_report_id=None,
            purchase_order_id=None,
            request_id=None,
            payment_id=7,
            vendor_quote_id=None,
            db=FakeSession([]),
            org_context=SimpleNamespace(),
            current_user=_user("View_Document"),
        ))
    assert exc.value.status_code == 403
