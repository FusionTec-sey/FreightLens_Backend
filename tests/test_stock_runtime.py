import json
from dataclasses import asdict
from uuid import uuid4
import pytest
from Services.stock_runtime_service import parse_local_stock_runtime, StockRuntimeUnavailable, local_stock_runtime
from tests.test_posting_authority import append_epoch
from tests.test_stock_ledger import stock  # noqa: F401


def config(f, **changes):
    claim = asdict(f.claim); claim['node_key'] = str(claim['node_key']); claim.update(changes)
    return json.dumps(dict(mode='local-development', claims=[claim]))


@pytest.mark.parametrize('raw', ['', '{}', 'null', '{invalid', '{"mode":"production","claims":[]}',
    '{"mode":"local-development","claims":[]}'])
def test_missing_or_invalid_configuration_disables_runtime(raw):
    with pytest.raises(StockRuntimeUnavailable): parse_local_stock_runtime(raw)


def test_operator_config_resolves_exact_persisted_owner(stock):
    f = stock; runtime = parse_local_stock_runtime(config(f))
    with f.factory.begin() as db:
        assert runtime.claim_for(db, f.context, f.branches[0]) == f.claim
        with pytest.raises(StockRuntimeUnavailable): runtime.claim_for(db, f.context, f.branches[1])
    append_epoch(f, 2, 'ACTIVE')
    with f.factory.begin() as db, pytest.raises(PermissionError):
        runtime.claim_for(db, f.context, f.branches[0])


def test_runtime_does_not_discover_or_adopt_another_node(stock):
    f = stock; runtime = parse_local_stock_runtime(config(f, node_key=str(uuid4())))
    with f.factory.begin() as db, pytest.raises(PermissionError): runtime.claim_for(db, f.context, f.branches[0])


def test_ambiguous_and_weak_claims_rejected(stock):
    f = stock
    data = json.loads(config(f)); data['claims'] *= 2
    with pytest.raises(StockRuntimeUnavailable): parse_local_stock_runtime(json.dumps(data))
    for changes in ({'epoch': True}, {'branch_id': '1'}, {'node_key': str(UUID_ZERO)}, {'unexpected': 'ignored'}):
        with pytest.raises(StockRuntimeUnavailable): parse_local_stock_runtime(config(f, **changes))


UUID_ZERO = '00000000-0000-0000-0000-000000000000'


def test_no_environment_default_and_explicit_operator_configuration(stock, monkeypatch):
    monkeypatch.delenv('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON', raising=False)
    with pytest.raises(StockRuntimeUnavailable): local_stock_runtime()
    monkeypatch.setenv('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON', config(stock))
    assert local_stock_runtime().claims == (stock.claim,)
