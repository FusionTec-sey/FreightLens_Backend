# Procurement Lock & Revision Specification

How a sourcing document is locked as it advances, and how its contents are changed
after it has been sent out.

Status as of 2026-10-13: the lifecycle, the audit trail and the rollback mechanics
are built. The **policy** is not. The lock currently lands four stages earlier than
this specification requires, it is enforced only in the browser, and no revision
path is exposed, so a requirement that changes after an RFQ is sent cannot be
corrected through the application at all. Section 4 lists the gaps against the
code; section 5 is the design that closes them.

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

## 2. What may change at each stage

| Stage | Line items | Quantities | Prices | How a change is made |
| :--- | :--- | :--- | :--- | :--- |
| `DRAFT` | add / remove | free | free | edited in place |
| `CONFIRMED` | add / remove | free | free | edited in place |
| `RFQ_SENT` | add / remove | free | n/a (no prices yet) | **revision** (section 5) |
| `QUOTE_RECEIVED` | add / remove | free | vendor's, per quote | **revision**, quotes superseded |
| `QUOTE_APPROVED` | locked | locked | locked | roll back to `QUOTE_RECEIVED` first |
| `PO_ISSUED` | locked | locked | locked | change order only (not built) |
| `PROFORMA` | must match the PO | — | variance queue | variance approval |

Two rules carry the table:

1. **Nothing is locked because it was sent.** It is locked because a decision was
   taken on it. Sending an RFQ starts a conversation; approving a quote ends one.
2. **A change after sending is a new version, never an edit.** The vendors hold
   paper describing v1. v2 is a different request, and the system has to be able to
   say which one a quote answered.

## 3. What a revision must preserve

- The document the vendors received, exactly as they received it.
- Which version each quote was given against.
- Who revised it, when, and why.
- The vendor name as it stood on the document (`supplier_name_at_issue`), unchanged
  by the revision.

## 4. Current implementation, measured against the above

| Requirement | State | Where |
| :--- | :--- | :--- |
| Stage machine with gates | built | `LifecycleService.get_gate_checklist` |
| Rollback, with optimistic version check | built, unused by the UI | `LifecycleService.transition_stage` |
| Immutable snapshot per transition | built (`STAGE_ADVANCE` / `STAGE_ROLLBACK`) | `capture_po_snapshot`, `po_version_snapshots` |
| Line-item delta audit | built | `po_item_history` |
| Quote supersession state | column exists, set on re-award only | `VendorQuote.status = 'SUPERSEDED'` |
| Lock at `QUOTE_APPROVED` | **wrong stage** — locks everything past `DRAFT` | `OrderEntryPage.js:1259` `isSourcingLocked` |
| Lock enforced server-side | **absent** — stage is never checked on write | `OrderRouter.py:1152` `PUT /orders/{order_id}` |
| Revision path in the UI | **absent** — the stepper only advances | `LifecycleStepper.js` `handleAdvance` |
| Permission to roll back | **absent** — only forward moves are guarded | `LifecycleRouter.py:187` |
| Reason recorded on rollback | optional free-text `comment` | same |

The two that matter most:

- **The lock is cosmetic.** `PUT /orders/{order_id}` checks `Edit_RFQ` / `Edit_Order`
  and nothing about stage or `lifecycle_locked`. The read-only screen is the only
  thing stopping a line change on an approved document.
- **The screen is stricter than the policy.** An RFQ becomes read-only the moment it
  leaves `DRAFT`, with no way back, so the honest answer to "the quantity changed"
  is today "cancel it and raise another one" — which loses the history the snapshot
  tables were built to keep.

## 5. The revision loop

### 5.1 Flow

1. User opens a sent RFQ and presses **Revise**.
2. The system requires a reason, and refuses an empty one.
3. The document rolls back to the last editable stage (`CONFIRMED` from `RFQ_SENT`;
   `QUOTE_RECEIVED` stays put), capturing a `STAGE_ROLLBACK` snapshot carrying the
   reason.
