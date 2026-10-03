"""Explicit-pool weighted-average arithmetic, not a stock posting or authorization API.

All inputs are base-unit quantities and SCR values, already converted/approved
by the caller. Immutable results are intended for a future transactional ledger.
No database, current_stock, selling price, tax, invoice or outbox is changed here.
"""
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from typing import Mapping

QUANTUM = Decimal("0.000001")
COSTING_POLICY_VERSION = "pool-wac-v2"
ZERO = Decimal("0.000000")
MAX_QUANTITY = Decimal("999999999999.999999")
MAX_VALUE = Decimal("999999999999999999.999999")
_COST_CONTEXT = Context(prec=48, rounding=ROUND_HALF_UP)


class CostingError(ValueError):
    """Invalid costing input or violated quantity/value invariant."""


def _number(value: Decimal, label: str, maximum: Decimal, positive=False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CostingError(f"{label} must be a finite Decimal (not a float)")
    if value < 0 or value > maximum or (positive and value == 0):
        raise CostingError(f"{label} is outside the supported range")
    with localcontext(_COST_CONTEXT) as context:
        context.prec = 48
        normalized = value.quantize(QUANTUM, rounding=ROUND_HALF_UP)
    if value != normalized:
        raise CostingError(f"{label} has more than six decimal places")
    return normalized


def _portion(value: Decimal, quantity: Decimal, total_quantity: Decimal) -> Decimal:
    # Exhausting a lot consumes the exact residual rather than leaving ghost value.
    if quantity == total_quantity:
        return value
    with localcontext(_COST_CONTEXT) as context:
        context.prec = 48
        return (value * quantity / total_quantity).quantize(QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostPool:
    org_id: int
    cost_pool_id: int
    product_id: int

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.org_id, self.cost_pool_id, self.product_id)):
            raise CostingError("Organisation, cost pool and product IDs must be positive integers")


@dataclass(frozen=True)
class CostBalance:
    pool: CostPool
    quantity: Decimal
    value_scr: Decimal

    def __post_init__(self):
        if not isinstance(self.pool, CostPool):
            raise CostingError("An organisation/cost-pool/product identity is required")
        _number(self.quantity, "Quantity", MAX_QUANTITY)
        _number(self.value_scr, "Value", MAX_VALUE)
        if self.quantity == 0 and self.value_scr != 0:
            raise CostingError("Zero stock cannot retain inventory value")

    @property
    def average_cost_scr(self) -> Decimal:
        """Display/reference average only; issues use total value, not this rounded rate."""
        if self.quantity == 0:
            return ZERO
        with localcontext(_COST_CONTEXT) as context:
            context.prec = 48
            return (self.value_scr / self.quantity).quantize(QUANTUM, rounding=ROUND_HALF_UP)


def receive(balance: CostBalance, quantity: Decimal, goods_value_scr: Decimal,
            additional_cost_scr: Decimal = ZERO) -> CostBalance:
    """Add approved receipt value; cost changes do not publish selling prices."""
    _number(quantity, "Received quantity", MAX_QUANTITY, positive=True)
    _number(goods_value_scr, "Goods value", MAX_VALUE)
    _number(additional_cost_scr, "Additional cost", MAX_VALUE)
    with localcontext(_COST_CONTEXT) as context:
        context.prec = 48
        return CostBalance(balance.pool, balance.quantity + quantity,
                           balance.value_scr + goods_value_scr + additional_cost_scr)


@dataclass(frozen=True)
class IssueCost:
    remaining: CostBalance
    quantity: Decimal
    value_scr: Decimal


def issue(balance: CostBalance, quantity: Decimal) -> IssueCost:
    _number(quantity, "Issued quantity", MAX_QUANTITY, positive=True)
    if quantity > balance.quantity:
        raise CostingError("Insufficient quantity in this cost pool")
    amount = _portion(balance.value_scr, quantity, balance.quantity)
    with localcontext(_COST_CONTEXT) as context:
        context.prec = 48
        return IssueCost(CostBalance(balance.pool, balance.quantity - quantity,
                                    balance.value_scr - amount), quantity, amount)


