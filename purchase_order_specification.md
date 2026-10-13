# Procurement Lock & Revision Specification

How a sourcing document is locked as it advances, how its contents are changed
after it has been sent out, and what happens when a vendor answers with something
other than what was asked.

Status as of 2026-10-14: the lifecycle, the audit trail and the rollback mechanics
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
| **Award carries the quoted quantity** | **absent: price copied, quantity dropped** | `QuoteComparisonService.py:278` |
| Lock at `QUOTE_APPROVED` | **wrong stage** — locks everything past `DRAFT` | `OrderEntryPage.js:1259` |
| Lock enforced server-side | **absent** — stage is never checked on write | `OrderRouter.py:1152` |
| Revision path in the UI | **absent** — the stepper only advances | `LifecycleStepper.js` |
| Permission to roll back | **absent** — only forward moves are guarded | `LifecycleRouter.py:187` |
| Minimum order quantity on the masters | columns exist, **0 rows populated** | `product_suppliers.min_order_qty` |

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

### 7.1 Feeding the masters

The minimum could have been known before the RFQ went out. `product_suppliers.min_order_qty`
and `products.min_quantity_order` both exist, and on staging **0 of 3,723 supplier
links and 0 of 5,790 products carry one** — nothing populates them and no order
screen reads them.

Accepting a deviation writes the minimum back to the supplier link, and the order
entry screen warns when a line falls below a known minimum. That turns a surprise
that costs a quoting round into master data captured once.

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
needs a rule for which fields are commercial, which is a business rule, not a
technical one.

## 9. Data model

No new tables. Two columns:

- `po_items.quantity_requested` — what the RFQ asked for, kept beside
  `quantity_ordered` once a deviation is accepted.
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

## 11. Build order

1. **Award carries the deviation** (section 7, steps 1–3). It is the only item on
   this list that is producing wrong purchase orders today.
2. Stage guard on `PUT /orders/{order_id}` (section 6.2), so the lock is real.
3. Revise in the UI, with reason and permission (sections 6.1, 6.3).
4. Quote supersession on revision (section 8).
5. Minimum order quantity written back to the masters and read at entry (7.1).

## 12. Out of scope

- **Change orders after `PO_ISSUED`.** A PO is a contract; amending one is a
  document of its own, with its own numbering and vendor acknowledgement. It is
  named here only so the lock has somewhere to point.
- **Vendor-side editing.** Vendors proposing substitutes themselves needs a vendor
  portal. Today a substitute is recorded by the buyer on the vendor's quote.
