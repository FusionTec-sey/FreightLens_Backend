from decimal import Decimal, localcontext
from uuid import uuid4
import pytest
from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventorySerialSchema import SerialOpening
from Services.inventory_quantity_service import QuantityBreakdown
from Services.stock_reclassification_service import BatchAllocation, validate_reclassification


OLD = {"base_unit": "PCS", "quantity_step": "1", "tracking": "UNTRACKED"}
BATCH = {**OLD, "tracking": "BATCH"}
SERIAL = {**OLD, "tracking": "SERIAL"}


def quantity(on_hand="3", damaged="1", quarantined="1", reserved="0"):
    return QuantityBreakdown(Decimal(on_hand), Decimal(reserved), Decimal(damaged), Decimal(quarantined))


def batch(code="LOT-A", quantities=None, **identity):
    return BatchAllocation(StockBatchIdentity(batch_key=uuid4(), code=code, **identity), quantities or quantity())


def serials(conditions=("AVAILABLE", "DAMAGED", "QUARANTINED")):
    return SerialOpening(items=[dict(serial_key=uuid4(), serial_number=f"TEST-{i}", condition=value)
                                for i, value in enumerate(conditions)])


def test_batch_manifest_conserves_each_condition_without_changing_source():
    source = quantity()
    rows = (batch(quantities=quantity("1", "1", "0")),
            batch("LOT-B", quantity("2", "0", "1")))
    assert validate_reclassification(OLD, BATCH, source, batches=rows) == source
    assert source == quantity()


def test_serial_manifest_uses_explicit_identity_conditions():
    assert validate_reclassification(OLD, SERIAL, quantity(), serials=serials()) == quantity()


@pytest.mark.parametrize("target", [BATCH, SERIAL])
def test_reserved_stock_cannot_be_reassigned(target):
    with pytest.raises(ValueError, match="Reserved stock"):
        validate_reclassification(OLD, target, quantity(reserved="1"), batches=(batch(),))


@pytest.mark.parametrize("field", ["on_hand", "damaged", "quarantined"])
def test_quantity_or_condition_differences_rejected(field):
    values = {"on_hand": "3", "damaged": "1", "quarantined": "1"}
    values[field] = "4" if field == "on_hand" else "0"
    with pytest.raises(ValueError, match="conserve"):
        validate_reclassification(OLD, BATCH, quantity(), batches=(batch(quantities=quantity(**values)),))


@pytest.mark.parametrize("field", ["expiry", "shade", "calibre"])
def test_required_batch_metadata_cannot_be_inferred(field):
    with pytest.raises(ValueError, match="supplied explicitly"):
        validate_reclassification(OLD, {**BATCH, f"require_{field}": True}, quantity(), batches=(batch(),))


def test_duplicate_batch_identity_or_code_rejected():
    row = batch(quantities=quantity("1", "0", "0"))
    for other in (row, batch(quantities=quantity("1", "0", "0"))):
        with pytest.raises(ValueError, match="unique"):
            validate_reclassification(OLD, BATCH, quantity("2", "0", "0"), batches=(row, other))


@pytest.mark.parametrize("old,new", [(BATCH, OLD), (SERIAL, BATCH), (OLD, OLD), (OLD, {**BATCH, "base_unit": "M2"})])
def test_unsupported_tracking_removal_or_unit_change_rejected(old, new):
    with pytest.raises(ValueError):
        validate_reclassification(old, new, quantity(), batches=(batch(),))


def test_serial_conditions_and_fractional_quantities_cannot_be_hidden():
    with pytest.raises(ValueError, match="conserve"):
        validate_reclassification(OLD, SERIAL, quantity(), serials=serials(("AVAILABLE",) * 3))
    with pytest.raises(ValueError, match="conserve"):
        validate_reclassification({**OLD, "quantity_step": "0.1"}, SERIAL,
            quantity("3.1"), serials=serials())


def test_exact_fractional_batches_ignore_callers_decimal_precision():
    policy = {**OLD, "base_unit": "M2", "quantity_step": "0.000001"}
    source = quantity("999999.123456", "0", "0")
    with localcontext() as ctx:
        ctx.prec = 5
        assert validate_reclassification(policy, {**policy, "tracking": "BATCH"}, source,
            batches=(batch(quantities=source),)) == source


@pytest.mark.parametrize("target,kwargs", [(BATCH, {}), (SERIAL, {}),
    (BATCH, {"batches": (batch(),), "serials": serials()}),
    (SERIAL, {"batches": (batch(),), "serials": serials()})])
def test_missing_or_mixed_manifests_rejected(target, kwargs):
    with pytest.raises(ValueError):
        validate_reclassification(OLD, target, quantity(), **kwargs)


def test_allocations_cannot_create_holds_or_round_to_target_increment():
    with pytest.raises(ValueError, match="reservations"):
        validate_reclassification(OLD, BATCH, quantity(), batches=(batch(quantities=quantity(reserved="1")),))
    fractional = quantity("1.5", "0", "0")
    with pytest.raises(ValueError, match="rounding"):
        validate_reclassification({**OLD, "quantity_step": "0.1"}, BATCH, fractional,
            batches=(batch(quantities=fractional),))


def test_zero_and_unbounded_batch_manifests_rejected():
    with pytest.raises(ValueError, match="positive physical"):
        validate_reclassification(OLD, BATCH, quantity("0", "0", "0"), batches=(batch(),))
    with pytest.raises(ValueError, match="at most 1000"):
        validate_reclassification(OLD, BATCH, quantity(), batches=(batch(),) * 1001)


def test_invalid_source_increment_does_not_get_repaired_by_target():
    fractional = quantity("1.5", "0", "0")
    with pytest.raises(ValueError, match="rounding"):
        validate_reclassification(OLD, {**BATCH, "quantity_step": "0.1"}, fractional,
            batches=(batch(quantities=fractional),))
