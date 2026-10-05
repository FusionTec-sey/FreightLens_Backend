"""T15 safe-copy provenance over the existing authoritative draft save path."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Orders.SalesIntent import SalesIntentLineRevision
from Model.containermgmt.Orders.SalesIntentCopyOrigin import SalesIntentCopyOrigin
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def copy_api(api, monkeypatch, test_engine):
    import Utils.migrate_20261005_sales_intent_copy_origins as migration

    api.db.rollback()
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_sales_intent_copy_origins_schema()
    migration.ensure_sales_intent_copy_origins_schema()
    api.db.expire_all()
    return api


def _copy_payload(source, *, operation_key=None, line_key=None, version=1):
    payload = deepcopy(source.payload)
    payload["operation_key"] = str(operation_key or uuid4())
    payload["expected_version"] = 0
    payload["draft"]["lines"][0]["line_key"] = str(line_key or uuid4())
    payload["source_reference"] = {
        "document_key": source.url.rsplit("/", 1)[-1],
        "version": version,
    }
    return payload


def test_copy_persists_exact_origin_and_replays_once(copy_api):
    f = copy_api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    destination = uuid4()
    payload = _copy_payload(f)

    created = f.client.put(f"/sales/drafts/{destination}", json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["version"] == 1 and not created.json()["replayed"]
    replay = f.client.put(f"/sales/drafts/{destination}", json=payload)
    assert replay.status_code == 200 and replay.json()["replayed"]

    detail = f.client.get(f"/sales/drafts/{destination}")
    assert detail.status_code == 200
    assert detail.json()["source_reference"] == {
        "document_key": f.url.rsplit("/", 1)[-1],
        "version": 1,
    }
    historical = f.client.get(f"/sales/drafts/{destination}/history/1").json()
    assert historical["source_reference"] == detail.json()["source_reference"]
    origin = f.db.query(SalesIntentCopyOrigin).filter_by(
        destination_document_key=destination
    ).one()
    assert origin.operation_key == UUID(payload["operation_key"])
    operation = f.db.query(PostingOperation).filter_by(
        operation_key=origin.operation_key
    ).one()
    assert operation.kind == "sales.intent.copy.v1"
    assert operation.event_payload["source_reference"] == payload["source_reference"]


def test_ordinary_save_retains_pre_t15_operation_fingerprint(copy_api):
    f = copy_api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    request = {
        "document_key": f.url.rsplit("/", 1)[-1],
        "expected_version": 0,
        "draft": f.payload["draft"],
    }
    encoded = json.dumps(
        {"kind": "sales.intent.save.v1", "request": request},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )
    operation = f.db.query(PostingOperation).filter_by(
        operation_key=UUID(f.payload["operation_key"])
    ).one()
    assert operation.request_digest == sha256(encoded.encode("utf-8")).hexdigest()


def test_copy_revalidates_current_sources_and_uses_new_line_identity(copy_api):
    f = copy_api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    source_line = f.payload["draft"]["lines"][0]["line_key"]

    reused = _copy_payload(f, line_key=UUID(source_line))
    response = f.client.put(f"/sales/drafts/{uuid4()}", json=reused)
    assert response.status_code == 409
    assert "new identities" in response.json()["detail"]

    missing = _copy_payload(f)
    missing["source_reference"]["document_key"] = str(uuid4())
    response = f.client.put(f"/sales/drafts/{uuid4()}", json=missing)
    assert response.status_code == 404

    same_key = _copy_payload(f)
    same_key["source_reference"]["document_key"] = f.url.rsplit("/", 1)[-1]
    response = f.client.put(f.url, json=same_key)
    assert response.status_code == 422


def test_copy_reference_is_initial_only_and_changed_retry_conflicts(copy_api):
    f = copy_api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    destination = uuid4()
    payload = _copy_payload(f)
    assert f.client.put(f"/sales/drafts/{destination}", json=payload).status_code == 200

    changed_retry = deepcopy(payload)
    changed_retry["source_reference"]["version"] = 2
    assert f.client.put(
        f"/sales/drafts/{destination}", json=changed_retry
    ).status_code == 409

    later = deepcopy(payload)
    later["operation_key"] = str(uuid4())
    later["expected_version"] = 1
    assert f.client.put(f"/sales/drafts/{destination}", json=later).status_code == 422


def test_copy_replay_rechecks_permission_and_foreign_source_is_hidden(copy_api):
    f = copy_api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    destination = uuid4()
    payload = _copy_payload(f)
    assert f.client.put(f"/sales/drafts/{destination}", json=payload).status_code == 200

    original_policy = f.user.access_policy
    f.user.access_policy = replace(
        original_policy,
        permission_names=frozenset(f.permissions - {"Manage_SalesDraft"}),
    )
    assert f.client.put(f"/sales/drafts/{destination}", json=payload).status_code == 403
    f.user.access_policy = original_policy

    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    foreign = _copy_payload(f)
    assert f.client.put(f"/sales/drafts/{uuid4()}", json=foreign).status_code == 404


def test_copy_does_not_clone_historical_effects_or_identities(copy_api):
    f = copy_api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    destination = uuid4()
    new_line_key = uuid4()
    payload = _copy_payload(f, line_key=new_line_key)
    assert f.client.put(f"/sales/drafts/{destination}", json=payload).status_code == 200

    destination_lines = f.db.query(SalesIntentLineRevision).filter_by(
        document_key=destination, version=1
    ).all()
    assert [row.line_key for row in destination_lines] == [new_line_key]
    data = f.client.get(f"/sales/drafts/{destination}").json()
    assert "payments" not in data
    assert "approvals" not in data
    assert "collections" not in data
    assert "invoice_key" not in data
    assert data["lines"][0]["reserved_quantity"] == "0"


def test_copy_origin_is_immutable_and_database_guard_rejects_reused_line(copy_api):
    f = copy_api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    destination = uuid4()
    payload = _copy_payload(f)
    assert f.client.put(f"/sales/drafts/{destination}", json=payload).status_code == 200

    with pytest.raises(DBAPIError), f.db.begin_nested():
        f.db.execute(text(
            "DELETE FROM containermgmt.sales_intent_copy_origins "
            "WHERE org_id=:org AND destination_document_key=:key"
        ), {"org": f.org_a, "key": destination})

    # The deferred database guard is independent from the service-level check.
    source_key = UUID(f.url.rsplit("/", 1)[-1])
    source_line = f.db.query(SalesIntentLineRevision).filter_by(
        document_key=source_key, version=1
    ).one().line_key
    unsafe_destination = uuid4()
    unsafe = _copy_payload(f, line_key=source_line)
    unsafe.pop("source_reference")
    assert f.client.put(
        f"/sales/drafts/{unsafe_destination}", json=unsafe
    ).status_code == 200
    unsafe_line = f.db.query(SalesIntentLineRevision).filter_by(
        document_key=unsafe_destination, version=1
    ).one()
    assert unsafe_line.line_key == source_line
    f.db.execute(text(
        "INSERT INTO containermgmt.sales_intent_copy_origins "
        "(org_id,destination_document_key,source_document_key,source_version,"
        "operation_key,created_by) VALUES "
        "(:org,:destination,:source,1,:operation,:actor)"
    ), {"org": f.org_a, "destination": unsafe_destination,
        "source": source_key, "operation": UUID(unsafe["operation_key"]),
        "actor": f.user.id})
    with pytest.raises(DBAPIError):
        f.db.execute(text(
            "SET CONSTRAINTS ALL IMMEDIATE"
        ))
    f.db.rollback()


def test_database_rejects_retroactive_origin_for_ordinary_draft(copy_api):
    f = copy_api
    assert f.client.put(f.url, json=f.payload).status_code == 200
    source_key = UUID(f.url.rsplit("/", 1)[-1])
    destination = uuid4()
    ordinary = deepcopy(f.payload)
    ordinary["operation_key"] = str(uuid4())
    ordinary["draft"]["lines"][0]["line_key"] = str(uuid4())
    assert f.client.put(
        f"/sales/drafts/{destination}", json=ordinary
    ).status_code == 200

    f.db.execute(text(
        "INSERT INTO containermgmt.sales_intent_copy_origins "
        "(org_id,destination_document_key,source_document_key,source_version,"
        "operation_key,created_by) VALUES "
        "(:org,:destination,:source,1,:operation,:actor)"
    ), {"org": f.org_a, "destination": destination,
        "source": source_key, "operation": UUID(ordinary["operation_key"]),
        "actor": f.user.id})
    with pytest.raises(DBAPIError, match="destination first-save operation"):
        f.db.execute(text(
            "SET CONSTRAINTS ALL IMMEDIATE"
        ))
    f.db.rollback()
