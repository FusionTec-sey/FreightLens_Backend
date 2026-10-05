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

## C. `codex/pos-wip-checkpoint` — re-verified 2026-10-05

Two of the three original warnings are now **obsolete**. Verified against
`codex/pos-development` with file-presence and content checks, not assumption.

| Was flagged | Reality now | Action |
|---|---|---|
| `f12794c` C12 stock defects | **Already fixed on the integration branch, and more thoroughly.** `adjust-stock` is a retired compatibility route returning 400 ("Direct product-total adjustment is disabled"), `current_stock` reads from a ledger quantity map, and **zero xfail markers remain** | **Do not merge** — it would revert a stronger fix. Its evidence file `t08-legacy-writer-inventory.txt` is still useful background for T08 |
| `b004536` T33A count workspace | **Already merged** via `7b7a71e` "repaired T33A integration"; `CycleCount.py` is byte-identical | **Do not merge** |
| `b004536` T04 notification delivery | **Was genuinely missing** | Replaced by a clean branch, below |

### Ready to merge: `codex/t04-case-notifications` (`234b8c8`)

The T04 slice lifted onto the current integration baseline, rather than merging the
whole nine-commit checkpoint branch. Six files: the notification service, two hooks
in `manager_case_service`, a `require_any_module` guard, the router registration,
the recipient-scoped notification router and its access test.

It also carries a **pre-existing access fix**: the notification list query had no
user filter and the unread count was global, so any authenticated user could read
every other user's notifications in the company. Both are now scoped to the
authenticated recipient, with server-side pagination.

Verified on that base: **full backend suite 515 passed, 1140 skipped, no failures.**

### Still missing: seed fixtures

`Utils/seed_t06_sales_demo.py` and `Utils/seed_t07_counter_demo.py` are absent from
the integration branch, confirmed 2026-10-05. Without the counter seed **no counter
row exists in any company**, so the T07 work-area preview cannot be exercised at
all. They live in `d9798a3` on `codex/pos-wip-checkpoint`, alongside T07 area work
from the parallel lane.

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

1. `codex/t04-case-notifications` — self-contained, tested on this exact base, and
   carries a notification access fix. Do NOT merge `f12794c` or `b004536`; both are
   superseded or already present.
2. The seed fixtures from `d9798a3`, and frontend `codex/pos-ui-theme` for the
   Stock Counts screens that T33A's merged backend already serves.
3. The T14 and T16 pairs, each with its frontend counterpart.
4. `codex/t09-serial-handover` and `codex/t19-integration-record`.
5. `codex/pending-task-verification-20261005` last, or first with the lane entries
   re-applied — its queue rewrite will otherwise overwrite the others.

Conflicts in `TASK-QUEUE.txt`, `COLLABORATION-HANDOFF.txt`, `containerMgmt.py`,
`auth/policy/catalog.py` and `manager_case_service.py` are additive: keep both
sides. New migrations, new permissions and new hooks only append.

Delete this file once every branch above is reachable from `codex/pos-development`.
