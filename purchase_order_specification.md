# Procurement Lock & Revision Specification

How a sourcing document is locked as it advances, how its contents are changed
after it has been sent out, and what happens when a vendor answers with something
other than what was asked.

Status as of 2026-10-14 (revised the same day, after the container-fill case): the lifecycle, the audit trail and the rollback mechanics
are built. The **policy** is not, and two different mechanisms are missing, not one:

- a **revision loop**, for when the buyer changes the request, and
- an **accept-deviation step at award**, for when a vendor answers it differently
  (a minimum order quantity, a pack multiple, a substitute, a partial supply).

Today the lock lands four stages earlier than this specification requires, is
enforced only in the browser, and offers no revision path; and the award silently
drops the vendor's quantity. Section 5 measures the code; sections 6 and 7 are the
design that closes the gaps.

---

## 1. The lifecycle

```
DRAFT -> CONFIRMED -> RFQ_SENT -> QUOTE_RECEIVED -> QUOTE_APPROVED -> PO_ISSUED -> PROFORMA
```

`LIFECYCLE_SEQUENCE` in `Routes/Orders/LifecycleService.py`. Forward moves are gated
by a checklist (`get_gate_checklist`); backward moves are classified `ROLLBACK` and
skip the gates, because a rollback exists precisely to correct what a gate passed.

**The lock point is `QUOTE_APPROVED`.** Before it, a document is a statement of what
the company wants and may be corrected. From it, the document is the basis of an
award, and changing it silently rewrites what a vendor was judged on.

## 2. Revision or deviation

A vendor saying "my minimum is 5, you asked for 3" is **not** a revision. The
dividing line is who is changing their mind.

> The buyer changes the request — that is a **revision**.
> A vendor answers it differently — that is a **deviation**, and it lives on the quote.

```
                                 +-- Deviation ----------------------------+
          vendor answers         |  lives on the quote line, and the award |
          differently ---------->|  copies it onto the purchase order      |
         /                       +-----------------------------------------+
a change                         +-- Top-up --------------------------------+
after the                        |  only raises already priced lines; the   |
RFQ is sent                  +-->|  award stands, the vendor reconfirms     |
         \                   |   +------------------------------------------+
          buyer changes -----+
          the request        |   +-- Revision ------------------------------+
                             +-->|  anything else the buyer changes: roll   |
                                 |  back with a reason, edit, re-send;      |
                                 |  open quotes are superseded              |
                                 +------------------------------------------+

Once child POs exist the change lands on the child, and the RFQ cannot roll
back until they are cancelled (section 7.5).
```

Only the third path moves the document. The first two leave it exactly as the
vendors received it, which is what keeps their quotes comparable.

If a vendor's minimum rewrote the RFQ, the other vendors would be answering a
different question from the one they were sent, and five vendors would mean five
rollbacks of a document that can hold only one quantity at a time. The RFQ stays
fixed so the quotes stay comparable.

| What happens | Raised by | Where it is recorded | Revision? |
| :--- | :--- | :--- | :--- |
| Minimum order quantity above the request (3 asked, 5 minimum) | vendor | `vendor_quote_items.quantity_quoted` | no |
| Pack or carton multiple (10 asked, sold in 12s) | vendor | `quantity_quoted` | no |
| Vendor can supply only part of the line | vendor | `availability = PARTIAL`, split award | no |
| Item out of stock or discontinued | vendor | `availability = OUT_OF_STOCK` | no — unless the buyer then changes the item for everyone |
| Vendor offers an equivalent instead | vendor | `is_substitute`, `original_item_id` | no |
| Vendor sends a corrected quote | vendor | a new quote; the old one superseded | no |
| Price validity lapses before the award | time | re-quote | no |
| Delivery date, consignee, internal notes | buyer | header fields, editable throughout | no |
| The quantity the company needs changed | buyer | RFQ line | **yes** |
| A line is added or dropped | buyer | RFQ line | **yes** |
| A specification changes what is being bought | buyer | RFQ line | **yes** |
| The container would ship part-empty | buyer | quantities raised on existing lines | **yes — top-up** (section 7.2) |
| A volume price break is within reach | buyer | quantities raised on existing lines | **yes — top-up**, price reconfirmed |
| Any of the above after the quote was approved | buyer | roll back from `QUOTE_APPROVED` first | **yes** |
| Any of the above after the PO was issued | buyer | change order | out of scope |

Every vendor-side row is already modelled. `vendor_quote_items` carries
`quantity_quoted`, `availability`, `is_substitute` and `original_item_id`, and
`VendorQuoteEntryModal` captures them. Nothing new is needed to **record** a
deviation; what is missing is what happens to it next (section 7).

