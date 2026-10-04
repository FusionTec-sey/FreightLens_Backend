"""Server-owned stock runtime identity for cloud and retained local development.

The cloud process pins one node identity and resolves only active branch epochs
owned by that node. Retained local development pins exact node/branch epochs.
HTTP callers cannot choose either. Missing configuration disables writes, and a
runtime never adopts a different database owner. Importing this enables nothing.
"""
import json
import os
from dataclasses import dataclass
from uuid import UUID
from Model.containermgmt.Inventory.PostingAuthority import (
    BranchAuthorityEpoch, StoreNode,
)
from Services.posting_authority_service import AuthorityClaim, require_posting_authority
from Utils.org_filter import apply_org_filter


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


@dataclass(frozen=True)
class CloudStockRuntime:
    """One configured cloud process identity; branch/epoch stay server-derived."""
    node_key: UUID

    def claim_for(self, db, context, branch_id):
        if not db.in_transaction():
            raise ValueError('Cloud stock authority requires an active transaction')
        if context.org_id not in context.allowed_org_ids:
            raise PermissionError('Posting authority scope denied')
        node = apply_org_filter(db.query(StoreNode).filter_by(
            org_id=context.org_id, node_key=self.node_key, is_deleted=False),
            StoreNode, context).one_or_none()
        if node is None:
            raise PermissionError('Configured cloud runtime does not own this company')
        authority = apply_org_filter(db.query(BranchAuthorityEpoch).filter_by(
            org_id=context.org_id, branch_id=branch_id, is_deleted=False),
            BranchAuthorityEpoch, context).order_by(
                BranchAuthorityEpoch.epoch.desc()).first()
        if authority is None or authority.state != 'ACTIVE' or authority.node_id != node.id:
            raise PermissionError(
                'Configured cloud runtime has no active authority for this store')
        claim = AuthorityClaim(context.org_id, branch_id, self.node_key,
            authority.epoch)
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


def parse_cloud_stock_runtime(raw):
    try:
        key = UUID(raw.strip()) if isinstance(raw, str) else None
        if key is None or not key.int:
            raise ValueError('Missing cloud runtime key')
        return CloudStockRuntime(key)
    except (ValueError, TypeError, AttributeError) as error:
        raise StockRuntimeUnavailable(
            'Invalid cloud stock runtime configuration') from error


def server_stock_runtime():
    """Prefer the single cloud identity; retain explicit local dev compatibility.

    An invalid cloud value never falls back. HTTP clients cannot supply either
    identity. With neither operator setting present, stock writes remain disabled.
    """
    cloud = os.environ.get('FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY', '')
    if cloud.strip():
        return parse_cloud_stock_runtime(cloud)
    return local_stock_runtime()
