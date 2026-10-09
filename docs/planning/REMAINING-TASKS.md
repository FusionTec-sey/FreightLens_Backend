# FreightLens remaining-task view

Snapshot: 2026-10-04  
Authority: [`TASK-QUEUE.txt`](./TASK-QUEUE.txt) remains the only task-status ledger.  
Scope: cloud-authoritative delivery under BD-20261004-10. T21-T24 are retained but deferred.

## Work currently moving

| Task | Status | Remaining outcome |
|---|---|---|
| T04 | In progress | Finish reusable manager-case notifications and outstanding acceptance. |
| T06 | In progress | Public reviewed receipt-cost evidence and immutable product/pool checkpoints are ready; complete external evidence-retention/runtime acceptance and broader period/accounting gates. |
| T08 | In progress | Quantity readers, reviewed location adjustments and receipt evidence review are authoritative; finish opening/import composition and keep final receipt execution gated by retention/runtime acceptance. |
| T10 | In progress | Complete customer profile/contact updates, history and controlled duplicate review without balance merging. |
| T14B | In progress | Finish the sales register and navigation refinement. |
| T14C | In progress | Finish the desktop split-view sales workspace. |
| T14D | In progress | Finish the tablet product-and-cart draft workspace. |
| T33A | In progress | Finish cycle-count planning, blind entry, recount and review acceptance; do not add stock posting. |

## Implemented, with verification or external acceptance still remaining

| Task | Status | Remaining outcome |
|---|---|---|
| T03 | Implemented—verification pending | Complete branch/counter settings and permission acceptance. |
| T05 | Implemented—verification pending | Complete approved browser acceptance; physical conversion stays with T06/T09. |
| T07 | Implemented—verification pending | Complete remaining runtime/browser acceptance for the protected reservation lifecycle. |
| T10A | Implemented—verification pending | Complete live provider/browser and projection-recovery acceptance. |
| T11 | Implemented—verification pending | Complete browser and real tax/accounting-configuration acceptance. |
| T13A | Implemented—verification pending | Complete scoped visual/provider acceptance for authoritative sales drafts. |
| T15A | Implemented—verification pending | Complete browser reload and multi-tab recovery acceptance. |

## Ready independent work

| Task | Status | Remaining outcome |
|---|---|---|
| T12 | Ready | Implement customer-money configuration, payment methods, branch receiving-account mappings and fail-closed lookup. The bounded T12A configuration package is assigned to the other programmer. |

## Dependency-blocked cloud delivery

| Task | Depends on | Remaining outcome |
|---|---|---|
| T09 | T08 | Transfers, dispatch, transit, receipt, write-off and controlled stock movements. |
| T13 | T07, T08, T11, T12, T13A | Atomic invoice, stock, payment allocation, numbering and outbox posting. |
| T14 | T13, T15A, T14D | Connect real pricing, payments and atomic posting to tablet checkout. |
| T14E | T14, T15, T16, T17 | Integrated desktop/tablet sales-screen acceptance. |
| T15 | T14, T15A | Safe document copy and full checkout draft protection. |
| T16 | T09, T13, T14 | Line-level partial collection, collector details and exact serial handover. |
| T17 | T13 | Immutable invoices, COPY reprints and Epson-aware print queues. |
| T18 | T12, T16 | Invoice/handover-linked returns, cumulative eligibility and credit notes. |
| T19 | T04, T09, T18 | Damaged/display, quarantine, disclosure, supplier claim and write-off workflows. |
| T20 | T12, T13, T18 | Till close, discrepancy approval, bank matching and balanced accounting export. |
| T25 | T13, T17 | Consent-aware queued email/WhatsApp invoice delivery using sandbox adapters first. |
| T26 | T08, T20 | inFlow import mapping, exception review, opening reconciliation and restore rehearsals. |
| T27 | T12, T13, T18 | Deposits, top-ups, refunds/reclassification and cheque lifecycle/history. |
| T28 | T04, T13, T27 | Contract terms, exposure, ageing, statements and scoped credit exceptions. |
| T29 | T07, T10, T28, T13A | Quotes, confirmed orders, waiting-list links, lead times and salesperson follow-through. |
| T30 | T11, T13 | Customer-beneficial pricing groups, tiers, offers, bundles and coupons. |
| T31 | T18, T30 | Promotion-aware cumulative returns with explicit exception cases. |
| T32 | T20, T28, T29, T31 | Reporting and drill-down with access controls and provisional-cost labels. |
| T33 | T09, T11, T33A | Price labels and movement-aware cycle-count reconciliation/coverage planning. |
| T34 | T14E, T15, T19, T25-T33 | Hardware, configuration, import, accounting, outage and supervised-pilot gates. |

## Retained but owner-deferred offline work

These tasks remain in the roadmap but are not part of the current single-cloud build goal.

| Task | Depends on | Deferred outcome |
|---|---|---|
| T21 | T02, T03 | Store/cloud runtime packaging and secure local-node enrollment. |
| T22 | T21 | Durable inbox/outbox synchronization and ordered recovery. |
| T23 | T12, T22 | Offline eligibility, policy validity and shared-money fencing. |
| T24 | T16, T23 | Controlled paper-outage recovery and reconciliation. |

## Completed foundations not repeated above

T01, T01A, T02 and T14A are Verified. Their tracking, posting-authority,
consolidation and approved sales-design foundations remain in force.
