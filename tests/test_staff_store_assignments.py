from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.Credentials.users import User
from Model.containermgmt.Inventory.StaffStoreAssignment import StaffStoreAssignment
from Schema.StaffStoreAssignmentSchema import StaffStoreConfig
from Services.staff_store_assignment_service import save_staff_store_assignment, require_staff_store_assignment, eligible_staff
from Services.inventory_posting_service import PostingConflict
from tests.test_stock_ledger import stock  # noqa: F401


def save(f, **kw):
    return save_staff_store_assignment(kw.pop('factory', f.factory), f.context, f.actor, kw.pop('key', uuid4()),
        user_id=kw.pop('user_id', f.actor), config=kw.pop('config', StaffStoreConfig(branch_id=f.branches[0], is_enabled=True)),
        expected_version=kw.pop('version', 0), authorize=kw.pop('authorize', lambda db: None))


def test_immutable_history_retry_and_revocation(stock):
    f = stock; key = uuid4()
    assert not save(f, key=key).replayed and save(f, key=key).replayed
    with f.factory.begin() as db:
        assert require_staff_store_assignment(db, f.context, f.actor, branch_id=f.branches[0], expected_version=1).counter_id is None
    save(f, version=1, config=StaffStoreConfig(branch_id=f.branches[0], is_enabled=False))
    with pytest.raises(PermissionError), f.factory.begin() as db:
        require_staff_store_assignment(db, f.context, f.actor, branch_id=f.branches[0], expected_version=1)
    with pytest.raises(DBAPIError), f.factory.begin() as db:
        db.execute(text('DELETE FROM containermgmt.inventory_staff_store_assignments WHERE org_id=:org'), {'org': f.orgs[0]})
    with pytest.raises(PostingConflict): save(f, version=0)


def test_foreign_staff_and_revoked_membership_fail(stock):
    f = stock
    with f.factory.begin() as db:
        foreign = User(username='foreign-'+uuid4().hex, org_id=f.orgs[1], password_hash='synthetic')
        db.add(foreign); db.flush(); foreign_id = foreign.id
    with pytest.raises(LookupError): save(f, user_id=foreign_id)
    key = uuid4(); save(f, key=key)
    with f.factory.begin() as db: db.get(User, f.actor).allowed_org_ids = []
    with pytest.raises(LookupError): save(f, key=key)
    with f.factory() as db: assert eligible_staff(db, f.context).count() == 0


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_assignment_changes(stock, same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = stock; key = uuid4(); barrier = Barrier(2)
    def run(operation):
        barrier.wait(timeout=10)
        try: return save(f, key=operation).replayed
        except PostingConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [key, key if same_key else uuid4()]))
    assert results.count(False) == 1 and results.count(True if same_key else 'conflict') == 1


def test_migration_replay_and_caller_rollback(stock, monkeypatch, test_engine):
    import Utils.migrate_20261003_staff_store_assignments as migration
    f = stock; monkeypatch.setattr(migration, 'engine', test_engine)
    migration.ensure_staff_store_assignments_schema(); migration.ensure_staff_store_assignments_schema()
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            save(f, factory=db)
            raise RuntimeError('Synthetic rollback')
    with f.factory() as db: assert db.query(StaffStoreAssignment).filter_by(org_id=f.orgs[0]).count() == 0


def test_counter_must_match_store_and_assignment_lock_blocks_change(stock):
    from Model.containermgmt.Inventory.Location import InventoryBranch
    from Model.containermgmt.Inventory.BranchCounter import BranchCounter
    f = stock
    with f.factory.begin() as db:
        other = InventoryBranch(org_id=f.orgs[0], code='SECOND', name='Synthetic', kind='STORE')
        db.add(other); db.flush()
        counter = BranchCounter(org_id=f.orgs[0], branch_id=other.id, code='OTHER', counter_key=uuid4(), created_by=f.actor)
        db.add(counter); db.flush(); counter_id = counter.id
    with pytest.raises(LookupError, match='counter'):
        save(f, config=StaffStoreConfig(branch_id=f.branches[0], counter_id=counter_id, is_enabled=True))
    save(f)
    with f.factory.begin() as reader:
        require_staff_store_assignment(reader, f.context, f.actor, branch_id=f.branches[0], expected_version=1)
        with pytest.raises(DBAPIError), f.factory.begin() as writer:
            writer.execute(text("SET LOCAL lock_timeout='150ms'"))
            writer.query(User.id).filter(User.id == f.actor).with_for_update().one()
