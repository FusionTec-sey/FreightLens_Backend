"""Permanent product/unit identities bound to an exact reviewed policy."""
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, UniqueConstraint, ForeignKeyConstraint, CheckConstraint, DDL, event
from sqlalchemy.dialects.postgresql import UUID
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin


class UnitBarcode(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_unit_barcodes"
    __table_args__ = (
        UniqueConstraint("org_id", "barcode", name="uq_unit_barcode_org_code"),
        UniqueConstraint("org_id", "operation_key", name="uq_unit_barcode_operation"),
        ForeignKeyConstraint(["org_id", "product_id", "policy_version"],
            ["containermgmt.inventory_product_policy_activations.org_id", "containermgmt.inventory_product_policy_activations.product_id",
             "containermgmt.inventory_product_policy_activations.version"], name="fk_unit_barcode_policy"),
        ForeignKeyConstraint(["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_unit_barcode_posting", deferrable=True, initially="DEFERRED"),
        CheckConstraint("length(barcode) BETWEEN 1 AND 100 AND barcode !~ '[^!-~]'", name="ck_unit_barcode_code"),
        CheckConstraint("factor > 0 AND factor < 1000000000 AND policy_version > 0", name="ck_unit_barcode_factor"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_unit_barcode_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, nullable=False, index=True)
    policy_version = Column(Integer, nullable=False)
    barcode = Column(String(100), nullable=False)
    unit = Column(String(50), nullable=False)
    factor = Column(Numeric(17, 8), nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)


FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_unit_barcode_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Unit barcode identities are immutable'; END; $$"""
TRIGGER = """CREATE TRIGGER unit_barcode_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_unit_barcodes FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_unit_barcode_change()"""
event.listen(UnitBarcode.__table__, "after_create", DDL(FUNCTION))
event.listen(UnitBarcode.__table__, "after_create", DDL(TRIGGER))


class UnitBarcodeRetirement(OrgMixin, AuditMixin, Base):
    __tablename__ = "inventory_unit_barcode_retirements"
    __table_args__ = (
        UniqueConstraint("barcode_id", name="uq_barcode_retirement_identity"),
        ForeignKeyConstraint(["case_id", "org_id"], ["containermgmt.manager_cases.id", "containermgmt.manager_cases.org_id"], name="fk_barcode_retirement_case"),
        ForeignKeyConstraint(["org_id", "operation_key"], ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"], name="fk_barcode_retirement_posting", deferrable=True, initially="DEFERRED"),
        CheckConstraint("created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL", name="ck_barcode_retirement_audit"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    barcode_id = Column(Integer, ForeignKey("containermgmt.inventory_unit_barcodes.id"), nullable=False)
    case_id = Column(Integer, nullable=False, index=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False, index=True)


RETIREMENT_GUARD = """CREATE OR REPLACE FUNCTION containermgmt.check_barcode_retirement()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF NOT EXISTS (SELECT 1 FROM containermgmt.inventory_unit_barcodes b
 JOIN containermgmt.manager_cases c ON c.org_id=b.org_id
 JOIN containermgmt.manager_case_uses u ON u.org_id=c.org_id AND u.case_id=c.id
 WHERE b.id=NEW.barcode_id AND b.org_id=NEW.org_id AND c.id=NEW.case_id
 AND c.action='inventory.barcode.retire' AND c.source_type='product.barcode'
 AND c.source_key=b.id::text AND u.operation_key=NEW.operation_key) THEN
 RAISE EXCEPTION 'Barcode retirement requires an exact scoped consumed approval';
END IF;
RETURN NEW; END; $$"""
RETIREMENT_CHECK = """CREATE TRIGGER barcode_retirement_scope BEFORE INSERT
ON containermgmt.inventory_unit_barcode_retirements FOR EACH ROW
EXECUTE FUNCTION containermgmt.check_barcode_retirement()"""
RETIREMENT_IMMUTABLE = """CREATE TRIGGER barcode_retirement_immutable BEFORE UPDATE OR DELETE
ON containermgmt.inventory_unit_barcode_retirements FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_unit_barcode_change()"""
for statement in (FUNCTION, RETIREMENT_GUARD, RETIREMENT_CHECK, RETIREMENT_IMMUTABLE):
    event.listen(UnitBarcodeRetirement.__table__, "after_create", DDL(statement))
