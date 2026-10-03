from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from decimal import Decimal
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Model.containermgmt.Inventory.StockReclassification import StockReclassificationProposal
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Schema.StockReclassificationSchema import ReclassificationProposalCreate
from Services.reclassification_proposal_service import save_proposal, load_proposal_binding
from Services.manager_case_service import request_case, review_case
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def proposal(reviewed):
    f = reviewed; f.activate()
    f.balance = f.open(policy=f.policy).result["balance_id"]
    with f.factory.begin() as db:
        db.add(ProductPolicyDraft(org_id=f.orgs[0], product_id=f.products[0], version=2,
            config={**f.policy.model_dump(mode="json"), "tracking": "BATCH", "require_shade": True}, created_by=f.actor))
    f.payload = ReclassificationProposalCreate(operation_key=uuid4(), balance_id=f.balance,
        expected_balance_version=1, expected_active_version=1, expected_draft_version=2,
        reason="Synthetic stock audit", batches=[dict(identity=dict(batch_key=uuid4(), code="AUDITED", shade="A"),
            on_hand="10", damaged="1", quarantined="1")])
    f.save = lambda payload=None, factory=None, context=None, authorize=lambda db: None: save_proposal(
        factory or f.factory, context or f.context, f.actor, payload or f.payload, authorize=authorize)
    f.load_proposal = lambda db: load_proposal_binding(db, f.context, f.payload.operation_key)
    return f


def test_saved_proposal_replays_without_changing_stock_and_binds_existing_review_engine(proposal):
    f = proposal
    assert f.save().result["status"] == "SAVED" and f.save().replayed
    with f.factory.begin() as db:
        binding = f.load_proposal(db)
        balance = db.get(StockBalance, f.balance)
        assert balance.version == 1 and balance.on_hand == 10 and balance.tracking_policy == "UNTRACKED"
        assert binding.details["snapshot"]["quantities"]["damaged"] == "1.000000"
    key = uuid4()
    request_case(f.factory, f.context, f.actor, key, binding=binding,
        reason="Review manifest", load_binding=f.load_proposal, authorize=lambda db: None)
    result = review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=key, binding=binding,
        expected_version=1, outcome="APPROVED", reason="Checked", load_binding=f.load_proposal, authorize=lambda db: None)
    assert result.result["status"] == "APPROVED"


def test_quantity_change_invalidates_save_replay_and_review_source(proposal):
    f = proposal; f.save()
    f.reserve(f.balance, quantity=Decimal("1"))
    with pytest.raises(PostingConflict, match="version changed"):
        f.save()
    with f.factory.begin() as db, pytest.raises(PostingConflict, match="version changed"):
        f.load_proposal(db)


def test_changed_draft_invalidates_saved_proposal(proposal):
    f = proposal; f.save()
    with f.factory.begin() as db:
        db.add(ProductPolicyDraft(org_id=f.orgs[0], product_id=f.products[0], version=3,
            config={**f.policy.model_dump(mode="json"), "tracking": "SERIAL", "quantity_step": "1"}, created_by=f.actor))
    with pytest.raises(PostingConflict):
        f.save()


def test_rollback_and_permission_check_apply_to_retries(proposal):
    f = proposal
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.save(factory=db)
            raise RuntimeError("Synthetic downstream failure")
    assert not f.save().replayed
    def deny(db):
        raise PermissionError("Denied")
    with pytest.raises(PermissionError):
        f.save(authorize=deny)
    with pytest.raises(ValueError, match="permission guard"):
        f.save(authorize=None)


def test_foreign_active_company_cannot_save_or_load(proposal):
    f = proposal; f.save()
    foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    with pytest.raises(LookupError):
        f.save(context=foreign)
    with f.factory.begin() as db, pytest.raises(LookupError):
        load_proposal_binding(db, foreign, f.payload.operation_key)


def test_changed_intent_cannot_reuse_operation_key(proposal):
    f = proposal; f.save()
    with pytest.raises(PostingConflict):
        f.save(f.payload.model_copy(update={"reason": "Different reason"}))


def test_concurrent_retry_has_one_immutable_proposal(proposal):
    f = proposal; barrier = Barrier(2, timeout=10)
    def run(_):
        barrier.wait(); return f.save().replayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == [False, True]
    with f.factory() as db:
        assert db.query(StockReclassificationProposal).filter_by(org_id=f.orgs[0]).count() == 1


def test_database_immutability_and_migration_replay(proposal, monkeypatch, test_engine):
    f = proposal; f.save()
    from Utils import migrate_20261002_stock_reclassification as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_stock_reclassification_schema(); migration.ensure_stock_reclassification_schema()
    for statement in ("UPDATE containermgmt.inventory_stock_reclassification_proposals SET snapshot='{}' WHERE org_id=:org",
                      "DELETE FROM containermgmt.inventory_stock_reclassification_proposals WHERE org_id=:org"):
        with f.factory.begin() as db, pytest.raises(DBAPIError):
            with db.begin_nested():
                db.execute(text(statement), {"org": f.orgs[0]})


def test_review_blocks_self_approval_and_changed_stock(proposal):
    f = proposal; f.save()
    with f.factory.begin() as db:
        binding = f.load_proposal(db)
    case = uuid4()
    request_case(f.factory, f.context, f.actor, case, binding=binding,
        reason="Check source", load_binding=f.load_proposal, authorize=lambda db: None)
    def review(actor):
        return review_case(f.factory, f.context, actor, uuid4(), case_key=case, binding=binding,
            expected_version=1, outcome="APPROVED", reason="Checked",
            load_binding=f.load_proposal, authorize=lambda db: None)
    with pytest.raises(PermissionError, match="own case"):
        review(f.actor)
    f.reserve(f.balance, quantity=Decimal("1"))
    with pytest.raises(PostingConflict, match="version changed"):
        review(f.reviewer)


def test_current_version_with_reserved_stock_still_cannot_save(proposal):
    f = proposal
    f.reserve(f.balance, quantity=Decimal("1"))
    with pytest.raises(ValueError, match="Reserved stock"):
        f.save(f.payload.model_copy(update={"expected_balance_version": 2}))
    with f.factory() as db:
        assert db.query(StockReclassificationProposal).filter_by(org_id=f.orgs[0]).count() == 0