## 3. What may change at each stage

| Stage | Line items | Quantities | Prices | How a change is made |
| :--- | :--- | :--- | :--- | :--- |
| `DRAFT` | add / remove | free | free | edited in place |
| `CONFIRMED` | add / remove | free | free | edited in place |
| `RFQ_SENT` | add / remove | free | n/a (no prices yet) | **revision** |
| `QUOTE_RECEIVED` | add / remove | free | vendor's, per quote | **revision**; quotes superseded |
| `QUOTE_APPROVED` | locked | locked | locked | roll back to `QUOTE_RECEIVED` first |
| `PO_ISSUED` | locked | locked | locked | change order only (not built) |
| `PROFORMA` | must match the PO | — | variance queue | variance approval |

Two rules carry the table:

1. **Nothing is locked because it was sent.** It is locked because a decision was
   taken on it. Sending an RFQ starts a conversation; approving a quote ends one.
2. **A change after sending is a new version, never an edit.** The vendors hold
   paper describing v1. v2 is a different request, and the system has to be able to
   say which one a quote answered.

## 4. What a revision must preserve

- The document the vendors received, exactly as they received it.
- Which version each quote was given against.
- Who revised it, when, and why.
- The vendor name as it stood on the document (`supplier_name_at_issue`), unchanged
  by the revision.

## 5. Current implementation, measured against the above

| Requirement | State | Where |
| :--- | :--- | :--- |
| Stage machine with gates | built | `LifecycleService.get_gate_checklist` |
| Rollback, with optimistic version check | built, unused by the UI | `LifecycleService.transition_stage` |
| Immutable snapshot per transition | built | `capture_po_snapshot`, `po_version_snapshots` |
| Line-item delta audit | built | `po_item_history` |
| Vendor deviations on a quote line | built: quantity, availability, substitute | `vendor_quote_items` |
| Quote supersession state | column exists, set on re-award only | `VendorQuote.status` |
| **Award carries the quoted quantity** | built on `feature/procurement-revision` | `_apply_quoted_line` |
| Split award into one PO per vendor | built, with lineage | `QuoteComparisonService.split_award` |
| Quantity split across vendors | built on the branch: `quantity` on the allocation | `split_award_rfq` |
| Child PO snapshotted at birth | built all along; the parent link was added on the branch | `split_award` |
| "Awarded" as a state of its own | the borrowed variance lock is gone; stage and the child guard carry it | `split_award_rfq` |
| Coverage of an RFQ across its children | **absent** | — |
| Container fill known before shipping | **absent** — volume computed only after packing | `order_packing_lists.total_cbm` |
| Dimensions on the masters | columns exist, **0 of 5,790 populated** | `products.length` / `width` / `height` |
| Lock at `QUOTE_APPROVED` | API correct on the branch; the screen is still per document | `OrderEntryPage.js:1259` |
| Lock enforced server-side | built on the branch | `_assert_lines_may_change` |
| Revision path in the UI | built on the branch | `POST /orders/{id}/revise`, Revise button |
| Permission to roll back | built on the branch: `Revise_RFQ` | `LifecycleRouter` |
| Minimum order quantity on the masters | columns exist, **0 of 3,723 populated** | `product_suppliers.min_order_qty` |

The three that matter most:

- **The award drops the quantity** (section 7). Found by testing the real case: 3
  requested, 5 the vendor's minimum.
- **The lock is cosmetic.** `PUT /orders/{order_id}` checks `Edit_RFQ` / `Edit_Order`
  and nothing about stage or `lifecycle_locked`. The read-only screen is the only
  thing stopping a line change on an approved document.
- **The screen is stricter than the policy.** An RFQ becomes read-only the moment it
  leaves `DRAFT`, with no way back, so the honest answer to "the quantity changed"
  is today "cancel it and raise another one" — which loses the history the snapshot
  tables were built to keep.

## 6. The revision loop

### 6.1 Flow

1. User opens a sent RFQ and presses **Revise**.
2. The system requires a reason, and refuses an empty one.
3. The document rolls back to the last editable stage (`CONFIRMED` from `RFQ_SENT`;
   `QUOTE_RECEIVED` stays put), capturing a `STAGE_ROLLBACK` snapshot carrying the
   reason.
4. Open quotes are superseded (section 8) and the stage version increments.
5. The user edits lines, then advances again. Re-sending is an ordinary `RFQ_SENT`
   transition, so `Send_RFQ` is required exactly as it was the first time.
6. The vendors are told what changed. The diff for that message comes from
   `diff_data` on the two snapshots, not from a human retyping it.

