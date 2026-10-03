from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Schema.SalesIntentSchema import SalesIntentInput
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision, SalesIntentLineRevision
from Services.sales_intent_service import save_sales_intent, get_sales_intent
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def intent(source):
    f = source; f.document = uuid4(); f.operation = uuid4()
    def save(**kw):
        f.db.connection()
        return save_sales_intent(f.db, f.context, f.user.id, kw.pop('key', f.operation),
            f.document, SalesIntentInput(**f.data), expected_version=kw.pop('version', 0),
            authorize=kw.pop('authorize', lambda db: None), **kw)
    f.save = save
    return f


def test_create_exact_replay_and_revision_history(intent):
    f = intent
    first = f.save(); f.db.commit()
    assert first.result['version'] == 1 and not first.replayed
    assert f.save().replayed; f.db.commit()
    f.data['lines'][0]['quantity'] = '3'
    assert f.save(key=uuid4(), version=1).result['version'] == 2; f.db.commit()
    result = get_sales_intent(f.db, f.context, f.document, authorize=lambda db: None)
    assert result['version'] == 2 and result['lines'][0]['base_quantity'] == '36.000000'
    old = f.db.query(SalesIntentLineRevision).filter_by(document_key=f.document, version=1).one()
    assert old.base_quantity == 24
    assert f.db.query(SalesIntent).filter_by(document_key=f.document).count() == 1


def test_stale_write_and_changed_retry_do_not_append(intent):
    f = intent; f.save(); f.db.commit()
    with pytest.raises(PostingConflict): f.save(key=uuid4())
    f.data['lines'][0]['quantity'] = '4'
    with pytest.raises(PostingConflict): f.save()
    assert f.db.query(SalesIntentRevision).filter_by(document_key=f.document).count() == 1


def test_outer_rollback_removes_parent_lines_and_receipt(intent):
    f = intent; f.save(); f.db.rollback()
    assert f.db.query(SalesIntent).filter_by(document_key=f.document).count() == 0
    assert not f.save().replayed


def test_permission_revocation_blocks_replay(intent):
    f = intent; f.save(); f.db.commit()
    def deny(db): raise PermissionError('Denied')
    with pytest.raises(PermissionError): f.save(authorize=deny)


def test_foreign_root_cannot_read_or_overwrite(intent):
    f = intent; f.save(); f.db.commit()
    f.context = OrgContext(current_org_id=f.org_b, allowed_org_ids=[f.org_a, f.org_b], is_root=True)
    with pytest.raises(LookupError):
        get_sales_intent(f.db, f.context, f.document, authorize=lambda db: None)
    with pytest.raises(LookupError): f.save(key=uuid4())


@pytest.mark.parametrize('table', ['sales_intents', 'sales_intent_revisions', 'sales_intent_line_revisions'])
def test_history_is_immutable(intent, table):
    f = intent; f.save(); f.db.commit()
    with pytest.raises(DBAPIError), f.db.begin_nested():
        f.db.execute(text(f'DELETE FROM containermgmt.{table} WHERE document_key=:key'), {'key': f.document})


def test_migration_replay(intent, monkeypatch, test_engine):
    import Utils.migrate_20261003_sales_intents as migration
    monkeypatch.setattr(migration, 'engine', test_engine)
    migration.ensure_sales_intents_schema(); migration.ensure_sales_intents_schema()
    assert intent.save().result['version'] == 1
