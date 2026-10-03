"""Pure reconciliation for future reviewed UNTRACKED -> BATCH/SERIAL transitions.

Not a posting API. Source must be derived from scoped, locked authoritative rows;
caller must verify versions, node authority, identity uniqueness and approval at
posting. This validator never changes history, creates identities or releases holds.
Only same-base-unit, same-location reclassification is supported by this contract.
"""
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Schema.InventorySerialSchema import SerialOpening
from Services.inventory_quantity_service import QuantityBreakdown, ZERO
from Services.inventory_unit_service import convert_quantity


@dataclass(frozen=True)
class BatchAllocation:
    identity: StockBatchIdentity
    quantities: QuantityBreakdown


def validate_reclassification(source_policy, target_policy, source, *, batches=(), serials=None):
    """Return conserved quantities, not permission or a persisted conversion plan.

    One source balance only. Targets inherit that balance's product/location in
    the future adapter, never client-selected destination scope. No reservation
    migration, unit rescaling, condition change or tracking removal is inferred.
    """
    old = InventoryPolicyConfig.model_validate(source_policy)
    new = InventoryPolicyConfig.model_validate(target_policy)
    if not isinstance(source, QuantityBreakdown):
        raise ValueError("An authoritative quantity snapshot is required")
    if old.tracking != "UNTRACKED" or new.tracking not in ("BATCH", "SERIAL"):
        raise ValueError("Only ordinary stock to explicit batch or serial tracking is supported")
    if old.base_unit != new.base_unit:
        raise ValueError("Reclassification cannot change the base unit")
    if source.reserved:
        raise ValueError("Reserved stock requires separate approved reservation resolution")
    if source.on_hand <= 0:
        raise ValueError("A positive physical stock snapshot is required")
    # Validate all existing quantities under their original rules too; never fix
    # inconsistent source data merely because a target would accommodate it.
    for value in (source.on_hand, source.damaged, source.quarantined):
        convert_quantity(old, value, old.base_unit, allow_zero=True)
    if not isinstance(batches, tuple) or len(batches) > 1000:
        raise ValueError("Use an explicit tuple of at most 1000 batch allocations")
    if new.tracking == "BATCH":
        if not batches or serials is not None:
            raise ValueError("Batch tracking requires only an explicit batch manifest")
        keys, codes = set(), set()
        totals = [ZERO, ZERO, ZERO]
        with localcontext(Context(prec=48)):
            for row in batches:
                if not isinstance(row, BatchAllocation) or not isinstance(row.quantities, QuantityBreakdown):
                    raise ValueError("An explicit batch allocation is required")
                if not isinstance(row.identity, StockBatchIdentity):
                    raise ValueError("An explicit batch identity is required")
                identity = StockBatchIdentity.model_validate(row.identity.model_dump(mode="python"))
                if identity.batch_key in keys or identity.code in codes:
                    raise ValueError("Batch keys and codes must be unique within the manifest")
                keys.add(identity.batch_key); codes.add(identity.code)
                for field, required in (("expires_on", new.require_expiry),
                                        ("shade", new.require_shade), ("calibre", new.require_calibre)):
                    if required and getattr(identity, field) is None:
                        raise ValueError(f"Batch {field} must be supplied explicitly")
                quantities = row.quantities
                if quantities.reserved or quantities.on_hand <= 0:
                    raise ValueError("Batch allocations must be positive and cannot create reservations")
                for index, value in enumerate((quantities.on_hand, quantities.damaged, quantities.quarantined)):
                    totals[index] += convert_quantity(new, value, new.base_unit, allow_zero=True)
            result = QuantityBreakdown(totals[0], ZERO, totals[1], totals[2])
    else:
        if batches or not isinstance(serials, SerialOpening):
            raise ValueError("Serial tracking requires only an explicit serial manifest")
        # Revalidate even constructed models; identity/condition validation is shared
        # with the existing opening contract, not a second serial format.
        manifest = SerialOpening.model_validate(serials.model_dump(mode="python"))
        damaged = sum(item.condition == "DAMAGED" for item in manifest.items)
        quarantined = sum(item.condition == "QUARANTINED" for item in manifest.items)
        result = QuantityBreakdown(Decimal(len(manifest.items)), ZERO, Decimal(damaged), Decimal(quarantined))
    if result != source:
        raise ValueError("Manifest must conserve on-hand, damaged and quarantined quantities exactly")
    return result
