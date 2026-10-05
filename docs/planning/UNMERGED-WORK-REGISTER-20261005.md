# Unmerged work register — 2026-10-05

**Purpose: stop two people building the same thing.** Work listed here is already
implemented and pushed on another branch, but is **not** reachable from
`codex/pos-development`. Before starting any task below, read this file, fetch the
named branch and review the named commit. Do not re-implement it.

Baseline for this register: `codex/pos-development` at `42f080e`.
Verification method: `git merge-base --is-ancestor <sha> origin/codex/pos-development`.

---

## Backend — branch `codex/pos-wip-checkpoint`

### 1. `d9798a310b8452e4bbec3a080fa481334ab0ab20` — register labels, demo seeds, T07 area dependencies

| | |
|---|---|
| Affects | T07, T13A, local fixtures |
| Status on this branch | **Not merged** |

- `SalesIntentSummary` and the drafts list return `customer_name`, `branch_name`,
  `created_at` and `line_count`, resolved with org-scoped outer joins, so the
  register shows names instead of a raw document UUID. The customer name is
  personal data and rides the existing `View_Customer` + `View_Personal_Data` gate.
- `Utils/seed_t06_sales_demo.py` — synthetic customers, drafts, source-linked
  holds and release/follow-up/reallocation cases in mixed states.
- `Utils/seed_t07_counter_demo.py` — the first enabled counter and work area.
  **Without it the T07 work-area preview and local reservation cannot be exercised
  at all**, because no counter rows exist in any company.
- Also carries the collaborator's `sales_area_preview_service`,
  `sales_local_reservation_service` and `SalesAreaPreviewSchema`, which the router
  change depends on.

**Duplication risk:** anyone improving the sales register, or wondering why the
work-area preview has nothing to select, will rebuild these.

### 2. `b0045366441534004de7084e80987c1d2da5fd90` — T33A count workspace, T04 delivery, T06/T07 gates

| | |
|---|---|
| Affects | **T33A**, **T04**, T06, T07 |
| Status on this branch | **Not merged** |

- **T33A is fully implemented here**: six append-only tables (`CycleCount.py`),
  twelve endpoints (`CycleCountRouter.py`), three services, two idempotent
  migrations, six seeded permissions, and the blind-sheet projection that carries
  no expected stock, earlier round or value. Verified end to end on synthetic data.
  `docs/planning/T33A-COUNT-PROPOSAL-20261004.md` holds the schema/API proposal.
- **T04's recorded remaining item is closed**: `case_notification_service.py`
  delivers durable in-app notifications to eligible reviewers inside the case
  transaction. This is why T04 reads *Implemented—verification pending* on
  `codex/pos-wip-checkpoint` but still *In progress* here.
- `blob_storage.ensure_versioning_enabled()` validates and enforces object version
  retention at startup — the T06 storage gate.
- Evidence: `evidence/t33a-count-workspace.txt`,
  `evidence/t04-case-notification-delivery.txt`,
  `evidence/t06-t07-runtime-and-retention-gates.txt`.

**Duplication risk: highest in this register.** T33A is assigned to the
collaborator in `COLLABORATION-HANDOFF.txt` and reads *In progress* on this branch
with no implementation present. Anyone picking it up will rebuild roughly 1,900
lines that already exist and are verified.

### 3. `f12794ce654134f010c7cea91b73eec8ab780695` — both C12 stock defects closed

| | |
|---|---|
| Affects | **T08** |
| Status on this branch | **Not merged — and T08 is actively being worked here** |

- `adjust-stock` no longer clamps an excessive negative delta to zero. It uses
  exact `Decimal` arithmetic and refuses with 400, naming the held quantity.
- A product metadata save can no longer replace held stock: `current_stock` is
  removed from the catalogue updatable list and supplying it is refused with 422
  rather than silently ignored.
- Both strict `xfail` markers in `tests/test_pos_prerequisite_regressions.py` are
  removed; those two tests pass as ordinary assertions. 37 passed in that suite,
  125 in related suites.
- `evidence/t08-legacy-writer-inventory.txt` — the complete legacy writer
  inventory T08's next action called for: four writers of `Product.current_stock`,
  plus eight reader sites that still treat the legacy total as authoritative and
  must move with the writers. Confirms nothing outside `stock_ledger_service`
  writes `StockBalance` quantities.
- `docs/planning/BROWSER-ACCEPTANCE-CHECKLIST-20261004.md` — owner-run acceptance
  checklist for T03, T04, T05 and T33A.

**Act on this one first.** T08's acceptance requires "two C12 xfails pass". On
`codex/pos-development` both defects are still open and both markers still present,
so T08 is being built on a base that clamps negative stock and permits stock
replacement through a metadata save.

---

## Frontend — branch `codex/pos-ui-theme` at `4b6705fa07ea9414b8028c39e560ddae8681e66d`

**Not merged into the frontend `codex/pos-development`.** Contains the shared
`RegisterShell` tokens, the themed Sales/Customers/Inventory screens, the POS
sidebar navigation with per-view routes, `PrintableDocument` plus print CSS, and
the four-screen Stock Counts workspace that T33A's backend serves. 179 frontend
tests pass on that branch.

**Duplication risk:** the Stock Counts screens and the printable document do not
exist on the integration branch.

---

## What is already merged, for completeness

`0c0c70d` (BD-20261004-09, the cloud-only deferral of T21–T24) **is** reachable
from `codex/pos-development`, superseded there by `BD-20261004-10`. No action.

---

## How to clear this register

Per `BD-20261005-01` the integrator owns merges and shared contracts, so these are
merge requests, not pushes:

1. Merge `f12794c` first — it is small, self-contained and unblocks correct T08 work.
2. Merge `b004536` — resolve `TASK-QUEUE.txt`, `containerMgmt.py`,
   `auth/policy/catalog.py` and `manager_case_service.py` by keeping both sides;
   the additions are append-only (new migrations, new permissions, two notification
   hooks).
3. Merge `d9798a3` — note it also carries T07 area work from the parallel lane.
4. Merge the frontend `codex/pos-ui-theme`, which pairs with 2 and 3.

Delete this file once all four are reachable from `codex/pos-development`.
