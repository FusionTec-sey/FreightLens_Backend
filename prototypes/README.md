# POS C01 executable design experiment

This folder is not imported by the application and contains no production API,
database migration, durable queue, accounting export or stock writer.

Run `python -m prototypes.pos_offline_contract` for the numerical demonstration;
run `python -m pytest tests/test_pos_offline_contract.py -q` for contract checks.

## What the experiment establishes

One synthetic organisation owns one product in two independent stock authorities,
named Mahé and Praslin. Each holds 100 units valued at SCR 10 per unit. Mahé
receives 100 additional units at SCR 20; disconnected Praslin issues 50 units.
Selling price and VAT do not participate in these inventory-cost calculations.

| Cost policy and approved order | Issue cost (SCR) | Remaining value (SCR) |
| --- | ---: | ---: |
| Shared average, receipt before issue | 666.666667 | 3333.333333 |
| Separate authority averages | 500.000000 | 3500.000000 |
| Shared average, issue before receipt | 500.000000 | 3500.000000 |

All cases leave 250 physical units; issue cost plus remaining value equals SCR
4,000. Local Praslin cost of SCR 500 is provisional under the first policy. A
linked SCR 166.666667 cost adjustment would be needed, without changing the
customer price, payment, or issued quantity. The experiment computes the delta;
it does not post an adjustment or claim an approved accounting treatment.

The third row matters: delivery order must not silently become accounting order.
This prototype takes an explicit close manifest listing the approved total event
order. It verifies complete per-authority sequence watermarks and preserves each
authority's local order. Every permutation of network delivery produces the same
cost result for that same manifest. It does NOT prove that device clocks are
accurate or decide how the business approves a final manifest.

## Failure contract exercised

| Interruption or conflict | Modeled result |
| --- | --- |
| Before local commit | Neither balance nor outbox changes; retry applies once |
| After local commit, response lost | Operation ID retry returns the same event |
| Cloud accepts, acknowledgment lost | Resend is deduplicated; local outbox remains pending until acknowledged |
| Sequence 2 arrives before 1 | Inbox buffers it; projection waits for a contiguous prefix |
| Same operation, changed payload | Rejected without another movement |
| Different operation, reused sequence | Rejected |
| Wrong tenant or node identity | Rejected against the synthetic authenticated authority |
| Local shortage despite remote stock | Rejected |
| Finalization with a missing authority event | Rejected against the supplied close watermark |

Acknowledgment means modeled inbox acceptance, not inventory cost finalization.
Records remain available for audit; acknowledgment does not delete events.

## Proposed production contract, not implemented

- Each physical location has exactly one active write authority. Online tablets
  and mobile-data users must reach that authority; cloud reachability alone does
  not authorize a second writer for an offline store's stock.
- A durable database transaction must combine stock, document, payment allocation
  and outbox. The in-memory tuple update here is NOT evidence of crash durability.
- Node enrollment, tenant-scoped credentials, authority epochs/fencing, durable
  deduplication keys, projection versions and a recoverable inbox are still needed.
- No final costing close while an included authority has an unverified watermark.
  Device timestamps alone are not authoritative. Proposed close manifests should
  record policy/version, opening checkpoint, ordered event IDs and content hashes.
- Once finalized, corrections must be new linked events and adjustment batches,
  not replacement of historical invoices, issues or exports. Late/backdated events,
  provisional receipt costs and reopen controls require a separate tested design.
- Shared customer credit needs a different hold/commit/cancel protocol. It must not
  be treated as an independently spendable balance on each store's replica.
- Six-decimal intermediate amounts and rounding are illustrative, not the final
  financial precision policy. Transfers, reservations, returns, taxes, serials,
  discounts, multiple products and independently owned entities are not modeled.

## Decision gate

**Subsequently resolved:** the owner approved branch/product weighted-average
costs with independent store price lists on 2026-10-02. The discussion below is
the decision history, not an unanswered request. Durable authority/close rules,
legal entity mapping and accounts' cost eligibility controls remain open.

The owner's subsequent clarification says imports arrive at the main warehouse,
then distribution adds inter-island costs and Praslin has different selling prices.
Selling-price lists and inventory valuation are separate policies. An additional
illustration transfers 100 of 200 units costing SCR10 each, with SCR200 approved
freight: main warehouse retains value SCR1,000, Praslin receives value SCR1,200
(SCR12/unit), consolidated value SCR2,200. This is cost carry-forward plus freight,
not an interbranch sale/profit. Eligibility of particular costs and actual legal
entity ownership still need accounts confirmation. No transfer posting is built.

Based on that clarification, branch/location cost pools with separate price lists
are the revised recommendation to confirm. Different selling prices alone do not
authorize that accounting choice. Physical bin counts should not create separate
cost pools, and cost pools must not be coupled blindly to server/node identities.
The synthetic example uses one branch per authority only for demonstration.

The [IFRS Foundation's IAS 2 overview](https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/)
supports including eligible costs of bringing inventory to its location and
condition, and weighted-average costing for interchangeable goods. It does not
by itself select this business's cost pools, approve every distribution charge,
or establish the applicable reporting framework. Accounts must confirm those.

Preserve the earlier proposed organisation/product average with provisional
offline costs and central finalization, or explicitly approve independent
authority cost pools. Owner/accounts must confirm before the C10 valuation schema
is frozen. Also resolve close ordering, actual legal entities and authority
topology. C01 remains partial and no pilot readiness is claimed.
