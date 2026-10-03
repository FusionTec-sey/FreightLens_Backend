"""Valuation identities are independent of selling branches and physical bins."""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index, text
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class InventoryCostPool(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_cost_pools"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_inventory_cost_pool_org_code"),
        UniqueConstraint("id", "org_id", name="uq_inventory_cost_pool_id_org"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", name="ck_inventory_cost_pool_code"),
        CheckConstraint("length(trim(name)) > 0", name="ck_inventory_cost_pool_name"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    code = Column(String(32), nullable=False)
    name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))


class BranchCostPool(OrgMixin, AuditMixin, Base):
    """Initial binding only. Reassignment requires a future audited cutover workflow."""
    __tablename__ = "branch_cost_pools"
    __table_args__ = (
        UniqueConstraint("branch_id", name="uq_branch_cost_pool_branch"),
        ForeignKeyConstraint(["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id", "containermgmt.inventory_branches.org_id"],
            name="fk_branch_cost_pool_branch_org"),
        ForeignKeyConstraint(["cost_pool_id", "org_id"],
            ["containermgmt.inventory_cost_pools.id", "containermgmt.inventory_cost_pools.org_id"],
            name="fk_branch_cost_pool_pool_org"),
        Index("ix_branch_cost_pool_pool_org", "cost_pool_id", "org_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, nullable=False)
    cost_pool_id = Column(Integer, nullable=False)