### 6.2 Server-side enforcement

`PUT /orders/{order_id}` gains a stage guard before it writes:

- `DRAFT`, `CONFIRMED` — header and lines both writable.
- `RFQ_SENT`, `QUOTE_RECEIVED` — header fields writable; **line items rejected**
  with `409`, naming Revise as the route.
- at or past `QUOTE_APPROVED`, or `lifecycle_locked` — lines rejected; a short
  allow-list of fields that are not part of the agreement (internal notes,
  attachments, expected dates) stays writable.

The guard lives beside the permission checks already in that function, so a client
that bypasses the UI gets the same answer as the UI.

### 6.3 Permission

A new `Revise_RFQ`, checked on any backward transition. Rolling back invalidates
vendor-facing work; it is not the same authority as editing a draft. Until the
permission exists in a role, the holder of `Approve_Quote` may revise, since that
role already decides what the company commits to.

## 7. Accepting a deviation at award

**The award copies the vendor's price and drops the vendor's quantity.** With 3
requested, 5 the vendor's minimum and $10 each:

- the quote totals `quantity_quoted × unit_price` = **$50** (`LifecycleRouter.py:276`);
- the award writes the price onto the PO line and recomputes the PO as
  `quantity_ordered × unit_price` = **$30** (`QuoteComparisonService.py:278`).

Nothing in the codebase writes `po_items.quantity_ordered` from a quote. The buyer
awards a quote for 5, the PO says 3, and the disagreement surfaces only when the
vendor ships or invoices five — at the proforma variance check or the goods
receipt, where it reads as the vendor's error. The same hole swallows a substitute:
`is_substitute` and `original_item_id` are captured and never carried onto the
awarded line.

The fix is an acceptance step, not a revision:

1. The comparison screen flags every line where the quote differs from the request
   (quantity, substitute, partial availability) and will not award silently past it.
2. Accepting copies the quoted quantity, and the substitute's identity, onto the PO
   line, and records the acceptance in `po_item_history`.
3. The line keeps both numbers: a new `po_items.quantity_requested` beside
   `quantity_ordered`, so the PO shows what was asked and what was agreed.
4. If the buyer would rather re-solicit every vendor at the new quantity than accept
   one vendor's minimum, that is the moment a **revision** is the right answer. The
   screen offers both.

### 7.2 Top-up: changes that improve the deal

Filling a container is as good a reason to change a sent document as a mistake is.
A part-empty container costs the same to ship as a full one, so topping the order
up is the buyer doing their job, not correcting a fault, and it needs a path of its
own rather than being squeezed through the door built for errors.

These changes land **late** by nature. The gap is visible only once quantities,
volumes and prices are known: after the quotes are in, usually after the award,
sometimes while loading is being planned. That is exactly where the lock is
tightest, which makes "cancel and raise another one" the worst available answer —
it discards an awarded price in order to buy goods the vendor is glad to sell.

They also have a particular shape: **increase-only, on lines a vendor has already
priced.** That earns a lighter path than a full re-solicitation.

A **top-up revision**:

1. raises quantities on existing lines, or adds a line the awarded vendor already
   quoted — it may not drop a line, change a specification or introduce an item
   nobody priced, each of which is an ordinary revision;
2. leaves the award standing and the quotes in place;
3. sets `vendor_quotes.reconfirmation_required`, because volume cuts both ways: the
   vendor is asked whether the price holds at the larger quantity, and the flag
   clears when they answer;
4. supersedes the quote and re-decides that line only if the vendor re-prices;
5. records the reason like any revision, so "container fill" is visible in the
   history rather than looking like an unexplained quantity change.

This gives section 8 its missing test. **Supersession follows price, not
paperwork:** the question is whether the change alters what the vendor had to
price. A delivery date or a corrected wording does not. A quantity does, which is
why a top-up asks instead of assuming.

### 7.3 The system cannot see the gap

It cannot tell anyone the container is 72 percent full. `length`, `width`, `height`,
`weight_per_unit`, `units_per_box`, `est_qty_20ft` and `est_qty_40hc` all exist on
`products`, and on staging **0 of 5,790 rows carry any of them**. Volume is computed
only after packing, as `order_packing_lists.total_cbm`, far too late to act on.

So the decision is made in someone's head or a spreadsheet and the application can
only record the outcome. Two things change that:

1. **Estimated volume and weight on the order**, summed from the line dimensions and
   shown as a fill bar against the intended container from `QUOTE_RECEIVED` onward.
   The arithmetic is trivial; the inputs are the problem.
