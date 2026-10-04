"""Opt-in local central valuation identity; separate from stock-branch ownership."""
import json
import os
from dataclasses import dataclass
from uuid import UUID
from Services.posting_authority_service import CostPoolAuthorityClaim, require_cost_pool_authority


class CostRuntimeUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class LocalCostRuntime:
    claims: tuple[CostPoolAuthorityClaim, ...]

    def claim_for(self, db, context, pool_id):
        matches = [row for row in self.claims if row.org_id == context.org_id and row.cost_pool_id == pool_id]
        if len(matches) != 1: raise CostRuntimeUnavailable('No configured central runtime for this cost pool')
        claim = matches[0]
        require_cost_pool_authority(db, context, claim, cost_pool_id=pool_id)
        return claim


def local_cost_runtime():
    raw = os.environ.get('FREIGHTLENS_LOCAL_COST_RUNTIME_JSON', '')
    if not raw.strip(): raise CostRuntimeUnavailable('Local valuation execution is disabled')
    try:
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {'mode', 'claims'}
                or data['mode'] != 'local-development' or not isinstance(data['claims'], list)
                or not 1 <= len(data['claims']) <= 100):
            raise ValueError('Invalid central runtime')
        claims = []
        for row in data['claims']:
            if not isinstance(row, dict) or set(row) != {'org_id', 'cost_pool_id', 'node_key', 'epoch'}:
                raise ValueError('Invalid central claim')
            claims.append(CostPoolAuthorityClaim(org_id=row['org_id'], cost_pool_id=row['cost_pool_id'],
                node_key=UUID(row['node_key']), epoch=row['epoch']))
        if len({(row.org_id, row.cost_pool_id) for row in claims}) != len(claims):
            raise ValueError('Ambiguous central runtime')
        return LocalCostRuntime(tuple(claims))
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        raise CostRuntimeUnavailable('Invalid local valuation runtime configuration') from error
