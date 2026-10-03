from Model.containermgmt.Inventory.UnitBarcode import UnitBarcodeRetirement
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Services.unit_barcode_service import barcode_query, barcode_product, BarcodeSourceUnavailable
from Services.policy_activation_service import active_policy
from Services.manager_case_service import CaseBinding, consume_case
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Utils.org_filter import apply_org_filter


def retirements(db, context):
    return apply_org_filter(db.query(UnitBarcodeRetirement).filter(
        UnitBarcodeRetirement.org_id == context.org_id,
        UnitBarcodeRetirement.is_deleted.is_(False)), UnitBarcodeRetirement, context)


def load_retirement_binding(db, context, barcode_id, *, replay_operation=None, lock=True):
    row = barcode_query(db, context).filter_by(id=barcode_id).one_or_none()
    if row is None:
        raise BarcodeSourceUnavailable("Registered barcode not found")
    product = barcode_product(db, context, row.product_id, lock=lock)
    retired = retirements(db, context).filter_by(barcode_id=row.id).one_or_none()
    if retired and retired.operation_key != replay_operation:
        raise PostingConflict("Barcode is already retired")
    policy = active_policy(db, context, product.id)
    if policy is None:
        raise PostingConflict("Reviewed policy history is required")
    return CaseBinding(context.org_id, "inventory.barcode.retire", "product.barcode", str(row.id), 1,
        {"product_id": row.product_id, "barcode_id": row.id, "barcode": row.barcode,
         "policy_version": row.policy_version, "active_policy_version": policy.version,
         "unit": row.unit, "base_quantity": format(row.factor, ".8f"),
         "catalogue_unit": product.unit})


def retire_barcode(factory, context, actor_id, operation_key, *, case_key, binding, authorize):
    if binding.action != "inventory.barcode.retire" or binding.source_type != "product.barcode":
        raise ValueError("A barcode retirement case is required")
    def load(db):
        return load_retirement_binding(db, context, int(binding.source_key), replay_operation=operation_key)
    def guard(db):
        authorize(db)
        if binding.org_id != context.org_id:
            raise PermissionError("Barcode retirement scope denied")
        if load(db).snapshot() != binding.snapshot():
            raise PostingConflict("Barcode or policy changed; request a new review")
    def apply(db):
        consume_case(db, context, actor_id, operation_key, case_key=case_key, binding=binding,
                     load_binding=load, authorize=authorize)
        case = apply_org_filter(db.query(ManagerCase).filter(ManagerCase.org_id == context.org_id,
            ManagerCase.case_key == case_key, ManagerCase.is_deleted.is_(False)), ManagerCase, context).one()
        db.add(UnitBarcodeRetirement(org_id=context.org_id, barcode_id=int(binding.source_key),
            case_id=case.id, operation_key=operation_key, created_by=actor_id))
        db.flush()
        return PostingEffect({"barcode_id": int(binding.source_key), "retired": True},
            {"kind": "inventory.barcode.retired", "barcode_id": int(binding.source_key), "case_key": str(case_key)})
    return execute_once(factory, context, actor_id, operation_key, "inventory.barcode.retire.v1",
        {"case_key": str(case_key), "binding": binding.snapshot()}, apply, authorize=guard)
