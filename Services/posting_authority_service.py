"""Internal same-database authority guard, not a disconnected failover protocol.

Claims must come from authenticated runtime identity, not a client request body.
Enrollment, reviewed transitions, recovery proof and distributed fencing remain
release gates. No public authority writer is exposed. Permissions/source checks
are additionally mandatory; matching a node claim is not sales authorization.
"""
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.orm import Session
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.PostingAuthority import StoreNode, BranchAuthorityEpoch
from Utils.org_filter import OrgContext, apply_org_filter


@dataclass(frozen=True)
class AuthorityClaim:
    org_id: int
    branch_id: int
    node_key: UUID
    epoch: int

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.org_id, self.branch_id, self.epoch)):
            raise ValueError("Authority requires positive organisation, branch and epoch")
        if not isinstance(self.node_key, UUID) or self.node_key.int == 0:
            raise ValueError("Authority requires a nonzero node UUID")


def require_posting_authority(db: Session, context: OrgContext, claim: AuthorityClaim,
                              *, branch_id: int) -> None:
    """Hold branch authority stable through outer commit, including replay checks."""
    if not db.in_transaction():
        raise ValueError("Authority check requires an active posting transaction")
    if (not isinstance(claim, AuthorityClaim) or context.org_id not in context.allowed_org_ids
            or claim.org_id != context.org_id or claim.branch_id != branch_id):
        raise PermissionError("Posting authority scope denied")
    branch = apply_org_filter(db.query(InventoryBranch).filter(
        InventoryBranch.id == branch_id, InventoryBranch.org_id == context.org_id,
        InventoryBranch.is_active.is_(True), InventoryBranch.is_deleted.is_(False)),
        InventoryBranch, context).with_for_update(read=True).one_or_none()
    if branch is None:
        raise PermissionError("Posting authority scope denied")
    authority = apply_org_filter(db.query(BranchAuthorityEpoch).filter(
        BranchAuthorityEpoch.org_id == context.org_id, BranchAuthorityEpoch.branch_id == branch_id,
        BranchAuthorityEpoch.is_deleted.is_(False)), BranchAuthorityEpoch, context).order_by(
            BranchAuthorityEpoch.epoch.desc()).first()
    if authority is None or authority.state != "ACTIVE" or authority.epoch != claim.epoch:
        raise PermissionError("Posting authority is missing, suspended or stale")
    node = apply_org_filter(db.query(StoreNode).filter(
        StoreNode.id == authority.node_id, StoreNode.org_id == context.org_id,
        StoreNode.node_key == claim.node_key, StoreNode.is_deleted.is_(False)),
        StoreNode, context).one_or_none()
    if node is None:
        raise PermissionError("Posting node does not own this branch")
