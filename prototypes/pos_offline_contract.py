"""C01 executable design experiment, NOT a production inventory service.

One tenant/product, synthetic store authorities, in-memory atomic transitions.
No persistence, authentication, network transport, tax, or customer-money claims.
Finalization needs an explicitly supplied complete, ordered close manifest;
arrival order and device clocks are deliberately not accounting policy.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext

SCALE = Decimal("0.000001")


@dataclass(frozen=True)
class Event:
    org_id: int
    node: str
    sequence: int
    operation: str
    kind: str
    quantity: Decimal
    unit_cost: Decimal | None = None

    def __post_init__(self):
        if self.org_id <= 0 or not self.node or not self.operation or self.sequence <= 0:
            raise ValueError("Invalid event identity")
        if self.kind not in {"receipt", "issue"}:
            raise ValueError("Unsupported movement")
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("Quantity must be a positive finite Decimal")
        if self.kind == "receipt":
            if not isinstance(self.unit_cost, Decimal) or not self.unit_cost.is_finite() or self.unit_cost < 0:
                raise ValueError("Receipt needs a nonnegative finite Decimal cost")
        elif self.unit_cost is not None:
            raise ValueError("Issue cost must be derived, not supplied")

    @property
    def key(self):
        return self.node, self.operation


class Store:
    """Stock and immutable outbox are one modeled transition, not separate writes."""
    def __init__(self, org_id, node, opening_quantity):
        self.org_id, self.node = org_id, node
        self.quantity = opening_quantity
        self.events = ()
        self.acknowledged = frozenset()

    def post(self, operation, kind, quantity, unit_cost=None, fail_at=None):
        previous = next((event for event in self.events if event.operation == operation), None)
        candidate = Event(self.org_id, self.node,
            previous.sequence if previous else len(self.events) + 1,
            operation, kind, quantity, unit_cost)
        if previous:
            if previous != candidate:
                raise ValueError("Operation ID reused with changed payload")
            return previous
        balance = self.quantity + (quantity if kind == "receipt" else -quantity)
        if balance < 0:
            raise ValueError("Insufficient stock at this store")
        if fail_at == "before_commit":
            raise RuntimeError("Interrupted before local commit")
        self.quantity, self.events = balance, self.events + (candidate,)
        if fail_at == "after_commit":
            raise RuntimeError("Response lost after local commit")
        return candidate

    @property
    def pending(self):
        return tuple(event for event in self.events if event.key not in self.acknowledged)

    def acknowledge(self, key):
        if key not in {event.key for event in self.events}:
            raise ValueError("Unknown acknowledgment")
        self.acknowledged = self.acknowledged | {key}


class Cloud:
    """Deduplicate and apply each authority's contiguous prefix; buffer gaps."""
    def __init__(self, org_id, opening_quantities):
        self.org_id = org_id
        self.quantities = dict(opening_quantities)
        self.sequences = {node: 0 for node in opening_quantities}
        self.inbox = {}

    def receive(self, event, authenticated_node):
        if event.org_id != self.org_id or event.node != authenticated_node or event.node not in self.quantities:
            raise ValueError("Wrong tenant or authority")
        old = self.inbox.get(event.key)
        if old is not None:
            if old != event:
                raise ValueError("Conflicting operation replay")
            return event.key
        if any(row.node == event.node and row.sequence == event.sequence for row in self.inbox.values()):
            raise ValueError("Authority sequence reused")
        inbox = {**self.inbox, event.key: event}
        sequence, quantity = self.sequences[event.node], self.quantities[event.node]
        by_sequence = {row.sequence: row for row in inbox.values() if row.node == event.node}
        while sequence + 1 in by_sequence:
            row = by_sequence[sequence + 1]
            quantity += row.quantity if row.kind == "receipt" else -row.quantity
            if quantity < 0:
                raise ValueError("Authority stream would overdraw stock")
            sequence += 1
        self.inbox = inbox
        self.sequences[event.node], self.quantities[event.node] = sequence, quantity
        # Acknowledges modeled inbox acceptance, not cost finalization.
        return event.key


