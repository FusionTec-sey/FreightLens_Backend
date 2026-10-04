"""Server-owned central valuation identity for cloud and local development.

The cloud process pins one node identity and derives current cost-pool epochs from
the database. HTTP callers cannot choose claims. Invalid cloud configuration never
falls back; importing this module enables no posting action.
"""
import json
import os
from dataclasses import dataclass
from uuid import UUID
from Model.containermgmt.Inventory.PostingAuthority import (
    CostPoolAuthorityEpoch, StoreNode,
)
from Services.posting_authority_service import CostPoolAuthorityClaim, require_cost_pool_authority
from Utils.org_filter import apply_org_filter


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


@dataclass(frozen=True)
class CloudCostRuntime:
    """One configured cloud process identity; pool and epoch are database-derived."""
    node_key: UUID

    def claim_for(self, db, context, pool_id):
        if not db.in_transaction():
            raise ValueError('Cloud valuation authority requires an active transaction')
        if context.org_id not in context.allowed_org_ids:
            raise PermissionError('Central authority scope denied')
        node = apply_org_filter(db.query(StoreNode).filter_by(
            org_id=context.org_id, node_key=self.node_key, is_deleted=False),
            StoreNode, context).one_or_none()
        if node is None:
            raise PermissionError('Configured cloud runtime does not own this company')
        authority = apply_org_filter(db.query(CostPoolAuthorityEpoch).filter_by(
            org_id=context.org_id, cost_pool_id=pool_id, is_deleted=False),
            CostPoolAuthorityEpoch, context).order_by(
                CostPoolAuthorityEpoch.epoch.desc()).first()
        if authority is None or authority.state != 'ACTIVE' or authority.node_id != node.id:
            raise PermissionError(
                'Configured cloud runtime has no active authority for this cost pool')
        claim = CostPoolAuthorityClaim(context.org_id, pool_id, self.node_key,
            authority.epoch)
        require_cost_pool_authority(db, context, claim, cost_pool_id=pool_id)
        return claim


def parse_local_cost_runtime(raw):
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


def local_cost_runtime():
    return parse_local_cost_runtime(
        os.environ.get('FREIGHTLENS_LOCAL_COST_RUNTIME_JSON', ''))


def parse_cloud_cost_runtime(raw):
    try:
        key = UUID(raw.strip()) if isinstance(raw, str) else None
        if key is None or not key.int:
            raise ValueError('Missing cloud runtime key')
        return CloudCostRuntime(key)
    except (ValueError, TypeError, AttributeError) as error:
        raise CostRuntimeUnavailable(
            'Invalid cloud valuation runtime configuration') from error


def server_cost_runtime():
    """Prefer cloud identity; retain explicit local-development compatibility."""
    cloud = os.environ.get('FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY', '')
    if cloud.strip():
        return parse_cloud_cost_runtime(cloud)
    return local_cost_runtime()