2. **Dimensions captured once and shared.** The group product dictionary already
   carries `length`, `width`, `height`, `weight_per_unit` and `dimension_unit`, so
   one company measuring a product serves every company that adopts it.

After the PO is issued a top-up becomes a change order. Worth noting for when that
work starts: a quantity increase on an existing line, same vendor, same price, is
the commonest and least risky change order there is, and is the one to build first.

### 7.4 Feeding the masters

The minimum could have been known before the RFQ went out. `product_suppliers.min_order_qty`
and `products.min_quantity_order` both exist, and on staging **0 of 3,723 supplier
links and 0 of 5,790 products carry one** — nothing populates them and no order
screen reads them.

Accepting a deviation writes the minimum back to the supplier link, and the order
entry screen warns when a line falls below a known minimum. That turns a surprise
that costs a quoting round into master data captured once.

## 7.5 After the award: one RFQ, several POs

A split award turns one RFQ into a PO per vendor. It is built and in use: in the
dev data `RFQ-2026-0005` (2 lines, 230 units, $16,965) became `PO-2026-0005A`
(150 units, vendor 179, $5,925) and `PO-2026-0005B` (80 units, vendor 184,
$11,040). Children carry `parent_rfq_id`, `split_index` and, per line,
`source_rfq_item_id`, so the lineage exists.

What is missing is the rule about **which document is live**. Once children exist
the RFQ is a source record, not a working document: editing it changes nothing
downstream, because the children are copies, while making the history claim
something that never reached a vendor.

| A change after the award | Lands on |
| :--- | :--- |
| Quantity, price or dates for one vendor | that child PO — a top-up or a change order |
| A line nobody awarded yet | the RFQ, re-sent for that line only |
| The whole request was wrong | roll the RFQ back — only after its children are cancelled |

Three rules follow:

1. **The lock is per line, not per document.** An awarded line is frozen on the
   RFQ; an unawarded line stays live and can be revised and re-sent. Today the lock
   is all-or-nothing, so a partly awarded RFQ freezes lines nobody has quoted on.
2. **A rollback is refused while children live.** Two documents claiming the same
   line is corruption, not a revision. The guard names the children and offers to
   cancel them first.
3. **Each child's birth snapshot is descended from the award.** The snapshot
   itself always existed; what was missing was `parent_snapshot_id`, so the chain
   stopped at the child rather than reading end to end: RFQ v3 -> PO-A v1 -> PO-A v2.

### 7.6 The coverage view

Once a top-up lands on one child, the RFQ total stops equalling the sum of its
children — correctly, and visibly rather than quietly. The RFQ grows a per-line
reconciliation: **requested, awarded, ordered, received** across every child, each
difference named ("+20 on PO-A, container fill"). It is a read-only view over data
that already exists, and it is what makes a multi-PO award manageable at all.

### 7.7 Two defects found here

**A quantity could not be split across vendors** (fixed on the branch). The
allocation payload was `{po_item_id, quote_id, unit_price}` — no quantity — and
each child copied `quantity_ordered` in full, so awarding one line of 100 as 60/40
ordered 100 from each. An allocation now carries an optional `quantity`, the parts
are added up and may not exceed the line, and a child records its own share as its
`quantity_requested`. Omitting it still means the whole line, which is how every
award worked before.

**The award borrowed the variance lock** (fixed on the branch). `split_award` set
`rfq.lifecycle_locked = True`, but that flag means "unresolved price variance"
everywhere else: `transition_stage` refused with that message, `approve_proforma_variance`
cleared it, and the order screen went looking for variance details that never
existed. It is no longer set: an award is protected by the rollback guard and the
stage guard, which say what they mean.

## 8. Quotes against a revised document

A quote answers one version of a request. When the request changes, that quote is
evidence of what a vendor offered, not an offer against the new document.

**Recommendation: keep and supersede, never delete.** On revision, every quote in
`PENDING` moves to `SUPERSEDED`; the comparison screen excludes superseded quotes
from scoring while still showing them, labelled with the version they answered.
`VendorQuote.status` already carries `SUPERSEDED` and `QuoteComparisonService`
already sets it on re-award, so this reuses a path the system has.

The alternative, voiding the quotes outright, loses the vendor's prior position —
the one thing the buyer wants when the revision is small.

