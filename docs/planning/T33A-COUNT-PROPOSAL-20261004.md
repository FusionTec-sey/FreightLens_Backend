# T33A — cycle-count planning and blind-count workspace: schema and API proposal

Date: 2026-10-04. Status: proposal for integrator review, per the T33A queue entry
("propose schema/API and shared-file integration changes, then build count-specific
services/UI").

Nothing in this slice posts stock, freezes stock, values stock, prints price labels
or reconciles a discrepancy. It creates count records only. Movement-aware
reconciliation and any adjustment stay in T09/T33.

## Reuse, not rebuild

| Need | Existing thing reused |
|---|---|
| Products, locations, branches | `Product`, `StockLocation`, `InventoryBranch` |
| Unit rules, exact quantities | `InventoryPolicyConfig`, `ProductPolicyActivation`, `inventory_unit_service.convert_quantity` |
| Approvals | `manager_case_service` request/review/consume, with a new action string |
| Durable retries, one-effect writes | `inventory_posting_service.execute_once` |
| Company isolation | `OrgMixin`, `OrgContext`, `apply_org_filter` |
| Paginated tables | `LocationPage[...]` response model + server-side page/limit |
| Notifications | `case_notification_service` (added for T04) |

No second catalogue, location tree, approval engine, identity store or inbox.

## Tables (all `containermgmt`, all `OrgMixin` + `AuditMixin`)

1. **`inventory_count_plans`** — an annual programme for one branch.
   `id`, `org_id`, `branch_id`, `plan_key uuid`, `code`, `name`, `year`,
   `state` (`DRAFT`/`ACTIVE`/`CLOSED`), unique `(org_id, plan_key)` and
   `(org_id, branch_id, code)`.
2. **`inventory_count_scopes`** — the product-location lines a plan covers.
   `plan_id`, `product_id`, `location_id`, `cadence` (`ANNUAL`/`QUARTERLY`/`MONTHLY`),
   `due_on date`, unique `(org_id, plan_id, product_id, location_id)`.
   Coverage reporting reads this, so "annual coverage" is a query, not a new store.
3. **`inventory_count_sessions`** — one assignment of a scope slice to a counter.
   `session_key uuid`, `plan_id`, `location_id`, `assignee_id`, `state`
   (`ASSIGNED`/`IN_PROGRESS`/`SUBMITTED`/`REVIEWED`/`CANCELLED`), `round int`,
   `parent_session_id` for a recount, `opened_at`, `submitted_at`,
   unique `(org_id, session_key)`.
4. **`inventory_count_entries`** — immutable blind entries.
   `session_id`, `product_id`, `location_id`, `counted_quantity numeric(18,6)`,
   `unit`, `base_quantity numeric(18,6)`, `base_unit`, `policy jsonb`,
   `operation_key uuid`, unique `(org_id, session_id, product_id, location_id)`,
   unique `(org_id, operation_key)`. **Update and delete rejected by trigger**, as
   with `sales_intent_*` and `inventory_counter_*`.
5. **`inventory_count_discrepancies`** — provisional, computed at submission.
   `session_id`, `product_id`, `location_id`, `counted_base numeric(18,6)`,
   `expected_base numeric(18,6)`, `difference_base numeric(18,6)`,
   `balance_version int`, `state` (`PROVISIONAL`/`REVIEWED`), `case_key uuid null`.
   `expected_base` is captured **at submission**, never shown before it, and is
   explicitly provisional because stock can move between count and review.

Immutability: entries and discrepancy rows get the same `BEFORE UPDATE OR DELETE`
reject trigger used elsewhere, so a recount is a new session (round + 1), never an
edit. Recount rounds chain through `parent_session_id`.

## Blind-count rule, enforced on the backend

The counter-facing read returns **only** product identity, location, unit and the
step from the reviewed policy. It never returns `expected_base`, `on_hand`, any
valuation, or any earlier round's entries. That is enforced in the service and in
the response model, not by hiding fields in React. A counter holding only the
entry permission cannot reach the planning, discrepancy or review reads at all.

## Permissions (new, seeded by migration into Super_Admin / Administrator)

| Permission | Grants |
|---|---|
| `View_CountPlan` | See plans, scopes, coverage |
| `Manage_CountPlan` | Create and activate plans and scopes |
| `Assign_CountSession` | Assign and cancel sessions |
| `Enter_CountResult` | Blind entry and submit, own assigned sessions only |
| `View_CountDiscrepancy` | See provisional discrepancies |
| `Review_CountDiscrepancy` | Decide a discrepancy case |

`Enter_CountResult` deliberately grants no visibility of expected stock.

## API (all paginated, all org-scoped, module `INVENTORY`)

```
GET    /inventory/count-plans                      View_CountPlan
POST   /inventory/count-plans                      Manage_CountPlan
POST   /inventory/count-plans/{key}/scopes         Manage_CountPlan
POST   /inventory/count-plans/{key}/activate       Manage_CountPlan
GET    /inventory/count-plans/{key}/coverage       View_CountPlan
GET    /inventory/count-sessions                   Assign_CountSession | Enter_CountResult (own)
POST   /inventory/count-sessions                   Assign_CountSession
GET    /inventory/count-sessions/{key}/sheet       Enter_CountResult   (blind projection)
PUT    /inventory/count-sessions/{key}/entries     Enter_CountResult   (operation_key, expected_version)
POST   /inventory/count-sessions/{key}/submit      Enter_CountResult
POST   /inventory/count-sessions/{key}/recount     Assign_CountSession
GET    /inventory/count-discrepancies              View_CountDiscrepancy
POST   /inventory/count-discrepancies/{id}/review   Review_CountDiscrepancy (manager case)
```

Every write takes an `operation_key` and an `expected_version`, so an uncertain
retry is the same operation and a stale client is refused — the contract already
used by sales drafts and reservations.

## Manager case integration

New action `inventory.count.discrepancy` with review permission
`Review_CountDiscrepancy`, added to `case_notification_service.REVIEW_PERMISSION`
and `SUBJECT`. Review decides the record only; it authorises no adjustment, and
the review screen says so. Self-review is already refused by `manager_case_service`.

## Shared-file changes needed (integrator review)

- `containerMgmt.py`: register the new migration and router.
- `auth/policy/catalog.py`: six new permissions.
- `Services/case_notification_service.py`: one action mapping.
- Frontend `MenuPanel/Menu.js` and `MainPage.js`: a Counts menu group and routes.

Nothing else shared is touched. No change to stock, valuation, sales or customer
contracts.

## Frontend

A Counts group in the sidebar, reusing `RegisterShell`: plans register, scope
builder, assignment board, a blind count sheet built for a tablet (product,
location, unit, quantity field, no expected figures anywhere on screen), and a
discrepancy register that opens the existing `ManagerCases` review panel.

## Out of scope, explicitly

Stock adjustment or posting, freeze windows, valuation effects, price labels,
final reconciliation, offline entry, barcode scanning hardware, and any real
inventory seed. Browser and provider acceptance remain separate gates.
