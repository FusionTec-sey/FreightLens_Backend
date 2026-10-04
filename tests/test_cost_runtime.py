import json
from dataclasses import asdict
from uuid import uuid4

import pytest

from Model.containermgmt.Inventory.CostPool import InventoryCostPool
from Model.containermgmt.Inventory.PostingAuthority import CostPoolAuthorityEpoch
from Services.posting_authority_service import CostPoolAuthorityClaim
from Services.cost_runtime_service import (
    CostRuntimeUnavailable,
    local_cost_runtime,
    parse_cloud_cost_runtime,
    parse_local_cost_runtime,
    server_cost_runtime,
)
from tests.test_stock_ledger import stock  # noqa: F401


ZERO_UUID = '00000000-0000-0000-0000-000000000000'


@pytest.fixture
def cost_runtime(stock):
    f = stock
    with f.factory.begin() as db:
        pool = InventoryCostPool(org_id=f.orgs[0], code='RUNTIME',
            name='Synthetic runtime pool', created_by=f.actor)
        db.add(pool); db.flush()
        db.add(CostPoolAuthorityEpoch(org_id=f.orgs[0], cost_pool_id=pool.id,
            node_id=f.node_id, epoch=1, state='ACTIVE',
            reason='Synthetic runtime authority', created_by=f.actor))
        f.pool = pool.id
    f.central_claim = CostPoolAuthorityClaim(f.orgs[0], f.pool, f.node_key, 1)
    return f


def append(f, epoch, state='SUSPENDED'):
    with f.factory.begin() as db:
        db.add(CostPoolAuthorityEpoch(org_id=f.orgs[0], cost_pool_id=f.pool,
            node_id=f.node_id, epoch=epoch, state=state,
            reason='Synthetic runtime transition', created_by=f.actor))


def config(f, **changes):
    claim = asdict(f.central_claim)
    claim['node_key'] = str(claim['node_key'])
    claim.update(changes)
    return json.dumps({'mode': 'local-development', 'claims': [claim]})


@pytest.mark.parametrize('raw', ['', '{}', 'null', '{invalid',
    '{"mode":"production","claims":[]}',
    '{"mode":"local-development","claims":[]}'])
def test_missing_or_invalid_local_configuration_disables_cost_runtime(raw):
    with pytest.raises(CostRuntimeUnavailable):
        parse_local_cost_runtime(raw)


def test_local_runtime_resolves_only_the_configured_pool(cost_runtime):
    f = cost_runtime
    runtime = parse_local_cost_runtime(config(f))
    with f.factory.begin() as db:
        assert runtime.claim_for(db, f.context, f.pool) == f.central_claim
        with pytest.raises(CostRuntimeUnavailable):
            runtime.claim_for(db, f.context, f.pool + 100000)
    append(f, 2, 'SUSPENDED')
    with f.factory.begin() as db, pytest.raises(PermissionError):
        runtime.claim_for(db, f.context, f.pool)


def test_cloud_runtime_derives_only_current_pool_epoch_owned_by_node(cost_runtime):
    f = cost_runtime
    runtime = parse_cloud_cost_runtime(str(f.node_key))
    with f.factory.begin() as db:
        assert runtime.claim_for(db, f.context, f.pool) == f.central_claim
    append(f, 2, 'ACTIVE')
    with f.factory.begin() as db:
        claim = runtime.claim_for(db, f.context, f.pool)
        assert claim.node_key == f.node_key and claim.epoch == 2
    foreign = parse_cloud_cost_runtime(str(uuid4()))
    with f.factory.begin() as db, pytest.raises(PermissionError):
        foreign.claim_for(db, f.context, f.pool)


def test_server_runtime_prefers_cloud_and_invalid_cloud_never_falls_back(cost_runtime, monkeypatch):
    f = cost_runtime
    monkeypatch.setenv('FREIGHTLENS_LOCAL_COST_RUNTIME_JSON', config(f))
    monkeypatch.setenv('FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY', str(f.node_key))
    assert server_cost_runtime().node_key == f.node_key
    monkeypatch.setenv('FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY', 'invalid')
    with pytest.raises(CostRuntimeUnavailable):
        server_cost_runtime()


@pytest.mark.parametrize('raw', ['', 'invalid', ZERO_UUID])
def test_invalid_cloud_cost_identity_is_rejected(raw):
    with pytest.raises(CostRuntimeUnavailable):
        parse_cloud_cost_runtime(raw)


def test_local_environment_has_no_default(cost_runtime, monkeypatch):
    monkeypatch.delenv('FREIGHTLENS_LOCAL_COST_RUNTIME_JSON', raising=False)
    monkeypatch.delenv('FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY', raising=False)
    with pytest.raises(CostRuntimeUnavailable):
        local_cost_runtime()
    monkeypatch.setenv('FREIGHTLENS_LOCAL_COST_RUNTIME_JSON', config(cost_runtime))
    assert local_cost_runtime().claims == (cost_runtime.central_claim,)
