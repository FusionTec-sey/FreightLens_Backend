"""Personal case notifications must not be visible or writable by colleagues."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from Model.containermgmt.Orders.Notification import Notification
from Routes.Orders.NotificationRouter import list_notifications, mark_all_read, mark_read
from Utils.org_filter import OrgContext
from auth.module_guard import require_any_module


def test_shared_notification_guard_allows_inventory_without_orders():
    check = require_any_module("ORDERS", "INVENTORY", "LOGISTICS", "SALES")
    assert asyncio.run(check(policy=SimpleNamespace(is_platform_admin=False,
                           module_names=frozenset({"INVENTORY"})))) is True
    with pytest.raises(HTTPException) as denied:
        asyncio.run(check(policy=SimpleNamespace(is_platform_admin=False,
                          module_names=frozenset())))
    assert denied.value.status_code == 403


def test_notification_list_and_acknowledgements_are_recipient_scoped():
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    try:
        with engine.begin() as connection:
            connection.execute(text("ATTACH DATABASE ':memory:' AS containermgmt"))
            connection.execute(text("""CREATE TABLE containermgmt.notifications (
                id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, user_id INTEGER,
                event_type TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL,
                link_entity_type TEXT, link_entity_id INTEGER, is_read BOOLEAN NOT NULL,
                created_at DATETIME)"""))
        with Session(engine) as db:
            db.add_all([
                Notification(org_id=1, user_id=10, event_type="CASE_REVIEW_REQUESTED",
                             title="Mine", message="Mine", is_read=False),
                Notification(org_id=1, user_id=11, event_type="CASE_REVIEW_REQUESTED",
                             title="Colleague", message="Colleague", is_read=False),
                Notification(org_id=2, user_id=12, event_type="CASE_REVIEW_REQUESTED",
                             title="Other company", message="Other company", is_read=False),
            ])
            db.commit()
        context = OrgContext(current_org_id=1, allowed_org_ids=[1], is_root=False)
        user = SimpleNamespace(id=10)
        with Session(engine) as db:
            result = asyncio.run(list_notifications(unread_only=False, page=1, limit=20,
                              db=db, org_context=context, current_user=user))
            assert result["unread_count"] == 1
            assert (result["total"], result["pages"]) == (1, 1)
            assert [item["title"] for item in result["notifications"]] == ["Mine"]

            for foreign_id in (2, 3):
                with pytest.raises(HTTPException) as denied:
                    asyncio.run(mark_read(foreign_id, db=db, org_context=context,
                                          current_user=user))
                assert denied.value.status_code == 404

            asyncio.run(mark_all_read(db=db, org_context=context, current_user=user))

        with Session(engine) as db:
            assert [db.get(Notification, key).is_read for key in (1, 2, 3)] == [True, False, False]
    finally:
        engine.dispose()
