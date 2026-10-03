"""Explicit tenant-owned branches and physical locations; no legacy stock mapping."""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index, text
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class InventoryBranch(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_branches"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_inventory_branch_org_code"),
        UniqueConstraint("id", "org_id", name="uq_inventory_branch_id_org"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", name="ck_inventory_branch_code"),
        CheckConstraint("length(trim(name)) > 0", name="ck_inventory_branch_name"),
        CheckConstraint("kind IN ('STORE', 'WAREHOUSE')", name="ck_inventory_branch_kind"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    code = Column(String(32), nullable=False)
    name = Column(String(120), nullable=False)
    kind = Column(String(20), nullable=False)
    notes = Column(String(1000))
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))


class StockLocation(OrgMixin, AuditMixin, Base):
    __tablename__ = "stock_locations"
    __table_args__ = (
        ForeignKeyConstraint(["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id", "containermgmt.inventory_branches.org_id"],
            name="fk_stock_location_branch_org"),
        UniqueConstraint("id", "branch_id", "org_id", name="uq_stock_location_id_branch_org"),
        ForeignKeyConstraint(["parent_id", "branch_id", "org_id"],
            ["containermgmt.stock_locations.id", "containermgmt.stock_locations.branch_id", "containermgmt.stock_locations.org_id"],
            name="fk_stock_location_parent_scope"),
        UniqueConstraint("branch_id", "code", name="uq_stock_location_branch_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", name="ck_stock_location_code"),
        CheckConstraint("length(trim(name)) > 0", name="ck_stock_location_name"),
        CheckConstraint("kind IN ('SITE', 'ZONE', 'BIN')", name="ck_stock_location_kind"),
        CheckConstraint("(kind = 'SITE' AND parent_id IS NULL) OR (kind IN ('ZONE', 'BIN') AND parent_id IS NOT NULL)", name="ck_stock_location_parent_required"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_stock_location_not_self"),
        Index("ix_stock_location_parent_scope", "parent_id", "branch_id", "org_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, nullable=False, index=True)
    parent_id = Column(Integer, nullable=True)
    code = Column(String(32), nullable=False)
    name = Column(String(120), nullable=False)
    kind = Column(String(20), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
