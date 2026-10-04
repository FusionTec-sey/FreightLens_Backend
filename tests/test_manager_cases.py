from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.Credentials.users import User
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseDecision, ManagerCaseUse
from Services.manager_case_service import CaseBinding, request_case, review_case, consume_case
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from tests.test_inventory_posting import posting  # noqa: F401


@pytest.fixture
def cases(posting):
    f = posting
    with f.factory.begin() as db:
        reviewer = User(username="reviewer-" + uuid4().hex, password_hash="test-only", org_id=f.orgs[0])
        db.add(reviewer); db.flush(); f.reviewer = reviewer.id
    f.binding = CaseBinding(f.orgs[0], "inventory.policy.activate", "synthetic.policy", str(f.counter_id), 10,
                            {"quantity": "2.000000", "scope": "synthetic"})
    def load(db):
        row = db.query(f.model).filter_by(id=f.counter_id, org_id=f.orgs[0]).populate_existing().with_for_update().one()
        return replace(f.binding, source_version=int(row.label))
    f.load = load
    f.request = lambda key=None: request_case(f.factory, f.context, f.actor, key or uuid4(), binding=f.binding,
        reason="Synthetic reviewed action request", load_binding=f.load, authorize=lambda db: None)
    f.review = lambda case, key=None, **kw: review_case(f.factory, f.context, kw.pop("actor", f.reviewer), key or uuid4(),
        case_key=case, binding=kw.pop("binding", f.binding), expected_version=kw.pop("expected_version", 1),
        outcome=kw.pop("outcome", "APPROVED"), reason="Synthetic manager decision", load_binding=f.load,
        authorize=kw.pop("authorize", lambda db: None), **kw)
    def use(case, key=None, fail=False):
        operation_key = key or uuid4()
        def apply(db):
            consume_case(db, f.context, f.actor, operation_key, case_key=case, binding=f.binding,
                         load_binding=f.load, authorize=lambda db: None)
            if fail:
                raise RuntimeError("Synthetic posting failed")
            return PostingEffect({"used": str(case)}, {"kind": "synthetic.approved-action"})
        return execute_once(f.factory, f.context, f.actor, operation_key, "synthetic.approved-action",
                            {"case": str(case)}, apply, authorize=lambda db: f.load(db))
    f.use = use
    return f


def test_request_review_and_atomic_use_have_stable_retries(cases):
    f = cases
    case, decision, use = uuid4(), uuid4(), uuid4()
    f.request(case); assert f.request(case).replayed
    f.review(case, decision); assert f.review(case, decision).replayed
    f.use(case, use); assert f.use(case, use).replayed
    with f.factory() as db:
        assert db.query(ManagerCase).filter_by(org_id=f.orgs[0]).count() == 1
        assert db.query(ManagerCaseDecision).filter_by(org_id=f.orgs[0]).count() == 1
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0]).count() == 1


def test_self_approval_denied_in_service_and_database(cases):
    f = cases; case = uuid4(); f.request(case)
    with pytest.raises(PermissionError):
        f.review(case, actor=f.actor)
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            row = db.query(ManagerCase).filter_by(org_id=f.orgs[0], case_key=case).one()
            db.add(ManagerCaseDecision(org_id=f.orgs[0], case_id=row.id, created_by=f.actor,
                                      outcome="APPROVED", reason="Invalid self approval"))


@pytest.mark.parametrize("stage", ["request", "review", "use"])
def test_material_source_change_invalidates_case_including_retry(cases, stage):
    f = cases; case, decision = uuid4(), uuid4(); f.request(case)
    if stage != "request":
        f.review(case, decision)
    with f.factory.begin() as db:
        db.get(f.model, f.counter_id).label = "11"
    with pytest.raises(PostingConflict):
        if stage == "request": f.request(case)
        elif stage == "review": f.review(case, decision)
        else: f.use(case)


@pytest.mark.parametrize("field,value", [("action", "inventory.other"), ("source_key", "other"),
    ("source_version", 11), ("details", {"quantity": "3.000000"})])
def test_approval_cannot_be_rebound_to_another_action_or_scope(cases, field, value):
    f = cases; case = uuid4(); f.request(case)
    with pytest.raises(PostingConflict):
        f.review(case, binding=replace(f.binding, **{field: value}))


@pytest.mark.parametrize("outcome", [None, "REJECTED"])
def test_unapproved_cases_cannot_be_used(cases, outcome):
    f = cases; case = uuid4(); f.request(case)
    if outcome: f.review(case, outcome=outcome)
    with pytest.raises(PermissionError): f.use(case)


def test_failed_posting_does_not_consume_approval(cases):
    f = cases; case = uuid4(); f.request(case); f.review(case)
    with pytest.raises(RuntimeError): f.use(case, fail=True)
    assert not f.use(case).replayed
    with pytest.raises(PostingConflict): f.use(case)


@pytest.mark.parametrize("outcome", [None, "REJECTED"])
def test_database_rejects_consumption_without_approval(cases, outcome, test_engine, monkeypatch):
    import Utils.migrate_20261002_manager_cases as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_manager_cases_schema()
    f = cases; case = uuid4(); f.request(case)
    if outcome: f.review(case, outcome=outcome)
    with pytest.raises(DBAPIError, match="Only an approved manager case"):
        with f.factory.begin() as db:
            row = db.query(ManagerCase).filter_by(org_id=f.orgs[0], case_key=case).one()
            db.add(ManagerCaseUse(org_id=f.orgs[0], case_id=row.id, operation_key=uuid4(), created_by=f.actor))
            db.flush()


def test_simultaneous_uses_have_one_business_effect(cases):
    f = cases; case = uuid4(); f.request(case); f.review(case)
    barrier = Barrier(2, timeout=10)
    def run(_):
        barrier.wait()
        try: f.use(case); return "used"
        except PostingConflict: return "denied"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == ["denied", "used"]


def test_permission_revocation_blocks_review_retry(cases):
    f = cases; case, decision = uuid4(), uuid4(); f.request(case); f.review(case, decision)
    def deny(db): raise PermissionError("Revoked")
    with pytest.raises(PermissionError): f.review(case, decision, authorize=deny)


def test_other_organisation_is_denied(cases):
    f = cases; key = uuid4()
    with pytest.raises(PermissionError):
        request_case(f.factory, f.contexts[1], f.actors[1], key, binding=f.binding,
                     reason="Foreign", load_binding=f.load, authorize=lambda db: None)


def test_case_history_immutable_and_migration_replay(cases, test_engine, monkeypatch):
    import Utils.migrate_20261002_manager_cases as migration
    f = cases; key = uuid4(); f.request(key); f.review(key); f.use(key)
    for table in ("manager_cases", "manager_case_decisions", "manager_case_uses"):
        with pytest.raises(DBAPIError):
            with f.factory.begin() as db:
                db.execute(text(f"DELETE FROM containermgmt.{table} WHERE org_id=:org"), {"org": f.orgs[0]})
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_manager_cases_schema(); migration.ensure_manager_cases_schema()
    with f.factory() as db:
        assert db.execute(text("SELECT to_regclass('containermgmt.ix_manager_cases_scope_source')")).scalar()
    assert f.request(key).replayed
