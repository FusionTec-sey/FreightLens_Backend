# Unmerged work register — 2026-10-05

**Purpose: stop two people building the same thing.** Everything listed here is
implemented and pushed, but is **not** reachable from `codex/pos-development`.
Before starting any task below, fetch the named branch and read the named commit.
Do not re-implement it.

Baseline: `codex/pos-development` at `42f080e`.
Method: `git merge-base --is-ancestor <sha> origin/codex/pos-development`, and
`git rev-list --count origin/codex/pos-development..<branch>` for every remote
branch in both repositories.

Out of scope by owner instruction: `dev`, `master`, `standalone-main`. They are
legacy lines, not part of the POS tree, and are left exactly as they are.

---

# Backend

## A. Lane branches — one commit each, 2026-10-05

These are finished slices waiting on the integrator. Each carries its own evidence
file, so the work is self-describing once merged.

| Branch | Commit | Task | Contents |
|---|---|---|---|
| `codex/t09-serial-handover` | `715dcc5` | T09 | Exact serial handover history; 12 files, +438. Adds `tests/test_inventory_handover_movement.py` (148 lines) and `evidence/20261005-serial-handover-gateway.txt` |
| `codex/t16-serial-collection` | `7ae40e2` | T16 | Binds serial identities to sale collection; 7 files, +256. Extends `tests/test_sales_collection.py` by 127 lines |
| `codex/t16-serial-docs` | `9b687d4` | T16 | Serial collection checkpoint; queue and handoff updates only |
| `codex/t14-direct-fulfilment-read` | `970e7f2` | T14 | Exposes the posted invoice reference; touches `sales_posting_service.py` and `sales_return_service.py`, +51 lines of posting tests |
| `codex/t14-direct-actions-record` | `1d5e828` | T14 | Records direct post-sale actions; evidence and queue only |
| `codex/t19-integration-record` | `a8780e3` | T19 | Records the merged T19A checkpoint; evidence and queue only |

**Duplication risk:** the two T16 branches and the two T14 branches each split code
from its record. Merging only one of a pair leaves the queue describing work whose
implementation is absent, or vice versa. Merge each pair together.

## B. `codex/pending-task-verification-20261005` — 2 commits

`455f2bb` and `48dbead`. Records a pending-task verification pass plus
`evidence/20261005-pending-task-verification.txt`.

**Handle with care.** Its `TASK-QUEUE.txt` diff is ±1,400 lines — effectively a
rewrite of the file, not a targeted edit. Merging it after the branches above will
either clobber their queue entries or conflict heavily. Either merge it **first**
and re-apply the lane entries on top, or take only its evidence file and
re-annotate the queue by hand.

## C. `codex/pos-wip-checkpoint` — 9 commits

The largest block. Note that **two of these commits fix and extend the earlier
ones**, so take the branch as a whole rather than cherry-picking the originals.

| Commit | Task | Contents |
|---|---|---|
| `d9798a310b8452e4bbec3a080fa481334ab0ab20` | T07, T13A | Register display labels (`customer_name`, `branch_name`, `created_at`, `line_count`) on the drafts list; `Utils/seed_t06_sales_demo.py`; `Utils/seed_t07_counter_demo.py`. **Without the counter seed no counter row exists in any company, so the T07 work-area preview cannot be exercised at all.** Also carries the parallel lane's `sales_area_preview_service`, `sales_local_reservation_service` and `SalesAreaPreviewSchema`, which the router change depends on |
| `b0045366441534004de7084e80987c1d2da5fd90` | **T33A**, **T04**, T06 | T33A implemented in full: six append-only tables, twelve endpoints, three services, two idempotent migrations, six permissions, and the blind-sheet projection carrying no expected stock, earlier round or value. T04 durable case-notification delivery inside the case transaction. `blob_storage.ensure_versioning_enabled()` for the T06 storage gate. Three evidence files and `T33A-COUNT-PROPOSAL-20261004.md` |
| `b6f888e` | **T04 follow-up** | Scopes case notifications to their correct recipients, hardens `auth/module_guard.py`, and adds `tests/test_case_notification_access.py` (68 lines). **This corrects a defect in `b004536`; do not merge that commit without this one** |
| `f12794ce654134f010c7cea91b73eec8ab780695` | **T08** | Both C12 defects closed: `adjust-stock` no longer clamps an excessive negative delta (exact `Decimal`, refused with 400), and a product metadata save can no longer replace held stock (removed from the updatable list, refused with 422). Both strict `xfail` markers removed and those tests now pass. Plus `evidence/t08-legacy-writer-inventory.txt` — the complete legacy writer inventory T08's next action required — and `BROWSER-ACCEPTANCE-CHECKLIST-20261004.md` |
| `ac5dec0` | T04, housekeeping | Sets T04 to verification-pending, fixes a `seed_t05_demo.py` issue and repairs a `tests/test_reporting_worker.py` regression |
| `10aee81` | mixed | Checkpoint of reporting, dashboard and T07 work in progress from the parallel lanes |
| `88e1136`, `8269c39`, `5e12a60` | finance, fixtures | A merge commit, base-currency amount calculation, and local inventory demo seeds |

**Act on `f12794c` first.** T08 is *In progress* on `codex/pos-development`, which
still clamps negative stock and still permits stock replacement through a product
metadata save, and still carries both `xfail` markers that T08's acceptance
requires to pass.

**T33A is the second priority.** It reads *In progress* on the integration branch
with no implementation present, and is assigned to the collaborator in
`COLLABORATION-HANDOFF.txt`. Roughly 1,900 verified lines already exist.

---

# Frontend

| Branch | Ahead | Task | Contents |
|---|---|---|---|
| `codex/pos-ui-theme` | 3 | T33A, T04, POS UI | Shared `RegisterShell` tokens; themed Sales, Customers and Inventory screens; POS sidebar navigation with per-view routes; `PrintableDocument` and print CSS; the four-screen **Stock Counts workspace** that T33A's backend serves; and `4b6705f` which shows personal case notifications, pairing with the backend T04 work. 179 tests pass on this branch |
| `codex/t16-serial-selector` | 1 | T16 | Select exact serials at collection; pairs with backend `codex/t16-serial-collection` |
| `codex/t14-posted-sale-actions` | 1 | T14 | Direct posted-sale collection and printing; pairs with backend `codex/t14-direct-fulfilment-read` |

**Pair the merges across repositories.** A backend serial-collection merge without
`codex/t16-serial-selector` leaves no way to pick serials; the Stock Counts screens
without `b004536` have no API to call.

---

## Suggested order

1. `f12794c` — small, self-contained, unblocks correct T08 work.
2. `codex/pos-wip-checkpoint` as a whole (keeps `b004536` with its `b6f888e` fix),
   paired with frontend `codex/pos-ui-theme`.
3. The T14 and T16 pairs, each with its frontend counterpart.
4. `codex/t09-serial-handover` and `codex/t19-integration-record`.
5. `codex/pending-task-verification-20261005` last, or first with the lane entries
   re-applied — its queue rewrite will otherwise overwrite the others.

Conflicts in `TASK-QUEUE.txt`, `COLLABORATION-HANDOFF.txt`, `containerMgmt.py`,
`auth/policy/catalog.py` and `manager_case_service.py` are additive: keep both
sides. New migrations, new permissions and new hooks only append.

Delete this file once every branch above is reachable from `codex/pos-development`.
