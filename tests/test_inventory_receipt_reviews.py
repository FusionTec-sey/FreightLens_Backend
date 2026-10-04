from uuid import uuid4
import pytest
from Model.Credentials.users import User
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Services.inventory_receipt_review_service import request_receipt_review, review_receipt_manifest
from Services.inventory_receipt_manifest_store import save_receipt_manifest
from Services.inventory_posting_service import PostingConflict
from tests.test_inventory_receipt_manifest import manifest
from tests.test_inventory_receipt_source import receipt  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def review(receipt):
    f = receipt
    f.reviewer = User(org_id=f.org_a, username='rr-' + uuid4().hex, password_hash='unusable-test-only')
    f.db.add(f.reviewer); f.db.flush()
    f.manifest_key, f.case_key = uuid4(), uuid4()
    save_receipt_manifest(f.db, f.context, f.user.id, f.manifest_key, manifest(f), authorize=lambda db: None)
    f.db.commit()
    return f


def request(f, actor=None):
    f.db.connection()
    return request_receipt_review(f.db, f.context, actor or f.user.id, f.case_key,
        manifest_key=f.manifest_key, reason='Synthetic classification review', authorize=lambda db: None)


def decide(f, actor=None, operation=None, **changes):
    f.db.connection()
    args = dict(manifest_key=f.manifest_key, case_key=f.case_key, expected_version=1,
        outcome='APPROVED', reason='Inspected', authorize=lambda db: None) | changes
    return review_receipt_manifest(f.db, f.context, actor or f.reviewer.id, operation or uuid4(), **args)


def test_receipt_review_is_independent_retryable_and_not_stock_consumption(review):
    f = review
    assert request(f).result['status'] == 'REQUESTED'
    assert request(f).replayed
    f.db.commit()
    with pytest.raises(PermissionError): decide(f, actor=f.user.id)
    operation = uuid4()
    assert decide(f, operation=operation).result['status'] == 'APPROVED'
    assert decide(f, operation=operation).replayed
    assert f.db.query(ManagerCaseUse).filter_by(org_id=f.org_a).count() == 1  # policy activation only
    assert f.product.current_stock == 0


def test_proxy_request_does_not_allow_creator_review(review):
    f = review
    request(f, actor=f.reviewer.id); f.db.commit()
    with pytest.raises(PermissionError, match='creators'):
        decide(f, actor=f.user.id)
    with pytest.raises(PermissionError): decide(f)


def test_changed_source_and_foreign_scope_block_review(review):
    f = review; request(f); f.db.commit()
    f.receipt_line.condition_ok = False; f.db.commit()
    with pytest.raises(PostingConflict): decide(f)
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]; f.context.is_root = True
    with pytest.raises(LookupError): decide(f)
