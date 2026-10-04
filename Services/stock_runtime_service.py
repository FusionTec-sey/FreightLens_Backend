"""Opt-in single-database development runtime, never disconnected enrollment.

The process operator pins node/branch epochs. HTTP callers cannot choose them.
Missing configuration disables writes; never adopt the database's latest owner.
No current preview or operational settings are enabled by importing this module.
"""
import json
import os
from dataclasses import dataclass
from uuid import UUID
from Services.posting_authority_service import AuthorityClaim, require_posting_authority


class StockRuntimeUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class LocalStockRuntime:
    claims: tuple[AuthorityClaim, ...]

    def claim_for(self, db, context, branch_id):
        matches = [claim for claim in self.claims if claim.org_id == context.org_id and claim.branch_id == branch_id]
        if len(matches) != 1:
            raise StockRuntimeUnavailable('No configured local runtime for this store')
        claim = matches[0]
        require_posting_authority(db, context, claim, branch_id=branch_id)
        return claim


def parse_local_stock_runtime(raw):
    if not raw or not raw.strip(): raise StockRuntimeUnavailable('Local stock execution is disabled')
    try:
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {'mode', 'claims'}
                or data['mode'] != 'local-development' or not isinstance(data['claims'], list)
                or not 1 <= len(data['claims']) <= 100):
            raise ValueError('Invalid runtime configuration')
        claims = []
        for row in data['claims']:
            if not isinstance(row, dict) or set(row) != {'org_id', 'branch_id', 'node_key', 'epoch'}:
                raise ValueError('Invalid claim fields')
            claims.append(AuthorityClaim(org_id=row['org_id'], branch_id=row['branch_id'],
                node_key=UUID(row['node_key']), epoch=row['epoch']))
        if len({(claim.org_id, claim.branch_id) for claim in claims}) != len(claims):
            raise ValueError('Ambiguous branch configuration')
        return LocalStockRuntime(tuple(claims))
    except (ValueError, TypeError, AttributeError, KeyError) as error:
        # Do not echo process configuration or identifiers into HTTP errors/logs.
        raise StockRuntimeUnavailable('Invalid local stock runtime configuration') from error


def local_stock_runtime():
    """Dependency reads operator-controlled process configuration, never headers."""
    return parse_local_stock_runtime(os.environ.get('FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON', ''))
