"""Real PostgreSQL gates; test-owned records only, no schema resets or business deletes."""
import asyncio
import importlib
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

import Model  # Register all model foreign keys before metadata creation.
from Model.db import Base
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt, ReceiptItem
from Model.containermgmt.Orders.Notification import Notification
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Schema.ReceivingSchema import ReceiptCreate
from Utils.org_filter import OrgContext

router = importlib.import_module("Routes.Orders.ReceivingRouter")


@pytest.fixture
def receipt_database(test_engine):
    with test_engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS usercredentials"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS containermgmt"))
        Base.metadata.create_all(conn)
    key = uuid4().hex
    with Session(test_engine) as db:
        org = Organisation(name=f"Receiving test {key}")
        db.add(org)
        db.flush()
        user = User(username=f"receiving-{key}", password_hash="test-only-unusable", org_id=org.id)
        db.add(user)
        db.flush()
        po = PurchaseOrder(po_number=f"TEST-{key}", org_id=org.id)
        db.add(po)
        db.flush()
        item = POItem(po_id=po.id, org_id=org.id, description="Test goods", quantity_ordered=10, unit="PCS")
        db.add(item)
        db.commit()
        yield SimpleNamespace(engine=test_engine, po_id=po.id, item_id=item.id,
            user=SimpleNamespace(id=user.id), context=OrgContext(current_org_id=org.id,
                allowed_org_ids=[org.id], is_root=False))


def create_draft(fixture, number=None):
    payload = ReceiptCreate(po_id=fixture.po_id, receipt_number=number or f"TEST-{uuid4().hex}",
        items=[{"po_item_id": fixture.item_id, "description": "Test", "received_quantity": "2.25"}])
    with Session(fixture.engine) as db:
        return asyncio.run(router.create_receipt(payload, db, fixture.context, fixture.user))


def submit(fixture, receipt_id):
    with Session(fixture.engine) as db:
        return asyncio.run(router.submit_receipt(receipt_id, db, fixture.context, fixture.user))


def test_postgres_draft_and_repeat_submit(receipt_database):
    f = receipt_database
    receipt = create_draft(f)
    with Session(f.engine) as db:
        assert db.get(POItem, f.item_id).quantity_received == Decimal("0")
    first = submit(f, receipt["id"])
    second = submit(f, receipt["id"])
    assert first["submitted_at"] == second["submitted_at"]
    with Session(f.engine) as db:
        assert db.get(POItem, f.item_id).quantity_received == Decimal("2.25")
        assert db.get(PurchaseOrder, f.po_id).receipt_status == "PARTIAL"
        assert db.query(Notification).filter(Notification.link_entity_id == receipt["id"], Notification.org_id == f.context.org_id).count() == 1


@pytest.mark.parametrize("same_receipt", [True, False])
def test_postgres_concurrent_submission(receipt_database, monkeypatch, same_receipt):
    f = receipt_database
    first = create_draft(f)["id"]
    second = first if same_receipt else create_draft(f)["id"]
    barrier = Barrier(2, timeout=10)
    original = router.lock_order

    def simultaneous_lock(*args):
        barrier.wait()
        return original(*args)

    monkeypatch.setattr(router, "lock_order", simultaneous_lock)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda receipt_id: submit(f, receipt_id), [first, second]))
    assert all(response["status"] == "SUBMITTED" for response in responses)
    with Session(f.engine) as db:
        assert db.get(POItem, f.item_id).quantity_received == Decimal("2.25" if same_receipt else "4.50")
        assert db.query(Notification).filter(Notification.org_id == f.context.org_id).count() == (1 if same_receipt else 2)


def test_postgres_failure_rolls_back_all_posting_effects(receipt_database, monkeypatch):
    f = receipt_database
    receipt = create_draft(f)
    original = router.post_receipt

    def fail_after_changes(*args):
        original(*args)
        args[0].flush()
        raise RuntimeError("Injected failure before commit")

    monkeypatch.setattr(router, "post_receipt", fail_after_changes)
    with pytest.raises(RuntimeError, match="Injected"):
        submit(f, receipt["id"])
    with Session(f.engine) as db:
        assert db.get(POItem, f.item_id).quantity_received == 0
        assert db.get(GoodsReceipt, receipt["id"]).status == "DRAFT"
        assert db.query(Notification).filter(Notification.org_id == f.context.org_id).count() == 0


def test_postgres_duplicate_number_rolls_back(receipt_database):
    f = receipt_database
    number = f"TEST-{uuid4().hex}"
    create_draft(f, number)
    with pytest.raises(HTTPException) as exc:
        create_draft(f, number)
    assert exc.value.status_code == 409
    with Session(f.engine) as db:
        assert db.query(GoodsReceipt).filter(GoodsReceipt.po_id == f.po_id).count() == 1
        assert db.get(POItem, f.item_id).quantity_received == 0


def test_postgres_legacy_draft_requires_review(receipt_database):
    f = receipt_database
    receipt = create_draft(f)
    with Session(f.engine) as db:
        db.get(GoodsReceipt, receipt["id"]).posting_version = 0
        db.get(POItem, f.item_id).quantity_received = Decimal("2.25")
        db.commit()
    with pytest.raises(HTTPException) as exc:
        submit(f, receipt["id"])
    assert exc.value.status_code == 409
    with Session(f.engine) as db:
        assert db.get(POItem, f.item_id).quantity_received == Decimal("2.25")


@pytest.mark.parametrize("status", ["VERIFIED", "DISCREPANCY", "CANCELLED"])
def test_postgres_invalid_transition_changes_nothing(receipt_database, status):
    f = receipt_database
    receipt = create_draft(f)
    with Session(f.engine) as db:
        db.get(GoodsReceipt, receipt["id"]).status = status
        db.commit()
    with pytest.raises(HTTPException) as exc:
        submit(f, receipt["id"])
    assert exc.value.status_code == 409
    with Session(f.engine) as db:
        assert db.get(POItem, f.item_id).quantity_received == 0
        assert db.get(GoodsReceipt, receipt["id"]).status == status


def test_postgres_complete_receipt_updates_order(receipt_database):
    f = receipt_database
    receipt = create_draft(f)
    with Session(f.engine) as db:
        if not db.query(OrderStatus).filter(OrderStatus.code == "RECEIVED").first():
            db.add(OrderStatus(name="Received", code="RECEIVED"))
        db.get(POItem, f.item_id).quantity_ordered = Decimal("2.25")
        db.commit()
    submit(f, receipt["id"])
    with Session(f.engine) as db:
        assert db.get(PurchaseOrder, f.po_id).receipt_status == "RECEIVED"
        assert db.get(PurchaseOrder, f.po_id).status == "RECEIVED"
