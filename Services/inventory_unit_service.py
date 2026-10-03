"""Exact unit conversion shared by preparation and trusted posting adapters."""
from decimal import Decimal, Context, localcontext
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.inventory_quantity_service import QuantityBreakdown


def convert_quantity(policy: InventoryPolicyConfig, quantity: Decimal, unit: str, *, allow_zero=False):
    if not isinstance(policy, InventoryPolicyConfig):
        raise ValueError("An explicit validated inventory policy is required")
    if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity < 0 or (not allow_zero and quantity == 0):
        raise ValueError("Quantity must be a positive exact decimal")
    # Bound the input before multiplication, independently of decimal context.
    QuantityBreakdown(quantity)
    factors = {policy.base_unit.casefold(): Decimal(1),
               **{row.unit.casefold(): row.factor for row in policy.conversions}}
    if not isinstance(unit, str) or unit.strip().casefold() not in factors:
        raise ValueError("Unit is not configured in this policy")
    with localcontext(Context(prec=48)):
        result = quantity * factors[unit.strip().casefold()]
        QuantityBreakdown(result)
        if result % Decimal(policy.quantity_step):
            raise ValueError("Converted quantity must be an exact multiple of the base quantity increment; rounding is not allowed")
    return result
