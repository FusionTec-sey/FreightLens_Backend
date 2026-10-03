"""Lossless policy extensions; never authorize reclassification of existing stock."""
from Schema.InventoryPolicySchema import InventoryPolicyConfig


def extends_policy(original, proposed):
    """Only add alternate units, preserving every original rule and factor."""
    if original is None or proposed is None:
        return False
    try:
        old = InventoryPolicyConfig.model_validate(original)
        new = InventoryPolicyConfig.model_validate(proposed)
    except ValueError:
        return False
    fixed = ("base_unit", "quantity_step", "tracking", "require_expiry", "require_shade", "require_calibre")
    if any(getattr(old, name) != getattr(new, name) for name in fixed):
        return False
    units = {row.unit: row.factor for row in new.conversions}
    return all(units.get(row.unit) == row.factor for row in old.conversions)