def finalize(events, openings, manifest, watermarks, policy):
    """Pure replay of an explicitly approved closed set; no historical rewrites.

openings maps node -> (quantity, unit cost). Six-place amounts are experimental.
The caller must supply the trusted close watermarks; this is not close discovery.
"""
    if policy not in {"organisation", "authority"}:
        raise ValueError("Unknown valuation policy")
    if set(openings) != set(watermarks) or any(mark < 0 for mark in watermarks.values()):
        raise ValueError("Every authority needs a close watermark")
    rows = {}
    for event in events:
        if event.key in rows and rows[event.key] != event:
            raise ValueError("Conflicting event")
        rows[event.key] = event
    if len({event.org_id for event in rows.values()}) > 1:
        raise ValueError("Never pool separate organisations")
    if len(manifest) != len(set(manifest)) or set(manifest) != set(rows):
        raise ValueError("Close manifest must contain every event exactly once")
    if any(event.node not in openings for event in rows.values()):
        raise ValueError("Unknown authority")
    for node, watermark in watermarks.items():
        sequences = [rows[key].sequence for key in manifest if rows[key].node == node]
        if sequences != list(range(1, watermark + 1)):
            raise ValueError("Missing, duplicated, or reordered authority sequence")
    pools = {}
    physical = {node: quantity for node, (quantity, _) in openings.items()}
    with localcontext() as context:
        context.prec = 28
        for node, (quantity, cost) in openings.items():
            if not quantity.is_finite() or not cost.is_finite() or quantity < 0 or cost < 0:
                raise ValueError("Invalid opening")
            pool = "all" if policy == "organisation" else node
            qty, value = pools.get(pool, (Decimal(0), Decimal(0)))
            pools[pool] = qty + quantity, value + quantity * cost
        issues = {}
        for key in manifest:
            event = rows[key]
            pool = "all" if policy == "organisation" else event.node
            qty, value = pools[pool]
            if event.kind == "receipt":
                physical[event.node] += event.quantity
                pools[pool] = qty + event.quantity, value + event.quantity * event.unit_cost
            else:
                if event.quantity > physical[event.node] or event.quantity > qty:
                    raise ValueError("Sale cannot use another store's stock")
                physical[event.node] -= event.quantity
                amount = value if event.quantity == qty else (value * event.quantity / qty).quantize(SCALE)
                issues[key] = amount
                pools[pool] = qty - event.quantity, value - amount
        return {"issue_costs": issues, "closing_quantity": sum(physical.values()),
                "closing_value": sum(value for _, value in pools.values())}


def example():
    openings = {"mahe": (Decimal(100), Decimal(10)), "praslin": (Decimal(100), Decimal(10))}
    mahe, praslin = Store(1, "mahe", Decimal(100)), Store(1, "praslin", Decimal(100))
    receipt = mahe.post("receipt-1", "receipt", Decimal(100), Decimal(20))
    issue = praslin.post("sale-1", "issue", Decimal(50))
    events = [receipt, issue]
    manifest = [receipt.key, issue.key]
    watermarks = {"mahe": 1, "praslin": 1}
    provisional = Decimal(500)
    global_result = finalize(events, openings, manifest, watermarks, "organisation")
    local_result = finalize(events, openings, manifest, watermarks, "authority")
    sale_first = finalize(events, openings, list(reversed(manifest)), watermarks, "organisation")
    return {"provisional_issue_cost": provisional, "global_receipt_first": global_result,
        "authority_pools": local_result, "global_sale_first": sale_first,
        "linked_cost_adjustment": global_result["issue_costs"][issue.key] - provisional}


def transfer_cost_example():
    """Illustrative allocation only, not transfer posting or cost eligibility policy.

Same legal organisation: 200 units at SCR10 in the main warehouse; send100
to Praslin with SCR200 of approved additional freight. No interbranch profit.
"""
    opening_quantity, opening_value = Decimal(200), Decimal(2000)
    moved, freight = Decimal(100), Decimal(200)
    carried_value = opening_value * moved / opening_quantity
    destination_value = carried_value + freight
    return {"main_warehouse_remaining_quantity": opening_quantity - moved,
        "main_warehouse_remaining_value": opening_value - carried_value,
        "praslin_received_quantity": moved,
        "praslin_received_value": destination_value,
        "praslin_unit_cost": destination_value / moved,
        "consolidated_stock_value": opening_value + freight}


if __name__ == "__main__":
    for label, result in example().items():
        print(label, result)
    print("branch_transfer_cost_example", transfer_cost_example())
