# Owner verification plan

**SUPERSEDED AS A REQUIREMENT by BD-20261005-09 (2026-10-05).** The owner has
waived manual acceptance and directed that time to development. Tasks now reach
Verified on automated evidence alone.

This plan is **retained, not cancelled**. It remains the script to run if a pass is
ever wanted, and it SHOULD be run before the supervised pilot. The sessions below
also mark what is now knowingly untested.

**Still genuinely untested, because only a browser can show it:**

- Navigation, reload and multi-tab draft recovery (Session 5, rows 5.3 and 5.6)
- Visual layout, dark mode, narrow viewport (Session 12)
- Print output as the browser renders it (Session 7, rows 7.2 and 7.3)
- Tablet ergonomics for checkout and the blind count sheet (Sessions 7 and 11)

Everything else in this plan has equivalent assertions in the automated suites.

---

Everything waiting on the owner to verify, in one place. **16 tasks** currently
converge here, and acceptance is the project's throughput bottleneck — not
development.

Organised by **session**, not by task, because the tasks share screens heavily.
Verifying them together is far cheaper than one at a time. One task may appear in
several sessions; it is accepted when all of its rows pass.

**Setup**

- `http://localhost:3000`, signed in, company switched to a company that has
  fixtures. Only the demo company is seeded today.
- Check each screen in **light and dark**, and once at roughly **400px** wide: the
  shell stays fixed, only content scrolls, no horizontal page scroll.
- Record as: screen → action → expected → actual. Anything that fails is a defect
  to send back, not a reason to stop the session.

**Before you start**, two gaps will otherwise block you:

1. The **seed fixtures are not on the integration branch**. Without
   `seed_t07_counter_demo.py` there is no counter in any company, so work-area and
   collection flows cannot be exercised at all.
2. The **Stock Counts screens are not merged** (frontend `codex/pos-ui-theme`), so
   T33A's merged API has no UI to verify.

---

## Session 1 — Settings and permissions (T03)

| # | Check | Expect |
|---|---|---|
| 1.1 | Branch settings → trading calendar, business date, cutoffs | Saves and reloads correctly |
| 1.2 | Counters panel | A counter exists, is enabled, has a work area |
| 1.3 | **Remove a mandatory setting**, then attempt a dependent action | **Action is blocked.** This is the core T03 criterion — absent mandatory settings must block, not default |
| 1.4 | A user without the branch permission | Cannot reach or change settings |

## Session 2 — Inventory policies and barcodes (T05)

| # | Check | Expect |
|---|---|---|
| 2.1 | Policy draft → review → activation | Activation requires a reviewed case |
| 2.2 | Activated policy snapshot | Immutable; earlier snapshots unchanged |
| 2.3 | Attempt an ambiguous transition | **Blocked** |
| 2.4 | Unit barcode registration and lookup | Bound to the active policy; retired codes rejected |

## Session 3 — Manager cases (T04)

| # | Check | Expect |
|---|---|---|
| 3.1 | Request → review → approve/reject | Full audit visible |
| 3.2 | **Review your own request** | **Refused** |
| 3.3 | Approve, then change the source, then try to reuse the approval | **Refused** — approval binds an exact version |
| 3.4 | Notifications | Unread entries for cases needing you; opening one reaches the case |
| 3.5 | Notification content | **No customer name, quantity, amount or reason text** |
| 3.6 | Sign in as another user | You see **only your own** notifications |

## Session 4 — Reservations (T07)

| # | Check | Expect |
|---|---|---|
| 4.1 | Draft → Reserved stock | Holds listed with source links |
| 4.2 | Release / follow-up / reallocation request → review | Each needs an independent reviewer |
| 4.3 | Overdue follow-up inbox | Due holds listed; drill-through re-checks access |
| 4.4 | Work-area preview, then reserve | Allocates within the area; shortfall shown when it cannot |
| 4.5 | Attempt multi-location allocation without approval | **Blocked** |

## Session 5 — Customers and drafts (T10A, T13A, T15, T15A)

