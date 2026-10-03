"""Shared transaction contracts against isolated PostgreSQL synthetic records."""
from uuid import uuid4

import pytest

from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Services.inventory_posting_service import execute_in_transaction, execute_once
from tests.test_inventory_posting import posting  # noqa: F401 - shared real-DB fixture


def run(db, f, key, **changes):
    return execute_in_transaction(db, f.context, f.actor, key, "test.reserve",
        {"quantity": "6", "counter_id": f.counter_id},
        changes.get("apply", f.apply), authorize=changes.get("authorize", lambda db: None))


def assert_untouched(f):
    with f.factory() as db:
        assert db.get(f.model, f.counter_id).label == "10"
        assert db.query(PostingOperation).filter_by(org_id=f.orgs[0]).count() == 0


def test_outer_rollback_removes_effect_receipt_and_other_work(posting):
    f = posting
    with pytest.raises(RuntimeError, match="later invoice failure"):
        with f.factory.begin() as db:
            db.add(f.model(org_id=f.orgs[0], label="synthetic invoice"))
            assert not run(db, f, uuid4()).replayed
            raise RuntimeError("later invoice failure")
    assert_untouched(f)
    with f.factory() as db:
        assert db.query(f.model).filter_by(org_id=f.orgs[0], label="synthetic invoice").count() == 0


def test_outer_commit_and_existing_wrapper_share_replay(posting):
    f = posting
    key = uuid4()
    with f.factory.begin() as db:
        assert not run(db, f, key).replayed
        assert db.in_transaction()
    assert f.run(key).replayed


def test_shared_boundary_requires_active_transaction(posting):
    f = posting
    with f.factory() as db:
        with pytest.raises(ValueError, match="active caller-owned"):
            run(db, f, uuid4())
    assert_untouched(f)


@pytest.mark.parametrize("replay", [False, True])
def test_guard_denies_before_effect_or_saved_result(posting, replay):
    f = posting
    key = uuid4()
    if replay:
        f.run(key)
    calls = []
    def denied(db):
        calls.append(True)
        raise PermissionError("authority revoked")
    with pytest.raises(PermissionError, match="revoked"):
        execute_once(f.factory, f.context, f.actor, key, "test.reserve",
            {"quantity": "6", "counter_id": f.counter_id}, f.apply, authorize=denied)
    assert calls == [True]
    if not replay:
        assert_untouched(f)


@pytest.mark.parametrize("failure", ["guard", "effect", "missing_guard"])
def test_caught_error_cannot_commit_prior_outer_work(posting, failure):
    f = posting
    def broken(db):
        if failure == "effect":
            f.apply(db)
            db.flush()
        raise ValueError("synthetic rejection")
    with f.factory() as db:
        db.begin()
        db.add(f.model(org_id=f.orgs[0], label="must roll back"))
        db.flush()
        options = {"authorize": None} if failure == "missing_guard" else {
            "authorize" if failure == "guard" else "apply": broken}
        with pytest.raises(ValueError):
            run(db, f, uuid4(), **options)
        assert not db.in_transaction()
        db.commit()  # caught failure still cannot persist the earlier work
    assert_untouched(f)
    with f.factory() as db:
        assert db.query(f.model).filter_by(org_id=f.orgs[0], label="must roll back").count() == 0
