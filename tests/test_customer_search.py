from unittest.mock import Mock
from uuid import uuid4
import pytest
from Services import search_service as service


def test_search_scope_and_bounded_page(monkeypatch):
    key = uuid4()
    index = Mock()
    index.search.return_value = {'hits': [{'id': str(key), 'org_id': 7}], 'totalHits': 1}
    client = Mock()
    client.index.return_value = index
    monkeypatch.setattr(service, 'get_meili_client', lambda: client)
    assert service.search_customers('Synthetic', 7, 2, 10) == ([key], 1)
    assert index.search.call_args.args[1]['filter'] == 'org_id = 7 AND is_deleted = false'
    assert index.search.call_args.args[1]['hitsPerPage'] == 10
    index.search.return_value['hits'][0]['org_id'] = 8
    with pytest.raises(service.CustomerSearchUnavailable): service.search_customers('Synthetic', 7, 2, 10)


def test_unavailable_sync_does_not_throw_or_log_contacts(monkeypatch, caplog):
    monkeypatch.setattr(service, 'get_meili_client', lambda: None)
    assert not service.sync_customer_document(uuid4(), 7, {'name': 'Private', 'contacts': []})
    with pytest.raises(service.CustomerSearchUnavailable): service.search_customers('Private', 7, 1, 25)
    assert 'Private' not in caplog.text


def test_sync_projection_excludes_extra_profile_fields(monkeypatch):
    from types import SimpleNamespace
    client = Mock()
    client.index.return_value.add_documents.return_value = SimpleNamespace(task_uid=1)
    client.wait_for_task.return_value = SimpleNamespace(uid=1, index_uid='retail_customers', status='succeeded')
    monkeypatch.setattr(service, 'get_meili_client', lambda: client)
    assert service.sync_customer_document(uuid4(), 7, {'name': 'Synthetic', 'contacts': [{'value': '12345', 'label': 'Private label'}], 'credit': 999})
    doc = client.index.return_value.add_documents.call_args.args[0][0]
    assert set(doc) == {'id', 'org_id', 'is_deleted', 'name', 'contacts'}
    assert doc['contacts'] == ['12345']


@pytest.mark.parametrize('status', ['failed', 'canceled', 'enqueued', 'processing'])
def test_accepted_task_is_not_indexing_success(monkeypatch, status):
    from types import SimpleNamespace
    client = Mock()
    client.index.return_value.add_documents.return_value = SimpleNamespace(task_uid=2)
    client.wait_for_task.return_value = SimpleNamespace(uid=2, index_uid='retail_customers', status=status)
    monkeypatch.setattr(service, 'get_meili_client', lambda: client)
    assert not service.sync_customer_document(uuid4(), 7, {'name': 'Private', 'contacts': []})


def test_task_timeout_preserves_failure_privacy(monkeypatch, caplog):
    from types import SimpleNamespace
    client = Mock()
    client.index.return_value.add_documents.return_value = SimpleNamespace(task_uid=2)
    client.wait_for_task.side_effect = RuntimeError('Private provider details')
    monkeypatch.setattr(service, 'get_meili_client', lambda: client)
    assert not service.sync_customer_document(uuid4(), 7, {'name': 'Private', 'contacts': []})
    assert 'Private' not in caplog.text


def test_wrong_index_task_and_missing_identity_fail_closed():
    from types import SimpleNamespace
    client = Mock()
    assert not service._customer_task_succeeded(client, SimpleNamespace(task_uid=None))
    client.wait_for_task.assert_not_called()
    client.wait_for_task.return_value = SimpleNamespace(uid=2, index_uid='products', status='succeeded')
    assert not service._customer_task_succeeded(client, SimpleNamespace(task_uid=2))