4. Open quotes are superseded (section 6) and the stage version increments.
5. The user edits lines, then advances again. Re-sending is an ordinary `RFQ_SENT`
   transition, so `Send_RFQ` is required exactly as it was the first time.
6. The vendors are told what changed. The diff for that message comes from
   `diff_data` on the two snapshots, not from a human retyping it.

### 5.2 Server-side enforcement

`PUT /orders/{order_id}` gains a stage guard before it writes:

- `DRAFT`, `CONFIRMED` — header and lines both writable.
- `RFQ_SENT`, `QUOTE_RECEIVED` — header fields writable; **line items rejected**
  with `409`, naming Revise as the route.
- at or past `QUOTE_APPROVED`, or `lifecycle_locked` — lines rejected; a short
  allow-list of fields that are not part of the agreement (internal notes,
  attachments, expected dates) stays writable.

The guard lives beside the permission checks already in that function, so a client
that bypasses the UI gets the same answer as the UI.

### 5.3 Permission

A new `Revise_RFQ`, checked on any backward transition. Rolling back invalidates
vendor-facing work; it is not the same authority as editing a draft. Until the
permission exists in a role, the holder of `Approve_Quote` may revise, since that
role already decides what the company commits to.

## 6. Quotes against a revised document

A quote answers one version of a request. When the request changes, that quote is
evidence of what a vendor offered, not an offer against the new document.

**Recommendation: keep and supersede, never delete.** On revision, every quote in
`PENDING` moves to `SUPERSEDED`; the comparison screen excludes superseded quotes
from scoring while still showing them, labelled with the version they answered.
`VendorQuote.status` already carries `SUPERSEDED` and `QuoteComparisonService`
already sets it on re-award, so this reuses a path the system has rather than
adding one.

The alternative, voiding the quotes outright, loses the vendor's prior position —
the one thing the buyer wants when the revision is small.

**Open decision for the business:** whether a revision touching only
non-commercial fields (a delivery date, a description's wording) should supersede
quotes at all, or leave them live. Superseding everything is the safe default and
is what this document specifies until that is decided. Deciding it the other way
needs a rule for which fields are commercial, which is a business rule, not a
technical one.

## 7. Data model

No new tables. The revision loop is built from what exists:

- `po_version_snapshots` — the full document per version, with `transition_type`,
  `change_summary`, `diff_data` and `parent_snapshot_id` lineage. A revision is a
  `STAGE_ROLLBACK` row followed, on re-send, by a `STAGE_ADVANCE` row.
- `po_item_history` — field-level deltas for the lines changed in between.
- `purchase_orders.lifecycle_version` / `stage_version` — the optimistic lock, and
  the version a vendor is quoting against.
- `vendor_quotes.status` — `SUPERSEDED`.

One column is added: `purchase_orders.quoted_against_version`, written when an RFQ
is sent and copied onto each quote as it is recorded, so a quote states its own
version rather than having it inferred from timestamps.

## 8. User interface

- **Revise** button on a sent RFQ, for holders of the revision permission, beside
  the stage badge rather than inside the locked form.
- The lock banner changes from a dead end into a route: it names the stage, says
  what can still change, and offers Revise where the stage allows it.
- `isSourcingLocked` is replaced by a stage-derived rule shared with the backend's
  guard, so the screen and the API cannot disagree.
- On the comparison screen, superseded quotes stay visible, greyed, labelled with
  their version, and excluded from ranking.

## 9. Out of scope

- **Change orders after `PO_ISSUED`.** A PO is a contract; amending one is a
  document of its own, with its own numbering and vendor acknowledgement. It is
  named here only so the lock has somewhere to point.
- **Vendor-side editing.** Vendors proposing substitutes, as the earlier draft of
  this specification imagined, needs a vendor portal. Today a substitute is
  recorded by the buyer on the vendor's quote.
