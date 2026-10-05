# Skipped scope register

Things the owner has decided **not** to build for the current delivery. Nothing
here is cancelled: each item is retained with its reason and the decision that
parked it, so it can be picked up deliberately rather than rediscovered by
accident.

**Rule: nothing is removed from the codebase because it appears here.** Work that
is already built and inert stays built and inert. Do not delete, weaken or
re-enable it without a new decision.

Keep this file current. When an item is resumed, move it out and record the
decision that resumed it.

| # | Skipped | Decision | Why | Resume when |
|---|---|---|---|---|
| 1 | Store-local hosting and multi-node packaging (T21) | BD-20261004-10, BD-20261004-09 | One cloud deployment serves every store | Outage frequency or cost justifies local nodes |
| 2 | Durable store/cloud synchronisation (T22) | BD-20261004-10 | Nothing to synchronise with a single deployment | T21 resumes |
| 3 | Offline eligibility, cached policy, node fencing, shared-money limits (T23) | BD-20261004-10 | Stores use the cloud instance directly | T21/T22 resume |
| 4 | Software paper-outage recovery (T24) | BD-20261004-10 | Outages handled by an operational paper procedure outside the software | Offline scope resumes |
| 5 | Till reconciliation, opening float, blind cash count, cash-deposit matching | BD-20261005-04 | Cashier at reception counts cash manually | Accounting module is developed |
| 6 | **Close authority and day-close approval** | BD-20261005-05 | Not required for now; no system-enforced close, variance approval or supervisor sign-off | Accounting module is developed |
| 7 | Accounting module: journal export, ledger posting, discrepancy approval | BD-20261005-04 | Future module, developed later | Owner starts the accounting module |
| 8 | Accounting export rehearsal within import/recovery (T26) | BD-20261005-04 | No accounting module to rehearse against | Item 7 resumes |
| 9 | Ledger and journal reporting (T32) | BD-20261005-04 | Reporting proceeds on sales, stock and customer data | Item 7 resumes |

## Open owner decisions blocking implementation

| Needed | For | Note |
|---|---|---|
| Whether a write-down needs review above a threshold | T19 | Or is the damaged-stock permission sufficient, per BD-20261005-05 |
| Supplier claims, disclosure, approved discount on damaged stock | T19 | Listed in T19 acceptance; still fail closed |

## Already built and parked — do not remove

| What | Where | State |
|---|---|---|
| T20A account mapping foundation | versioned per-branch logical account mappings, balanced journal composition | Fail-closed, no real account seed, no activation. Surfaced under Sales for now per BD-20261005-05 |
| Node identity and authority epochs | `StoreNode`, `BranchAuthorityEpoch`, `execute_once` operation keys | In use as a single-runtime safety fence; also the foundation if T21 resumes |
| Posting outbox | existing posting operations and event envelopes | In use for replay protection; the basis for T22 if sync resumes |
| T21 packaging handoff | `PROGRAMMER-T21-HANDOFF.txt` | Historical until reactivated |