**Open decision for the business:** whether a revision touching only
non-commercial fields (a delivery date, a description's wording) should supersede
quotes at all, or leave them live. Superseding everything is the safe default and
is what this document specifies until that is decided. Deciding it the other way
has its test in section 7.2 — does the change alter what the vendor had to price?
— and needs only the business decision to adopt it.

## 9. Data model

No new tables. Two columns:

- `po_items.quantity_requested` — what the RFQ asked for, kept beside
  `quantity_ordered` once a deviation or a top-up is accepted.
- `vendor_quotes.reconfirmation_required` — set by a top-up, cleared when the vendor
  confirms the price holds at the larger quantity.
- `po_items.quantity_awarded` — how much of a line went to this vendor, so a line
  can be split across children and the remainder stays visible.
- `purchase_orders.quoted_against_version` — written when an RFQ is sent and copied
  onto each quote as it is recorded, so a quote states its own version rather than
  having it inferred from timestamps.

Everything else exists:

- `po_version_snapshots` — the full document per version, with `transition_type`,
  `change_summary`, `diff_data` and `parent_snapshot_id` lineage. A revision is a
  `STAGE_ROLLBACK` row followed, on re-send, by a `STAGE_ADVANCE` row.
- `po_item_history` — field-level deltas, including an accepted deviation.
- `vendor_quote_items` — the deviation itself.
- `purchase_orders.lifecycle_version` / `stage_version` — the optimistic lock.
- `vendor_quotes.status` — `SUPERSEDED`.

## 10. User interface

- **Revise** button on a sent RFQ, for holders of the revision permission, beside
  the stage badge rather than inside the locked form.
- The lock banner changes from a dead end into a route: it names the stage, says
  what can still change, and offers Revise where the stage allows it.
- `isSourcingLocked` is replaced by a stage-derived rule shared with the backend's
  guard, so the screen and the API cannot disagree.
- The comparison screen marks deviating lines, requires each to be accepted or
  rejected before an award, and shows the requested quantity beside the quoted one.
- Superseded quotes stay visible, greyed, labelled with their version, and excluded
  from ranking.
- Order entry warns when a line falls below a known minimum order quantity.
- A fill bar on the order from `QUOTE_RECEIVED` onward: estimated volume and weight
  against the intended container, with the shortfall named in units of the largest
  line, so a top-up decision needs no spreadsheet.

## 10.1 What is built, and where

On `feature/procurement-revision`, not yet merged to `standalone-main`:

1. The award carries the vendor's quantity and substitute, behind an explicit
   acceptance (`409` listing the differences, then `accept_deviations`), with
   `po_items.quantity_requested` keeping the request.
2. `PUT /orders/{order_id}` refuses a line change once a document has been sent,
   and on an awarded line outright; header fields stay writable.
3. `POST /orders/{po_id}/revise` reopens a sent RFQ, demanding a reason,
   superseding its open quotes, under `Revise_RFQ`.
4. A rollback is refused while child POs are live; children are snapshotted at
   birth.
5. The screens: a Revise button and a banner that names the route, and a
   comparison screen that shows the deviations for acceptance.

Still to build: the top-up path with price reconfirmation (7.2), the coverage
view (7.6), quantity on the allocation (7.7), minimum order quantity written back
to the masters (7.4), dimensions and the fill bar (7.3), and the per-line lock in
the screens.

Two defects were found while building this and are fixed on the branch: a quote
line was matched by `item_code`, which matches every line of a catalogue that
leaves codes blank, so line 2 took line 1's answer; and the award button in the
comparison screen passed its click handler bare, which would have delivered the
click event as `accept_deviations`.

## 11. Build order

1. **Award carries the deviation** (section 7, steps 1–3). It is the only item on
   this list that is producing wrong purchase orders today.
2. Stage guard on `PUT /orders/{order_id}` (section 6.2), so the lock is real.
3. Revise in the UI, with reason and permission (sections 6.1, 6.3).
4. Quote supersession on revision (section 8).
5. Minimum order quantity written back to the masters and read at entry (7.4).
6. Top-up revision with price reconfirmation (7.2).
7. Dimensions captured, and the fill bar that depends on them (7.3). Last, because
   it is worth nothing until the dimensions exist, and most useful once the
   dictionary is spreading them.

Alongside, in the multi-PO area (7.5–7.7), in this order:

1. Refuse a rollback while children live. One guard, and it prevents corruption.
2. Snapshot each child at birth. Cheap, and every later change depends on it.
3. Give "awarded" its own state instead of the variance flag.
4. Quantity on the allocation, so a line can genuinely be split.
5. The coverage view.

## 12. Out of scope

- **Change orders after `PO_ISSUED`.** A PO is a contract; amending one is a
  document of its own, with its own numbering and vendor acknowledgement. It is
  named here only so the lock has somewhere to point.
- **Vendor-side editing.** Vendors proposing substitutes themselves needs a vendor
  portal. Today a substitute is recorded by the buyer on the vendor's quote.
