# FreightLens POS execution plan — 2026-10-04

This is an execution map, not a second task queue. `TASK-QUEUE.txt` remains the authoritative task/status ledger. Read `BUSINESS-DECISIONS.txt` before each slice; later agreed decisions take precedence over the 2026-09-30 *FreightLens POS Module — Draft Plan*. The draft remains the product vision.

## Product direction

Build a counter sales flow from Inventory's real products and stock: customer and draft demand → eligible reservation or explicit shortfall → quote/order or direct sale → invoice and payment → physical collection → returns and reporting. Keep reservation, payment and handover as separate states. POS depends on Inventory, with no second catalogue, stock ledger, approval engine or customer identity. Store prices, taxes, work areas and approvals are configurable; a new cost never changes a selling price automatically.

The first usable flows may operate against the central online stack. Supervised pilot readiness additionally requires the later offline eligibility, sync, paper-outage, hardware, accounting and import gates recorded in the queue. A locally running Docker screen is not pilot acceptance.

## Starting point

- Reuse T03/T04/T05 settings, authority, manager cases and reviewed Inventory policies. T05's agreed implementation scope is in place; browser acceptance is pending. Physical conversion belongs to T06/T09.
- Reuse T10A customer identity/search/select, T13A saved sales document and lines, and T15A local draft/retry recovery. These do not confirm a sale or post money.
- T07 has source-linked holds, reviewed release/reallocation/follow-up, and a due inbox. T06 has valuation/evidence/central-authority foundations. Both remain in progress.
- Local Docker has the current backend and frontend foundations. The Sales/Customers visual pass and admin menu fix are local frontend changes, outside the paired published baseline. Preserve unrelated uncommitted backend/frontend work when preparing task branches or PRs.

## Work sequence

### 1. Finish T07 allocation for real sales work

1. Bind the signed-in salesperson and counter to the current configured work area. Resolve it on the backend and fail closed for missing, stale or foreign settings.
2. Plan and reserve eligible stock automatically **within that area** using reviewed policy and exact quantities. Show the shortfall when the area cannot satisfy demand. Do not silently search or allocate elsewhere.
3. Add explicit other-area and other-store choices with the required manager review, exact source/version binding and fresh eligibility checks. Protect paid holds; follow-up dates trigger review, never silent cancellation or reassignment.
4. Expose the allocation, shortfall and approved exception path in the existing Sales draft flow. Keep the saved document/line/version as the demand identity.

Deliverable: a salesperson can see where stock can be held and why an exception is needed, without treating a draft as an invoice. Coordinate public stock writer and shared Sales/Inventory contracts with the integrator before editing them.

### 2. Finish T06 trusted valuation alongside T07

1. Connect authenticated central-runtime identity and fencing to the persisted cost-pool authority; do not treat branch authority as central financial authority.
2. Validate RustFS object version retention and configure bounded evidence capture before enabling reviewed financial evidence posting.
3. Connect authoritative receipt/freight and FX evidence to existing charge and valuation contracts. Preserve original quantities, immutable costs, pool identity and atomic retries.
4. Add central reconciliation and make provisional versus reconciled cost visible. Keep independent branch selling prices unchanged by cost posting.

Deliverable: trustworthy source-linked costs for later sales margin and physical stock movement, without enabling unreviewed public financial posting.

### 3. Parallel T33A count workspace

The collaborator first proposes the count schema, APIs, permissions and protected shared-file changes. Then build annual product-location schedules, assignments, blind entry, immutable recount rounds, provisional discrepancy review and audited manager decisions. Blind counter reads must exclude expected stock, prior counts and financial values. This slice creates count records only; T09/T33 later connect movement-aware reconciliation and any stock adjustment. Use separate checkouts, services and synthetic data, with linked backend/frontend PRs for integrator review.

### 4. Establish one physical stock path: T08 then T09

Inventory and replace legacy writers through the existing guarded stock boundary. Then build dispatch, transit, receipt, controlled adjustments and stock reclassification with batch/serial lineage and quantity/value conservation. This unlocks quick receive, collection, returns and reliable stock analytics. Existing reviewed reclassification proposals are inputs, not permission to convert stock before the movement and authority gates pass.

### 5. Complete commercial rules before checkout

Extend T10A into T10 versioned customer profile/history and controlled duplicate review, preserving original sales references. Build T11 branch price history, base-price floors, customer terms and configurable tax. Build T12 payment methods, receiving-account mappings, deposits, credit notes and credit liability, with absent mappings blocking posting. These can be scoped into independent frontend/backend slices once ownership and interfaces are set; they do not require a new customer or product store.

Resolve the following business-rule wording before T12/T27/T29 implementation:

- The draft permits configurable deposit/credit-note expiry; later decisions say customer credit never expires. Specify which balances, if any, can expire.
- Decide cross-store use of deposits and credit notes; the draft left this open.
- Pre-order follow-up and release must obey the later rule against silent cancellation or reassignment of paid holds. Confirm the exact staff-reviewed expiry action.

### 6. Compose the first complete sale

After T07/T08/T11/T12, implement T13 atomic sales posting using the existing saved document/line identity, stock authority, customer, price/tax and money services. A confirmed order needs qualifying deposit or agreed credit terms. Invoice, payment/commitment, number and outbox must have one durable outcome under retry. Then build T14 tablet checkout on that API, reuse T15A recovery in T15, and add T16 physical pickup and T17 immutable invoice/print queue. Payment and fulfilment statuses remain separate; selling never implies physical handover.

### 7. Extend after-sale and operating capabilities

Follow the queue dependencies for returns/credit notes, damaged stock, close/accounting export, contract credit, quotes/orders/waiting demand, offers, labels/count reconciliation and reporting. Add store/cloud runtime, durable sync, offline eligibility and paper recovery as explicit pilot gates. Do not infer that an online-only development slice is ready for a supervised store rollout.

## Fast development rhythm

Parth's 2026-10-04 instruction is to build for visible existence first and defer test runs until he requests the development checkpoint. Implement one usable vertical slice at a time, with its existing frontend entry point when applicable. Do not run routine Jest, pytest, full regression, visual automation or repeated production builds after each edit. Rebuild the Docker frontend only when the new UI needs to appear in the running preview. Keep a short list of pending checks and run the relevant ones when Parth asks or when investigating a particular failure. Until then, describe a slice as implemented, not verified or complete.

Reuse existing routes, permissions, pagination, receipts, migrations and manager cases instead of designing parallel infrastructure. Inspect only the affected code and contracts before editing. Keep shared-interface coordination and exact scope/version/authority checks in the implementation; skipping test execution does not change the business rules. Preserve unrelated uncommitted work, avoid broad refactors and avoid repeated documentation updates. Browser automation still needs the explicit approval required by `AGENTS.md` rule 13. Do not use real business data, turn on live posting or claim pilot readiness from a Docker build.
