"""Versioned per-branch logical account configuration.

These tables contain opaque account references only. They do not contain balances,
journals, exports, bank credentials, or a fallback branch configuration.
"""
from sqlalchemy import (Boolean, CheckConstraint, Column, ForeignKeyConstraint,
                        Integer, String, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin
from Model.containermgmt.Inventory.Location import InventoryBranch  # noqa: F401
from Model.containermgmt.Inventory.PostingOperation import PostingOperation  # noqa: F401


ACCOUNT_ROLES = (
    "SALES_REVENUE",
    "OUTPUT_TAX_PAYABLE",
    "CUSTOMER_CREDIT_LIABILITY",
    "COST_OF_GOODS_SOLD",
    "INVENTORY_ASSET",
    "CASH_OVER_SHORT",
    "CASH_DEPOSIT_CLEARING",
)

AUDIT_CHECK = "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL"


class BranchAccountMapping(OrgMixin, AuditMixin, Base):
    __tablename__ = "branch_account_mappings"
    __table_args__ = (
        UniqueConstraint("mapping_key", "org_id", name="uq_branch_account_mapping_scope"),
        UniqueConstraint("org_id", "branch_id", "account_role",
                         name="uq_branch_account_mapping_target"),
        ForeignKeyConstraint(
            ["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id",
             "containermgmt.inventory_branches.org_id"],
            name="fk_branch_account_mapping_branch",
        ),
        ForeignKeyConstraint(
            ["org_id", "creation_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_branch_account_mapping_creation",
        ),
        CheckConstraint(
            "account_role IN (" + ",".join(f"'{role}'" for role in ACCOUNT_ROLES) + ")",
            name="ck_branch_account_mapping_role",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_branch_account_mapping_audit"),
        {"schema": "containermgmt"},
    )

    mapping_key = Column(UUID(as_uuid=True), primary_key=True)
    branch_id = Column(Integer, nullable=False, index=True)
    account_role = Column(String(40), nullable=False, index=True)
    creation_operation_key = Column(UUID(as_uuid=True), nullable=False)


class BranchAccountMappingRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "branch_account_mapping_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["mapping_key", "org_id"],
            ["containermgmt.branch_account_mappings.mapping_key",
             "containermgmt.branch_account_mappings.org_id"],
            name="fk_branch_account_revision_scope",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_branch_account_revision_operation",
        ),
        UniqueConstraint("org_id", "mapping_key", "version",
                         name="uq_branch_account_revision_version"),
        UniqueConstraint("org_id", "operation_key",
                         name="uq_branch_account_revision_operation"),
        CheckConstraint("version > 0", name="ck_branch_account_revision_version"),
        CheckConstraint(
            "length(trim(account_ref)) > 0 AND length(trim(label)) > 0 "
            "AND length(trim(reason)) > 0",
            name="ck_branch_account_revision_text",
        ),
        CheckConstraint(
            "account_ref ~ '^[A-Z0-9][A-Z0-9_.:-]{0,63}$'",
            name="ck_branch_account_revision_ref",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_branch_account_revision_audit"),
        {"schema": "containermgmt"},
    )

    id = Column(Integer, primary_key=True)
    mapping_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    account_ref = Column(String(64), nullable=False)
    label = Column(String(120), nullable=False)
    is_enabled = Column(Boolean, nullable=False)
    reason = Column(String(500), nullable=False)
