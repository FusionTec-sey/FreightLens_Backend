"""Exact base-unit quantity contracts for future ledger-backed reads and posting.

These immutable snapshots do not authorize a sale or change stock. Load them
from scoped, locked domain records; never trust client-supplied balance totals.
Damaged and quarantined quantities are disjoint subsets of physical on-hand.
Pickup planning is intentionally absent: a plan is not a stock commitment.
"""
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

QUANTITY_POLICY_VERSION = "physical-quantity-v1"
_CONTEXT = Context(prec=48)
_QUANTUM = Decimal("0.000001")
_MAX = Decimal("999999999999.999999")
ZERO = Decimal("0.000000")


def _quantity(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Quantity must be a finite Decimal")
    if value < 0 or value > _MAX:
        raise ValueError("Quantity is outside the supported range")
    with localcontext(_CONTEXT):
        if value != value.quantize(_QUANTUM):
            raise ValueError("Quantity has more than six decimal places")


def _subtract(total: Decimal, *parts: Decimal) -> Decimal:
    with localcontext(_CONTEXT):
        return (total - sum(parts, ZERO)).quantize(_QUANTUM)


@dataclass(frozen=True)
class QuantityBreakdown:
    on_hand: Decimal
    reserved: Decimal = ZERO
    damaged: Decimal = ZERO
    quarantined: Decimal = ZERO

    def __post_init__(self):
        for value in (self.on_hand, self.reserved, self.damaged, self.quarantined):
            _quantity(value)
        if self.available < 0:
            raise ValueError("Reservations and unavailable conditions exceed physical stock")

    @property
    def available(self) -> Decimal:
        return _subtract(self.on_hand, self.reserved, self.damaged, self.quarantined)

    def reserve(self, quantity: Decimal) -> "QuantityBreakdown":
        _quantity(quantity)
        if quantity <= 0 or quantity > self.available:
            raise ValueError("Insufficient available stock for a positive reservation")
        with localcontext(_CONTEXT):
            return QuantityBreakdown(self.on_hand, self.reserved + quantity, self.damaged, self.quarantined)

    def release(self, quantity: Decimal) -> "QuantityBreakdown":
        """Caller must separately check reservation ownership and release approval."""
        _quantity(quantity)
        if quantity <= 0 or quantity > self.reserved:
            raise ValueError("Release must not exceed reserved quantity")
        return QuantityBreakdown(self.on_hand, _subtract(self.reserved, quantity), self.damaged, self.quarantined)

    def handover_reserved(self, quantity: Decimal) -> "QuantityBreakdown":
        """Caller must also validate the particular reservation and invoice line."""
        _quantity(quantity)
        if quantity <= 0 or quantity > self.reserved:
            raise ValueError("Handover must consume a positive reserved quantity")
        return QuantityBreakdown(_subtract(self.on_hand, quantity),
                                 _subtract(self.reserved, quantity), self.damaged, self.quarantined)


@dataclass(frozen=True)
class LineFulfillment:
    """One original invoice line, never an aggregate grouped only by product ID.

Returns do not reopen pickup entitlement. Replacement goods need their own
approved document. Pending returns prevent duplicate claims before approval.
"""
    invoice_line_id: str
    sold: Decimal
    handed_over: Decimal = ZERO
    reserved: Decimal = ZERO
    cancelled_uncollected: Decimal = ZERO
    returned: Decimal = ZERO
    pending_return: Decimal = ZERO

    def __post_init__(self):
        if not isinstance(self.invoice_line_id, str) or not self.invoice_line_id.strip():
            raise ValueError("Original invoice line identity is required")
        for value in (self.sold, self.handed_over, self.reserved, self.cancelled_uncollected,
                      self.returned, self.pending_return):
            _quantity(value)
        if self.outstanding_collection < 0:
            raise ValueError("Handover and cancellation exceed the original sale line")
        if self.reserved > self.outstanding_collection:
            raise ValueError("Reservation exceeds outstanding collection")
        if self.returnable < 0:
            raise ValueError("Previous and pending returns exceed physical handover")

    @property
    def outstanding_collection(self) -> Decimal:
        return _subtract(self.sold, self.cancelled_uncollected, self.handed_over)

    @property
    def unallocated(self) -> Decimal:
        return _subtract(self.outstanding_collection, self.reserved)

    @property
    def returnable(self) -> Decimal:
        return _subtract(self.handed_over, self.returned, self.pending_return)
