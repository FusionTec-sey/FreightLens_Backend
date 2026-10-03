"""Immutable node identities and append-only branch authority epochs.

No credential enrollment or automatic failover is implied by these records.
"""
from sqlalchemy import (Column, Integer, BigInteger, String, UniqueConstraint,
                        ForeignKeyConstraint, CheckConstraint, Index, DDL, event)
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class StoreNode(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_store_nodes"
    __table_args__ = (
        UniqueConstraint("org_id", "node_key", name="uq_store_node_org_key"),
        UniqueConstraint("id", "org_id", name="uq_store_node_id_org"),
        CheckConstraint("node_key <> '00000000-0000-0000-0000-000000000000'::uuid",
                        name="ck_store_node_key"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
                        name="ck_store_node_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    node_key = Column(UUID(as_uuid=True), nullable=False)


class BranchAuthorityEpoch(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_branch_authority_epochs"
    __table_args__ = (
        ForeignKeyConstraint(["branch_id", "org_id"],
            ["containermgmt.inventory_branches.id", "containermgmt.inventory_branches.org_id"],
            name="fk_authority_branch_org"),
        ForeignKeyConstraint(["node_id", "org_id"],
            ["containermgmt.inventory_store_nodes.id", "containermgmt.inventory_store_nodes.org_id"],
            name="fk_authority_node_org"),
        UniqueConstraint("org_id", "branch_id", "epoch", name="uq_authority_branch_epoch"),
        Index("ix_authority_node_org", "node_id", "org_id"),
        CheckConstraint("epoch > 0", name="ck_authority_epoch_positive"),
        CheckConstraint("state IN ('ACTIVE', 'SUSPENDED')", name="ck_authority_state"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_authority_reason"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
                        name="ck_authority_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, nullable=False)
    node_id = Column(Integer, nullable=False)
    epoch = Column(BigInteger, nullable=False)
    state = Column(String(16), nullable=False)
    reason = Column(String(500), nullable=False)


class CostPoolAuthorityEpoch(OrgMixin, AuditMixin, Base):
    """Central valuation ownership, distinct from physical branch ownership."""
    __tablename__ = "inventory_cost_pool_authority_epochs"
    __table_args__ = (
        ForeignKeyConstraint(["cost_pool_id", "org_id"],
            ["containermgmt.inventory_cost_pools.id", "containermgmt.inventory_cost_pools.org_id"],
            name="fk_pool_authority_pool_org"),
        ForeignKeyConstraint(["node_id", "org_id"],
            ["containermgmt.inventory_store_nodes.id", "containermgmt.inventory_store_nodes.org_id"],
            name="fk_pool_authority_node_org"),
        UniqueConstraint("org_id", "cost_pool_id", "epoch", name="uq_pool_authority_epoch"),
        Index("ix_pool_authority_node_org", "node_id", "org_id"),
        CheckConstraint("epoch > 0", name="ck_pool_authority_epoch"),
        CheckConstraint("state IN ('ACTIVE', 'SUSPENDED')", name="ck_pool_authority_state"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_pool_authority_reason"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL",
                        name="ck_pool_authority_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    cost_pool_id = Column(Integer, nullable=False)
    node_id = Column(Integer, nullable=False)
    epoch = Column(BigInteger, nullable=False)
    state = Column(String(16), nullable=False)
    reason = Column(String(500), nullable=False)


IMMUTABLE_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.reject_posting_authority_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Posting authority history is immutable; append a new epoch';
END;
$$
"""
SEQUENCE_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.check_posting_authority_epoch()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous_epoch bigint;
BEGIN
    -- Excludes concurrent epoch changes and waits for guarded postings to finish.
    PERFORM id FROM containermgmt.inventory_branches
        WHERE id = NEW.branch_id AND org_id = NEW.org_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Authority branch scope not found';
    END IF;
    SELECT COALESCE(MAX(epoch), 0) INTO previous_epoch
        FROM containermgmt.inventory_branch_authority_epochs
        WHERE org_id = NEW.org_id AND branch_id = NEW.branch_id;
    IF NEW.epoch <> previous_epoch + 1 THEN
        RAISE EXCEPTION 'Authority epoch must be the next consecutive version';
    END IF;
    RETURN NEW;
END;
$$
"""
SEQUENCE_TRIGGER = """
CREATE TRIGGER posting_authority_sequence
BEFORE INSERT ON containermgmt.inventory_branch_authority_epochs
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_posting_authority_epoch()
"""


def immutable_trigger(table):
    return f"""CREATE TRIGGER posting_authority_immutable BEFORE UPDATE OR DELETE
        ON containermgmt.{table} FOR EACH ROW
        EXECUTE FUNCTION containermgmt.reject_posting_authority_change()"""


for model in (StoreNode, BranchAuthorityEpoch, CostPoolAuthorityEpoch):
    event.listen(model.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
    event.listen(model.__table__, "after_create", DDL(immutable_trigger(model.__tablename__)))
event.listen(BranchAuthorityEpoch.__table__, "after_create", DDL(SEQUENCE_FUNCTION))
event.listen(BranchAuthorityEpoch.__table__, "after_create", DDL(SEQUENCE_TRIGGER))

POOL_SEQUENCE_FUNCTION = """
CREATE OR REPLACE FUNCTION containermgmt.check_cost_pool_authority_epoch()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE previous_epoch bigint;
BEGIN
    PERFORM id FROM containermgmt.inventory_cost_pools
        WHERE id = NEW.cost_pool_id AND org_id = NEW.org_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Authority cost pool scope not found'; END IF;
    SELECT COALESCE(MAX(epoch), 0) INTO previous_epoch
        FROM containermgmt.inventory_cost_pool_authority_epochs
        WHERE org_id = NEW.org_id AND cost_pool_id = NEW.cost_pool_id;
    IF NEW.epoch <> previous_epoch + 1 THEN
        RAISE EXCEPTION 'Pool authority epoch must be the next consecutive version';
    END IF;
    RETURN NEW;
END;
$$
"""
POOL_SEQUENCE_TRIGGER = """
CREATE TRIGGER pool_authority_sequence BEFORE INSERT
ON containermgmt.inventory_cost_pool_authority_epochs
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_cost_pool_authority_epoch()
"""
event.listen(CostPoolAuthorityEpoch.__table__, "after_create", DDL(POOL_SEQUENCE_FUNCTION))
event.listen(CostPoolAuthorityEpoch.__table__, "after_create", DDL(POOL_SEQUENCE_TRIGGER))
