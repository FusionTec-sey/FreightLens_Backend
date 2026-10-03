"""Append-only source-linked opening valuation; not final reconciled accounts."""
from sqlalchemy import Column, Integer, String, Numeric, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index, DDL, event, text
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class InventoryValuation(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_valuations"
    __table_args__ = (
        UniqueConstraint("org_id", "cost_pool_id", "product_id", "version", name="uq_valuation_pool_version"),
        UniqueConstraint('id', 'org_id', name='uq_valuation_id_org'),
        Index('uq_valuation_opening_source', 'org_id', 'balance_id', 'source_version', unique=True, postgresql_where=text("kind = 'OPENING'")),
        UniqueConstraint('org_id', 'operation_key', 'balance_id', name='uq_valuation_operation_line'),
        ForeignKeyConstraint(['source_valuation_id', 'org_id'], ['containermgmt.inventory_valuations.id', 'containermgmt.inventory_valuations.org_id'], name='fk_valuation_charge_source'),
        ForeignKeyConstraint(["cost_pool_id", "org_id"], ["containermgmt.inventory_cost_pools.id", "containermgmt.inventory_cost_pools.org_id"], name="fk_valuation_pool"),
        ForeignKeyConstraint(["balance_id", "product_id", "org_id"], ["containermgmt.inventory_stock_balances.id", "containermgmt.inventory_stock_balances.product_id", "containermgmt.inventory_stock_balances.org_id"], name="fk_valuation_stock"),
        ForeignKeyConstraint(["balance_id", "source_version"], ["containermgmt.inventory_stock_movements.balance_id", "containermgmt.inventory_stock_movements.version"], name="fk_valuation_movement"),
        ForeignKeyConstraint(["org_id", "operation_key"], ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"], name="fk_valuation_operation", deferrable=True, initially="DEFERRED"),
        CheckConstraint("version > 0 AND source_version = 1 AND quantity >= 0 AND quantity < 1000000000000 AND pool_quantity >= quantity AND pool_quantity < 1000000000000", name="ck_valuation_quantity_v2"),
        CheckConstraint("(kind = 'OPENING' AND quantity > 0 AND source_valuation_id IS NULL) OR (kind = 'CHARGE' AND quantity = 0 AND goods_value_scr = 0 AND source_valuation_id IS NOT NULL)", name='ck_valuation_kind'),
        CheckConstraint("goods_value_scr >= 0 AND additional_cost_scr >= 0 AND pool_value_scr >= goods_value_scr + additional_cost_scr AND pool_value_scr < 1000000000000000000", name="ck_valuation_value"),
        CheckConstraint("calculation_policy = 'pool-wac-v2' AND currency = 'SCR' AND status = 'UNRECONCILED' AND length(trim(reason)) > 0 AND length(trim(base_unit)) > 0", name="ck_valuation_contract"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_valuation_audit"),
        Index("ix_valuation_product", "product_id", "org_id"),
        Index("ix_valuation_pool", "cost_pool_id", "org_id"),
        Index("ix_valuation_balance", "balance_id", "product_id", "org_id"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False, server_default='OPENING')
    source_valuation_id = Column(Integer, nullable=True, index=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    cost_pool_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    balance_id = Column(Integer, nullable=False)
    source_version = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False)
    base_unit = Column(String(50), nullable=False)
    quantity = Column(Numeric(18, 6), nullable=False)
    goods_value_scr = Column(Numeric(24, 6), nullable=False)
    additional_cost_scr = Column(Numeric(24, 6), nullable=False)
    pool_quantity = Column(Numeric(18, 6), nullable=False)
    pool_value_scr = Column(Numeric(24, 6), nullable=False)
    calculation_policy = Column(String(30), nullable=False)
    currency = Column(String(3), nullable=False)
    status = Column(String(20), nullable=False)
    reason = Column(String(500), nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_valuation_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Inventory valuation records are immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER valuation_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_valuations FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_valuation_change()"""
event.listen(InventoryValuation.__table__, "after_create", DDL(FUNCTION))
event.listen(InventoryValuation.__table__, "after_create", DDL(TRIGGER))

CHARGE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_charge_valuation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF NEW.kind = 'CHARGE' AND NOT EXISTS (
 SELECT 1 FROM containermgmt.inventory_valuations source
 JOIN containermgmt.inventory_cost_charge_uses charge ON charge.operation_key=NEW.operation_key AND charge.org_id=NEW.org_id
 JOIN containermgmt.inventory_cost_allocation_proposals proposal ON proposal.proposal_key=charge.proposal_key AND proposal.org_id=NEW.org_id
 JOIN containermgmt.manager_case_uses used ON used.operation_key=NEW.operation_key AND used.org_id=NEW.org_id
 JOIN containermgmt.manager_cases review ON review.id=used.case_id AND review.org_id=NEW.org_id
 CROSS JOIN LATERAL jsonb_array_elements(proposal.snapshot->'lines') line
 WHERE source.id=NEW.source_valuation_id AND source.org_id=NEW.org_id AND source.kind='OPENING'
 AND source.cost_pool_id=NEW.cost_pool_id AND source.product_id=NEW.product_id AND source.balance_id=NEW.balance_id
 AND source.base_unit=NEW.base_unit AND proposal.cost_pool_id=NEW.cost_pool_id
 AND (line->>'valuation_id')::integer=source.id AND (line->>'allocated_scr')::numeric=NEW.additional_cost_scr
 AND charge.created_by=NEW.created_by AND used.created_by=NEW.created_by
 AND review.action='inventory.cost.verify-charge' AND review.source_version=2
 AND review.source_key=charge.proposal_key::text
) THEN RAISE EXCEPTION 'Charge valuation requires matching source, approved case use and charge allocation'; END IF;
RETURN NEW; END; $$"""
CHARGE_TRIGGER = """CREATE TRIGGER charge_valuation_guard BEFORE INSERT ON containermgmt.inventory_valuations
FOR EACH ROW EXECUTE FUNCTION containermgmt.guard_charge_valuation()"""
event.listen(InventoryValuation.__table__, 'after_create', DDL(CHARGE_FUNCTION))
event.listen(InventoryValuation.__table__, 'after_create', DDL(CHARGE_TRIGGER))