| # | Check | Expect |
|---|---|---|
| 5.1 | Create a customer, search, select into a draft | Identity reused, not duplicated |
| 5.2 | Save a draft, reopen, revise | Versions increment; history preserved |
| 5.3 | **Navigate away mid-edit, come back** | Entries recovered (T15A) |
| 5.4 | **Force a failed save, then retry** | Same operation, no duplicate document |
| 5.5 | **Copy a draft** | Intent and lines copied; **no money, reservations, approvals or collection carried over** (T15) |
| 5.6 | Two browser tabs on the same draft | No silent overwrite |

## Session 6 — Pricing and tax (T11)

| # | Check | Expect |
|---|---|---|
| 6.1 | Same product in two stores | Independent prices |
| 6.2 | Agreed customer price | Applied for that customer only |
| 6.3 | SCR price display | **Tax-inclusive**; VAT shown correctly |
| 6.4 | Attempt a price below the floor | **Blocked** |
| 6.5 | Exempt customer or product | Tax handled correctly |
| 6.6 | Change a price | Original rule preserved, not edited |

## Session 7 — Sale, invoice, collection (T13 re-check, T16, T17)

| # | Check | Expect |
|---|---|---|
| 7.1 | Complete a sale end to end | Posts once; retry does not double-post |
| 7.2 | Invoice render | Immutable; reprint marked **COPY** (T17) |
| 7.3 | Print queue after a failure | Failed/uncertain states visible, not silently lost |
| 7.4 | **Partial pickup** | Remaining quantity stays outstanding (T16) |
| 7.5 | Collector identity and serial assignment at collection | Recorded |
| 7.6 | Attempt collection beyond the sold quantity, or twice | **Blocked** — quantity and duplicate caps |
| 7.7 | Attempt collection without payment eligibility | **Blocked** |

## Session 8 — Returns (T18)

| # | Check | Expect |
|---|---|---|
| 8.1 | Return against an original invoice | Linked to the invoice and the actual handover |
| 8.2 | Return more than was handed over | **Blocked** |
| 8.3 | Second claim on the same line | Previous and pending claims counted |
| 8.4 | Customer with an outstanding debt | **Debt settled before any surplus credit** |
| 8.5 | Damaged return | Salesperson verifies, then chooses the disposition; nothing auto-routed |

## Session 9 — Stock movements (T09)

| # | Check | Expect |
|---|---|---|
| 9.1 | Dispatch → transit → receipt | **Destination stock available only after receipt**, never during transit |
| 9.2 | Batch and serial lineage across the movement | Preserved |
| 9.3 | Controlled adjustment and write-off | Reason recorded; no silent clamp |
| 9.4 | Quantity conservation | Nothing created or lost in transit |

## Session 10 — Damaged and display (T19)

| # | Check | Expect |
|---|---|---|
| 10.1 | Move stock to damaged | Requires the permission; no good-stock inflation |
| 10.2 | Write-down | Recovery value entered per event, **≤ carried cost**, zero allowed |
| 10.3 | Display units | **Remain sellable** |
| 10.4 | Sell a damaged item later | Ordinary sale against the written-down value; no second write-down |

## Session 11 — Counts (T33A) — *needs the frontend merged first*

| # | Check | Expect |
|---|---|---|
| 11.1 | Plans, scope, activation, coverage | As configured |
| 11.2 | Assign a round, open the sheet | Only the assigned counter can open it |
| 11.3 | **The blind sheet** | **No expected quantity, no earlier round, no value anywhere.** The single most important check in this plan |
| 11.4 | Submit, then review a discrepancy | Provisional difference recorded; decision needs a different reviewer |
| 11.5 | Attempt to edit a submitted count | **Refused** — recount only |

## Session 12 — Cross-cutting

| # | Check | Expect |
|---|---|---|
| 12.1 | Dark mode, all screens | Readable; no white-on-white |
| 12.2 | ~400px width | Fixed shell, contained scrolling |
| 12.3 | Switch company mid-session | Data clears and reloads; **no cross-company leakage** |
| 12.4 | Compare against Purchase Orders | Reads as one product |

---

## Out of scope — do not test, by decision

- Offline selling, store-local nodes, synchronisation, paper recovery (T21–T24).
- Till reconciliation, opening float, cash-deposit matching, day-close authority.
- Accounting journals and ledger export.
- Supplier claims, disclosure and approved discount on damaged stock — handled
  administratively, not in software.

## Separate gates, not owner verification

Epson hardware printing, provider/storage retention, accounting review, real data
import and the supervised pilot each remain their own gate.