@dataclass(frozen=True)
class TransferValue:
    """Remaining in-transit quantity/value snapshot, not a persisted transfer ID."""
    source: CostPool
    destination: CostPool
    quantity: Decimal
    carried_value_scr: Decimal

    def __post_init__(self):
        if not isinstance(self.source, CostPool) or not isinstance(self.destination, CostPool):
            raise CostingError("Transfer requires source and destination cost pools")
        if self.source.org_id != self.destination.org_id or self.source.product_id != self.destination.product_id:
            raise CostingError("Transfer must retain organisation and product")
        if self.source.cost_pool_id == self.destination.cost_pool_id:
            raise CostingError("Same-pool location movement must not change its cost pool")
        _number(self.quantity, "Transfer quantity", MAX_QUANTITY)
        _number(self.carried_value_scr, "Carried value", MAX_VALUE)
        if self.quantity == 0 and self.carried_value_scr != 0:
            raise CostingError("Completed transfer cannot retain carried value")


@dataclass(frozen=True)
class TransferDispatch:
    source_remaining: CostBalance
    in_transit: TransferValue


def dispatch_transfer(source: CostBalance, destination: CostPool, quantity: Decimal) -> TransferDispatch:
    outgoing = issue(source, quantity)
    return TransferDispatch(outgoing.remaining,
        TransferValue(source.pool, destination, outgoing.quantity, outgoing.value_scr))


@dataclass(frozen=True)
class TransferReceipt:
    destination_balance: CostBalance
    in_transit_remaining: TransferValue
    carried_value_received_scr: Decimal
    additional_cost_scr: Decimal


def receive_transfer(destination: CostBalance, transit: TransferValue, quantity: Decimal,
                     additional_cost_scr: Decimal = ZERO) -> TransferReceipt:
    """Receive only delivered quantity. Additional costs apply to THIS receipt only.

    The caller allocates consignment-wide freight first and prevents repeat posting.
    An API must never accept these snapshots directly from an untrusted client.
    """
    if destination.pool != transit.destination:
        raise CostingError("Receipt does not match the destination cost pool/product")
    _number(quantity, "Delivered quantity", MAX_QUANTITY, positive=True)
    if quantity > transit.quantity:
        raise CostingError("Delivered quantity exceeds remaining in-transit stock")
    value = _portion(transit.carried_value_scr, quantity, transit.quantity)
    received = receive(destination, quantity, value, additional_cost_scr)
    with localcontext(_COST_CONTEXT) as context:
        context.prec = 48
        remaining = TransferValue(transit.source, transit.destination,
                                 transit.quantity - quantity, transit.carried_value_scr - value)
    return TransferReceipt(received, remaining, value, additional_cost_scr)


def allocate_additional_cost(total_scr: Decimal, bases: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Exact largest-remainder allocation; ties use stable line IDs, not input order.

    Caller chooses/approves a consistent basis (e.g. weight, volume or goods value).
    This function does not decide whether a cost is eligible for capitalization.
    """
    total = _number(total_scr, "Allocation total", MAX_VALUE)
    if not bases or len(bases) > 10000:
        raise CostingError("Allocation requires 1 to 10000 lines")
    for key, weight in bases.items():
        if not isinstance(key, str) or not key.strip():
            raise CostingError("Every allocation line needs a stable ID")
        _number(weight, "Allocation basis", MAX_VALUE)
    # Fractions avoid decimal-context rounding altering near-tied remainders.
    denominator = sum(Fraction(weight) for weight in bases.values())
    if denominator == 0:
        raise CostingError("At least one allocation basis must be positive")
    units = int(Fraction(total) / Fraction(QUANTUM))
    quotas = {key: units * Fraction(weight) / denominator for key, weight in bases.items()}
    allocations = {key: quota.numerator // quota.denominator for key, quota in quotas.items()}
    residue = units - sum(allocations.values())
    ranked = sorted(bases, key=lambda key: (-(quotas[key] - allocations[key]), key))
    for key in ranked[:residue]:
        allocations[key] += 1
    with localcontext(_COST_CONTEXT) as context:
        context.prec = 48
        return {key: (Decimal(allocations[key]) * QUANTUM).quantize(QUANTUM) for key in sorted(bases)}
