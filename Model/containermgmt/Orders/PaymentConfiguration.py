"""Tenant-owned payment configuration. No monetary state lives in these tables."""
from sqlalchemy import (Boolean, CheckConstraint, Column, ForeignKeyConstraint,
                        Integer, String, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin
from Model.containermgmt.Inventory.Location import InventoryBranch  # noqa: F401
from Model.containermgmt.Inventory.PostingOperation import PostingOperation  # noqa: F401


class PaymentMethod(OrgMixin, AuditMixin, Base):
    __tablename__ = "payment_methods"
    __table_args__ = (
        UniqueConstraint("method_key", "org_id", name="uq_payment_method_scope"),
        UniqueConstraint("org_id", "code", name="uq_payment_method_code"),
        ForeignKeyConstraint(["org_id", "creation_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            deferrable=True, initially="DEFERRED", name="fk_payment_method_creation"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", name="ck_payment_method_code"),
        {"schema": "containermgmt"},
    )
    method_key = Column(UUID(as_uuid=True), primary_key=True)
    code = Column(String(32), nullable=False)
    creation_operation_key = Column(UUID(as_uuid=True), nullable=False)


class PaymentMethodRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "payment_method_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["method_key", "org_id"],
            ["containermgmt.payment_methods.method_key", "containermgmt.payment_methods.org_id"],
            name="fk_payment_method_revision_scope"),
        ForeignKeyConstraint(["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            deferrable=True, initially="DEFERRED", name="fk_payment_method_revision_operation"),
        UniqueConstraint("org_id", "method_key", "version", name="uq_payment_method_revision_version"),
        UniqueConstraint("org_id", "operation_key", name="uq_payment_method_revision_operation"),
        CheckConstraint("version > 0", name="ck_payment_method_version"),
        CheckConstraint("kind IN ('CASH', 'CARD')", name="ck_payment_method_kind"),
        CheckConstraint("length(trim(label)) > 0 AND length(trim(reason)) > 0",
                        name="ck_payment_method_revision_text"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    method_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    label = Column(String(120), nullable=False)
    kind = Column(String(12), nullable=False)
    is_enabled = Column(Boolean, nullable=False)
    reason = Column(String(500), nullable=False)


class BranchReceivingAccount(OrgMixin, AuditMixin, Base):
    __tablename__ = "branch_receiving_accounts"
    __table_args__ = (
        UniqueConstraint("mapping_key", "org_id", name="uq_receiving_mapping_scope"),
        UniqueConstraint("org_id", "branch_id", "method_key", name="uq_receiving_mapping_target"),
        ForeignKeyConstraint(["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id", "containermgmt.inventory_branches.org_id"],
            name="fk_receiving_mapping_branch"),
        ForeignKeyConstraint(["method_key", "org_id"],
            ["containermgmt.payment_methods.method_key", "containermgmt.payment_methods.org_id"],
            name="fk_receiving_mapping_method"),
        ForeignKeyConstraint(["org_id", "creation_operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            deferrable=True, initially="DEFERRED", name="fk_receiving_mapping_creation"),
        {"schema": "containermgmt"},
    )
    mapping_key = Column(UUID(as_uuid=True), primary_key=True)
    branch_id = Column(Integer, nullable=False, index=True)
    method_key = Column(UUID(as_uuid=True), nullable=False, index=True)
    creation_operation_key = Column(UUID(as_uuid=True), nullable=False)


class BranchReceivingAccountRevision(OrgMixin, AuditMixin, Base):
    __tablename__ = "branch_receiving_account_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["mapping_key", "org_id"],
            ["containermgmt.branch_receiving_accounts.mapping_key",
             "containermgmt.branch_receiving_accounts.org_id"],
            name="fk_receiving_revision_scope"),
        ForeignKeyConstraint(["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id",
             "containermgmt.inventory_posting_operations.operation_key"],
            deferrable=True, initially="DEFERRED", name="fk_receiving_revision_operation"),
        UniqueConstraint("org_id", "mapping_key", "version", name="uq_receiving_revision_version"),
        UniqueConstraint("org_id", "operation_key", name="uq_receiving_revision_operation"),
        CheckConstraint("version > 0", name="ck_receiving_revision_version"),
        CheckConstraint("length(trim(account_ref)) > 0 AND length(trim(label)) > 0 "
                        "AND length(trim(reason)) > 0", name="ck_receiving_revision_text"),
        CheckConstraint("account_ref ~ '^SYNTH_[A-Z0-9][A-Z0-9_.:-]*$'",
                        name="ck_receiving_account_ref_synthetic"),
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
