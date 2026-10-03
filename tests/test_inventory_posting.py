"""Real transactions/connections in the dedicated *_test database; no live data."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text, create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

import Model
from Model.db import Base
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Utils.org_filter import OrgContext


@pytest.fixture
def posting(test_engine, tenant_record_model):
    with test_engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS usercredentials"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS containermgmt"))
        Base.metadata.create_all(connection)
    key = uuid4().hex
    with Session(test_engine) as db:
        orgs = [Organisation(name="Posting " + key + str(i)) for i in range(2)]
        db.add_all(orgs); db.flush()
        users = [User(username="post-" + key + str(i), password_hash="test-only", org_id=o.id)
                 for i, o in enumerate(orgs)]
        db.add_all(users); db.flush()
        counter = tenant_record_model(org_id=orgs[0].id, label="10")
        db.add(counter); db.commit()
        org_ids, actor_ids, counter_id = [o.id for o in orgs], [u.id for u in users], counter.id
    contexts = [OrgContext(current_org_id=o, allowed_org_ids=[o], is_root=False) for o in org_ids]
    fixture = SimpleNamespace(factory=sessionmaker(test_engine), context=contexts[0], contexts=contexts,
        actor=actor_ids[0], actors=actor_ids, orgs=org_ids, counter_id=counter_id, model=tenant_record_model)

    def apply(db):
        row = db.query(tenant_record_model).filter_by(id=counter_id, org_id=org_ids[0]).with_for_update().one()
        available = int(row.label)
        if available < 6:
            raise ValueError("Insufficient synthetic balance")
        row.label = str(available - 6)
        return PostingEffect({"remaining": row.label}, {"kind": "test.reserved", "quantity": "6"})
    fixture.apply = apply
    fixture.run = lambda key, **kw: execute_once(fixture.factory, kw.pop("context", fixture.context),
        kw.pop("actor", fixture.actor), key, kw.pop("kind", "test.reserve"),
        kw.pop("request", {"quantity": "6", "counter_id": counter_id}), kw.pop("apply", apply))
    return fixture


def test_commit_and_retry_after_lost_response_use_same_result(posting, test_database_url):
    f = posting
    key = uuid4()
    first = f.run(key)
    # A brand-new engine/connection proves replay does not depend on Python memory.
    another = create_engine(test_database_url)
    try:
        def must_not_run(db):
            raise AssertionError("A committed operation must not execute again")
        second = execute_once(sessionmaker(another), f.context, f.actor, key, "test.reserve",
            {"counter_id": f.counter_id, "quantity": "6"}, must_not_run)
    finally:
        another.dispose()
    assert not first.replayed and second.replayed and first.result == second.result == {"remaining": "4"}
    with f.factory() as db:
        rows = db.query(PostingOperation).filter_by(org_id=f.orgs[0]).all()
        assert len(rows) == 1 and rows[0].event_payload["quantity"] == "6"
        assert db.get(f.model, f.counter_id).label == "4"


@pytest.mark.parametrize("change", ["request", "kind", "actor"])
def test_changed_intent_rejected(posting, change):
    f = posting
    key = uuid4(); f.run(key)
    changes = {"request": {"quantity": "5"}, "kind": "test.release", "actor": f.actors[1]}
    with pytest.raises(PostingConflict):
        f.run(key, **{change: changes[change]})


@pytest.mark.parametrize("failure", ["callback", "serialization", "database"])
def test_failure_rolls_back_effect_and_receipt(posting, failure):
    f = posting
    key = uuid4()
    def broken(db):
        result = f.apply(db)
        db.flush()
        if failure == "callback":
            raise RuntimeError("interrupted")
        if failure == "database":
            db.execute(text("SELECT 1 / 0"))
        return PostingEffect({"invalid_float": 1.5}, result.event)
    with pytest.raises((RuntimeError, ValueError, DBAPIError)):
        f.run(key, apply=broken)
    with f.factory() as db:
        assert db.get(f.model, f.counter_id).label == "10"
        assert db.query(PostingOperation).filter_by(org_id=f.orgs[0]).count() == 0
    assert f.run(key).result == {"remaining": "4"}


def test_keys_are_tenant_scoped_and_context_is_required(posting):
    f = posting
    key = uuid4(); f.run(key)
    other = f.run(key, context=f.contexts[1], actor=f.actors[1], apply=lambda db: PostingEffect({"other": True}, {}))
    assert not other.replayed and other.result == {"other": True}
    invalid = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=[f.orgs[0]], is_root=True)
    with pytest.raises(PermissionError):
        f.run(key, context=invalid)


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_operations_and_locked_balance(posting, same_key):
    f = posting
    first = uuid4()
    keys = [first, first if same_key else uuid4()]
    barrier = Barrier(2, timeout=10)
    def run(key):
        barrier.wait()
        try:
            return f.run(key)
        except ValueError:
            return "insufficient"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, keys))
    if same_key:
        assert sorted(r.replayed for r in results) == [False, True]
    else:
        assert results.count("insufficient") == 1
    with f.factory() as db:
        assert db.get(f.model, f.counter_id).label == "4"
        assert db.query(PostingOperation).filter_by(org_id=f.orgs[0]).count() == 1


@pytest.mark.parametrize("sql", ["UPDATE containermgmt.inventory_posting_operations SET kind = 'changed' WHERE org_id = :org",
    "UPDATE containermgmt.inventory_posting_operations SET is_deleted = true WHERE org_id = :org",
    "DELETE FROM containermgmt.inventory_posting_operations WHERE org_id = :org"])
def test_database_receipts_are_append_only(posting, sql):
    f = posting
    key = uuid4(); f.run(key)
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            db.execute(text(sql), {"org": f.orgs[0]})
    assert f.run(key).replayed


@pytest.mark.parametrize("payload", [{"quantity": 1.1}, {"x": float("nan")}, {1: "invalid"}, {"x": object()}, []])
def test_invalid_request_never_invokes_effect(posting, payload):
    def must_not_run(db):
        raise AssertionError("Invalid input executed callback")
    with pytest.raises(ValueError):
        posting.run(uuid4(), request=payload, apply=must_not_run)


def test_migration_replay_retains_operations(posting, test_engine, monkeypatch):
    import Utils.migrate_20261002_inventory_posting as migration
    key = uuid4(); posting.run(key)
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_inventory_posting_schema()
    migration.ensure_inventory_posting_schema()
    assert posting.run(key).replayed
