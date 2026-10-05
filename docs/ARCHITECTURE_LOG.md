# FreightLens Architecture Log

## 2026-10-05 - T15 immutable sales-draft copy provenance

- Extended only the existing initial sales-intent save with an optional exact
  source document/revision and immutable same-company provenance.
- Required new destination document/line identities and retained current source
  validation; no price, approval, reservation, money, posting, invoice, collection
  or print state is cloned.
- Stable retries bind the source reference and rerun permissions. Service and
  deferred database guards reject foreign/missing sources, self-copy and source
  line-key reuse; current and historical detail return the source reference.
- Seven focused T15 and 34 affected draft/API/concurrency tests pass. Frontend wiring
  and browser acceptance remain open.

## 2026-10-05 - T17 immutable invoice artifacts and print queue

- Added immutable ORIGINAL/COPY sales-invoice artifacts over the existing published
  report-template renderer, with exact RustFS VersionId/size/SHA-256 fingerprints.
- Added READY/UNCERTAIN/PRINTED/FAILED print jobs and append-only events. Handoff
  becomes UNCERTAIN before bytes leave the API; only an explicit observed outcome
  resolves it, and another artifact is blocked while a job remains unresolved.
- Connected the existing posted-sale detail to a permission-aware invoice/print
  panel with stable retry identities, paginated history and exact PDF handoff.
- Fifty-two affected backend checks and fifteen focused frontend checks pass; the
  production build passes with existing warnings. Browser and Epson gates remain.

## 2026-10-05 - T09 pilot reserved handover and cost issue

- Added an internal one-transaction movement seam that consumes an exact owned
  reservation, reduces its stock bucket and appends the matching central-pool
  weighted-average `ISSUE` valuation.
- Added immutable `HANDOVER`/`ISSUE` contracts, predecessor/conservation guards,
  exact branch/pool authority, current permission and expected-version checks.
- Same-key retries have one effect and competing expected versions cannot reuse a
  hold or value. Serial stock fails closed pending exact identity movement history.
- Seventy-one focused stock/valuation/migration/fresh-install checks pass. No invoice,
  payment, collector, public collection action, transfer, return or live posting is enabled.

## 2026-10-05 - T12A payment and branch-account configuration

- Added versioned payment methods and exact selling-branch receiving-account
  mappings with immutable history, stable retries and scoped paginated APIs.
- Missing/disabled exact mappings block explicitly; no fallback account is chosen.
  A locked internal resolver revalidates exact versions for future T13 posting.
- Added a permission-aware Sales configuration screen with retained uncertain saves,
  server pagination and explicit readiness inspection. No money is posted.
- Synthetic tests introduce no real bank data. Paired backend PR #10 and frontend
  PR #9 passed CI and merged. Browser, accounting setup and pilot gates remain pending.

## 2026-10-05 - Public reviewed receipt posting boundary

- Added server-derived posting context plus an authenticated execution route that
  composes the existing approved receipt classification, version-pinned cost
  evidence, physical movements, weighted-average valuation and operation outbox in
  one transaction.
- The client supplies stable operation/case identities and an expected valuation
  version, but cannot supply a branch, cost pool, authority claim or monetary value.
  Missing exact mappings and disabled runtimes fail closed.
- Separate stock and financial permissions, staff/company access, evidence policy,
  store authority and central-pool authority rerun on every attempt, including
  replays. Uncertain retries retain one business effect.
- Fifty focused backend checks pass. Real runtime identities, object-retention
  policy and accounting reconciliation remain external release gates; controlled
  opening/import composition remains the last T08 code package.

## 2026-10-05 - T08 reviewed opening/import composition

- Added a public request/review/list/execute adapter for one exact opening or staged
  import row. It reuses active inventory policies, manager cases, server-derived
  stock/cost authority, the stock ledger and immutable pool valuation.
- One caller-owned transaction consumes the exact approval and records physical
  stock plus unreconciled SCR value. Product totals and selling prices are untouched.
- Centralised the posting-operation advisory lock for composite coordinators so a
  concurrent same-key retry cannot observe a half-finished source check.
- Fourteen opening/API tests and 72 affected ledger/posting/valuation tests pass in
  isolated PostgreSQL. After receipt-boundary integration, 134 combined T08/startup
  checks pass. Browser, real import data, reconciliation and retention gates remain
  open; this does not activate real financial posting.

## 2026-10-04 - Reviewed immutable cost-reconciliation checkpoints

- Added product/pool checkpoints that bind one latest valuation head and every
  current physical balance/version in mapped branches. Exact on-hand and pool
  quantities must agree in one base unit.
- Reused manager cases for separate request/review/close permissions. Close requires
  a current approval plus server-derived central cost authority and appends an
  immutable checkpoint without editing weighted-average history.
- Added server-paged case/checkpoint APIs and a permission-aware Cost pools workflow.
  Stale states, duplicate exact closes, foreign scope and missing runtime fail closed.
- Backend7/frontend18 focused tests and production build pass. This is not a T20
  accounting/till close, journal export or final external-retention acceptance.

## 2026-10-04 - Public receipt cost evidence review

- Added scoped receipt-cost request/list/review routes over the existing immutable
  receipt manifest and shared manager-case engine. Declarations retain exact source
  unit price, currency, SCR rate, justification and version-pinned PO/FX documents.
- Storage reads occur outside business transactions. Review and download recheck the
  complete current source/document binding; generic reads expose no private hashes,
  versions, keys or paths.
- Connected a Goods Receiving workflow with retained uncertain retries, independent
  review, listed-version decisions and reviewed-document downloads. Approval remains
  evidence-only and exposes no stock/value posting action.
- Backend49/frontend9 focused tests and production build pass. RustFS retention,
  final receipt execution, immutable reconciliation and browser acceptance remain.

## 2026-10-04 - Cloud-derived central cost runtime

- Added a server-owned cloud node identity that derives current cost-pool authority
  from persisted company scope and active epochs; clients cannot submit claims.
- Invalid cloud configuration, foreign ownership, suspension and stale epochs fail
  closed without local fallback. Explicit local-development compatibility remains.
- Routed existing reviewed charge context/posting through the shared server resolver.
- 64 authority/evidence/posting tests pass. No authority, business record or real
  financial post was created; receipt composition and external gates remain.

## 2026-10-04 - T08 reviewed exact stock adjustments

- Added request, independent review and confirmed execution over exact scoped
  location balances; reservations are preserved and serial aggregates are blocked.
- Execution uses server-owned authority, exact approval consumption and one immutable
  ADJUSTMENT movement. Database guards reject direct/unreviewed or mismatched writes.
- Added separate permissions, replay-safe migrations and a permission-aware Location
  Stock UI with stable uncertain retries and explicit reconciliation wording.
- 65 backend and 26 frontend focused tests pass; the production build passes with
  existing warnings. T08 remains open for opening/import and public receipt gates.

## 2026-10-04 - T08 authoritative product quantity readers

- Replaced product catalogue, lookup, export, low-stock and dashboard dependence on
  `Product.current_stock` with scoped Inventory balance summaries. Exact quantity
  categories remain separate and incompatible base units fail closed as unavailable.
- Removed legacy stock from product search documents and updated Product Master,
  quick view, selectors and the older order picker to consume authoritative fields.
- Replaced estimated catalogue-cost dashboard value with latest immutable cost-pool
  heads in SCR, explicitly provisional and coverage-aware.
- 63 focused backend and four frontend tests pass; the production build passes with
  existing warnings. No stock writer or financial posting was enabled; T08 remains
  open for reviewed adjustments/import/openings and public receipt gates.

## 2026-10-04 - T07 shared cloud reservation runtime

- Added a server-owned cloud stock runtime keyed by one configured node identity.
  It derives only active branch epochs owned by that node and reuses the existing
  locked posting-authority guard; clients cannot submit authority or business date.
- Routed same-store allocation, approved release and approved other-store execution
  through the same resolver. Invalid cloud configuration cannot fall back to the
  retained explicit local-development mode.
- Kept T21-T24 deferred: no offline enrollment, synchronization or failover was
  added. Unconfirmed release continues to reject confirmed/non-DRAFT demand.
- 66 focused isolated-PostgreSQL tests pass with existing warnings. T07 is
  Implemented—verification pending on browser and real runtime configuration gates.

## 2026-10-04 - Cloud-first sequencing and collaborator reassignment

- Recorded BD-20261004-10: current development targets one cloud-authoritative
  application. Existing offline-safe foundations remain, but T21-T24 expansion is
  deferred and no transparent internet-outage operation is claimed.
- Removed T24 from current cloud pilot/import dependency paths and made digital
  delivery depend on the cloud posting outbox rather than store synchronization.
- Replaced the collaborator's T21 package with bounded T12A versioned payment-method
  and branch receiving-account configuration. It is configuration/fail-closed
  lookup only, with no real bank data, money posting, balances or provider flow.

## 2026-10-04 - T11 reviewed floors and immutable transaction pricing

- Reused the shared manager-case engine for below-floor selling prices and bound
  every request/review to the exact draft revision plus canonical price/tax input
  fingerprint. Self-review, stale drafts/configuration and foreign scope fail closed.
- Added immutable `sales_transaction_pricing` records using the shared posting
  operation identity. They retain exact source/version/tax/total inputs and reference
  the approved floor case when required, without consuming it or posting a sale.
- Added read/prepare draft endpoints and usable sales-detail preparation plus a
  dedicated manager review screen. Permission-gated reviews no longer disappear
  merely because the reviewer lacks customer-facing draft access.
- 48 focused backend tests and 43 focused frontend tests pass. The production build
  succeeds with only the repository's existing unrelated warnings. Browser and real
  tax/accounting configuration acceptance remain pending.
- T11 is Implemented—verification pending. T13 must select the exact pricing snapshot
  and consume any floor case atomically with invoice, stock, money, numbering and
  outbox effects; financial posting remains disabled until those dependencies exist.

## 2026-10-04 - T11 versioned configuration, draft preview and frontend

- Added stable, tenant-scoped configuration identities with consecutive immutable
  revisions for tax rules, store/product/selling-unit prices, product tax assignment
  and customer/store/product/unit agreements. Stable operation keys protect retries.
- Kept tax separate from price lists and added no seeded rate, price, tax class or
  real business record. Selling unit is part of price/agreement identity.
- Added protected, paginated `/sales/pricing` reads and writes with independent
  customer/personal-data access for agreements and financial management for writes.
- Added read-only authoritative draft pricing preview with exact SCR gross/net/tax,
  selected source and versions, and an explicit below-floor approval requirement.
  It cannot post invoices, payments or stock.
- Added the Sales > Pricing & tax frontend with four registers, selectors and
  version-aware forms. 42 pricing/configuration/preview/API backend tests, 26 focused
  frontend tests and the production build pass; the build retains pre-existing
  unrelated lint and bundle warnings. Browser acceptance remains pending.
- Follow-up above implements reviewed floor approval and immutable transaction
  pricing. This earlier checkpoint did not enable financial posting.

## 2026-10-04 - T11 exact pricing and tax calculation foundation

- Added a pure exact-Decimal contract for tax-inclusive SCR, versioned selling-store
  prices, already-eligible customer agreements, tax snapshots and explicit floors.
- Lowest eligible price benefits the customer; same-price ties retain store price.
  Below-floor results require approval but are not silently raised or posted.
- Tax treatment is independent from price lists and keeps standard, zero-rated and
  exempt supplies distinct. Invoice gross is rounded once, then line/tax cents are
  allocated deterministically with exact gross = net + tax conservation.
- Official SRC material checked on 2026-10-04 states the current standard rate is
  15%, distinguishes zero-rated from exempt supplies and requires VAT to be shown
  separately on invoices/receipts. The calculator remains configurable and does not
  seed legal classifications or rates.
- Sixteen focused tests pass, including 200 deterministic invoices. Persistence,
  authoritative eligibility, reviewed floor execution and checkout remain T11 work.

## 2026-10-04 - T10 customer workspace automated verification

- Verified existing append-only customer profile/contact revisions rather than
  rebuilding them. Current and exact historical reads, newest-first history, stable
  retries, immutable rows, permission/tenant denial and migration replay pass.
- Two concurrent edits at the same expected version serialize on the stable customer
  identity and only one revision commits. Original identity and old sales references
  remain unchanged.
- Verified duplicate assessment request/review with exact profile versions, stable
  pair locks, stale-profile invalidation, independent reviewer and separate action
  permissions. Approval creates no manager-case use and never merges customers,
  contacts, sales references or balances.
- 53 affected backend and 23 focused frontend tests pass. The production build from
  this boundary succeeds with existing unrelated warnings. Browser/provider and
  durable ordered search-projection acceptance remain; T10 stays in progress.

## 2026-10-04 - Central reconciliation readiness inspection

- Added a tenant/pool-scoped, server-paginated comparison of current physical
  on-hand against each product's latest immutable valuation head.
- Explicit `MISSING_VALUATION`, `QUANTITY_MISMATCH` and `UNIT_MISMATCH` exceptions
  fail closed; exact quantity/value/head details remain read-only and financial-only.
- Added the comparison to the existing Cost pools / Valuation history workspace,
  with stale-response clearing, retry and explicit wording that agreement is not
  final accounting approval.
- 54 focused backend API tests and 22 focused frontend tests pass. The frontend
  production build succeeds with the repository's existing unrelated warnings.
- This is reconciliation readiness, not an immutable period close. Reviewed close,
  evidence retention, accounting export, synchronized completeness and runtime
  authority remain outstanding.

## 2026-10-04 - Evidence-bound receipt value and atomic posting

- Added an independent receipt-cost case bound to the official PO unit price,
  receipt-unit quantity, source currency, explicit SCR exchange rate and exact
  versioned PO-price/FX document fingerprints. Manifest creators cannot approve it.
- Reused the generic two-stage evidence preparation contract: original reviewed blob
  versions are hashed outside database transactions, then the whole binding is locked
  and revalidated before any stock or value effect.
- The official internal receipt coordinator derives SCR goods value from approved
  evidence; it accepts no client or adapter value. It atomically consumes both cases
  and the source, writes exact movements/value and records the durable event receipt.
  The lower raw-value composition seam has a distinct internal-only operation kind.
- 141 affected PostgreSQL tests pass, including exact derivation, replay permission
  and content checks, both-case rollback, pinned-version reads and the existing
  committed concurrency coverage. No HTTP action, real receipt or configuration was
  enabled. RustFS retention, runtime identity and reconciliation remain gates.

## 2026-10-04 - Atomic internal receipt coordinator

- Composed source/case consumption, source-bound movement, receipt valuation and
  the existing immutable operation/outbox envelope in one execute-once transaction.
- Separate stock and financial permission guards and both persisted authorities
  run on every attempt; lock order is central pool then branch then source/product.
- Committed two-connection tests prove same-key replay and one effect for competing
  distinct keys. Rollback restores case, source, movement, value and receipt.
- No public adapter exists. Versioned PO/source-currency and FX evidence must supply
  the exact reviewed SCR value before posting can be enabled.

## 2026-10-04 - Internal receipt valuation stream

- Extended the immutable pool valuation stream with source-bound `RECEIPT` rows;
  existing opening and charge histories migrate without value rewrites or backfill.
- Central pool authority precedes receipt locks. Exact source quantity, movements,
  branch mapping, base unit and prior pool/physical consistency are revalidated.
- Exact SCR goods value is distributed across receipt movements with stable
  largest-remainder arithmetic. Receipt rows can enter the existing reviewed
  additional-cost workflow; charges still cannot be reallocated.
- 120 affected backend tests and six focused frontend tests pass. The production
  build compiles with the repository's existing warnings. FX/evidence capture,
  public atomic receipt coordination, outbox and reconciliation remain pending.

## 2026-10-04 - Internal source-bound receipt movements

- Added a replay-safe schema extension for immutable `RECEIPT` stock movements,
  with no backfill and no public writer.
- Trusted branch authority is acquired before purchasing source locks. The movement
  helper then rebinds the current approved manifest, requires its same-operation
  source-use claim and appends exact location/batch/serial effects without committing.
- Database guards enforce source scope, complete quantities and condition deltas and
  reject direct receipt movements without a consumed source.
- Six focused PostgreSQL tests cover exact batch stock/replay, downstream rollback,
  replay permission and authority, lock-order short-circuit, direct bypass rejection
  and migration replay. Atomic valuation/outbox composition and committed concurrency
  remain pending.

## 2026-10-04 - Unsafe product-total adjustment retired

- The legacy adjustment route now performs permission/company/product checks and
  then rejects without float math, clamping, mutation, commit or search work.
- Removed all Product Master and quick-view controls that opened the direct writer.
- Ten focused prerequisite checks pass, including the former adjustment regression
  and catalogue create/edit boundaries. Production build passes with existing warnings.
- Controlled reviewed location adjustment remains T08/T09 work; no substitute total
  or automatic correction was introduced.

## 2026-10-04 - Internal receipt source-use capacity

- Added immutable receipt-line source-use history and a replay-safe migration with
  no backfill. Database guard binds company, manifest, exact base quantity and the
  matching consumed classification approval while locking the receipt line.
- Added an internal-only helper for a future outer physical posting transaction.
  It revalidates the current source, consumes approval and claims capacity without
  committing or creating stock, movement or valuation by itself.
- Seven focused PostgreSQL tests cover retry, replay permission/source revalidation,
  duplicate full-line denial, outer rollback, direct unapproved insert denial,
  foreign scope and migration replay.
  Complete concurrent movement/valuation composition remains pending.

## 2026-10-04 - Exact receipt manifest entry workflow

- Added read-only source and manifest previews under the existing Verify_Receipt boundary. They
  lock and revalidate the authoritative receipt, line, location and reviewed policy,
  converts to base units and runs shared conservation/identity rules, then releases
  locks without a write. Save repeats all checks; preview is never posting authority.
- Goods-receipt lines now expose their linked product identity through an eager-loaded
  PO-line relationship without supplier or pricing fields.
- Goods Receiving can select the line, paged branch/location, and reviewed policy,
  retain exact failed input and retry identity, validate, and save a non-posting
  manifest. Batch/serial controls are shared with stock reclassification.
- Twenty-seven focused backend checks and fourteen frontend checks pass. The production
  build passes with existing warnings. Browser acceptance remains pending.

## 2026-10-04 - Public receipt proposal and classification review boundary

- Added stable-key proposal save under Verify_Receipt and request/list/decision routes
  using the existing manager-case engine and Inventory/Orders/view guards.
- Request-only users can see only their requests; wider/needs-review views require
  review authority. Creator/requestor independence, current-source rebinding, tenant
  scope and replay protection are enforced on every attempt.
- Case paging projects metadata without loading identity-heavy binding JSON and uses
  a replay-safe partial scope/source index. Review never consumes the case or stock.
- Goods Receiving retains failed review input/identity, blocks accidental panel exit,
  and exposes no physical or financial posting control. Twenty-eight backend and seven
  frontend tests pass; production build passes with existing warnings.

## 2026-10-04 - InFlow-informed Sales draft presentation

- Applied BD-20261004-09 to the existing register/detail/editor components: dense
  customer/store/Draft vN identity, secondary exact UUID and compact saved context.
- Demand, line reservations, payment and collection are separate facts. Pricing is
  pending/not calculated; no invoice, money, handover or new save action was added.
- Product lines retain image, SKU, exact quantity/unit, base quantity, policy and
  protected reservation facts; current permissions/search/history/recovery remain.
- Twenty-four affected frontend tests and production build pass with existing warnings.
  Browser/dark-mode acceptance and authoritative T11-T17 integration remain pending.

## 2026-10-04 - Read-only receipt manifest inspection

- Added scoped, paginated manifest summaries and exact UUID historical reads under
  the existing Inventory/Orders permissions; deleted and foreign parents stay hidden.
- Responses whitelist classification metadata and exact quantities, exclude supplier/
  price data and remain private/no-store. No write or posting route was added.
- Goods Receiving now offers an explicit saved-manifest inspector with cancellable,
  context-validated reads and contained modal scrolling. Saved is labelled not posted.
- Seven isolated backend and four focused frontend tests pass; production build passes
  with existing warnings. Browser acceptance and public create/review remain pending.

## 2026-10-04 - Receipt manifest manager-case binding

- Reused request_case/review_case with exact persisted manifest/source binding.
- Receipt creator cannot review via a proxy requester; engine also blocks requester
  self-review. Policy/source changes reject request/decision/replay binding.
- Eight isolated review/store tests pass. No case consumption, public endpoint,
  financial approval or physical receipt effect is enabled by classification review.

## 2026-10-04 - Durable immutable receipt manifests

- Added append-only manifest proposal table with source references, deferred
  shared-operation FK, exact company/parent insert guard and mutation rejection.
- Save reuses execute_once and prepared source, rechecking access/source on retry.
  No source-use reservation or stock effect is inferred from SAVED.
- Replay-safe empty-table migration registered; no stock backfill or activation.
  PostgreSQL guidance informed indexes and scoped FK/trigger boundaries.
- Isolated tests cover replay, changed source, permission, rollback, immutable
  rows, foreign insert and migration replay. Evidence in receipt-manifest-store.

## 2026-10-04 - Receipt manifest conservation shares inventory validators

- Extracted reusable validate_stock_manifest from existing reclassification
  validation; old conversion restrictions remain intact in their caller.
- Internal full-line receipt manifest uses existing batch/serial schemas, exact
  condition quantities and prepared source. Rejects quantity mismatch, inconsistent
  condition totals, duplicate identities and observed damage made available.
- No persistence, approval, source consumption or stock/valuation posting added.
  Partial/multi-location receipt composition remains subsequent integration work.

## 2026-10-04 - Guarded physical receipt source preparation

- Added internal typed receipt-line/location selection and caller-transaction
  preparation over existing GoodsReceipt/ReceiptItem/POItem/product/policy records.
- Requires submitted posting-v1 purchasing source, exact company/parent/product,
  active receiving location and current reviewed units. No float quantity inputs.
- Retains damaged/incorrect quantities without inventing saleable stock or costs.
- 27 isolated PostgreSQL tests pass including existing unit/source tests. No new
  public route, migration, stock writer or UI enabled; manifest/consumption next.

## 2026-10-04 - Catalogue creation cannot establish inventory

- Create-product API rejects nonzero/nonfinite opening totals after Add_Product
  permission check and before writes. Zero/null/omitted create only catalogue data.
- Constructor always initializes zero; quick-create UI no longer sends stock.
- Prerequisite suite48 pass /1 remaining adjustment xfail, including compatibility
  and rejection cases. This is not a replacement receipt/opening workflow.

## 2026-10-04 - T08 legacy writer audit and metadata stock bypass closure

- Audited current_stock writers/readers and purchasing receipt service; canonical
  LEGACY-STOCK-WRITER-AUDIT.txt records remaining paths and receipt integration.
- Product metadata rejects stock replacement and no longer whitelists the field;
  product form omits it and shows a read-only legacy reference, not editable stock.
- C12 metadata regression now passes for positive/zero/negative/same-value writes.
  Affected backend59 pass /1 remaining adjustment xfail; build evidence recorded.
  Receipt/valuation composition and nonzero creation remain outstanding.

## 2026-10-04 - Readable Sales branch and saved-revision attribution

- Current draft read includes current scoped branch label and immutable revision
  timestamp/actor reference; saving actor is not an assigned salesperson.
- Register/detail reuse a bounded branch-label lookup. PostgreSQL guidance informed
  primary-key page lookups; deleted/foreign labels are omitted, never substituted.
- Editor displays label but local recovery remains reference-only. No schema or
  business-write changes. Forty affected backend tests pass; UI evidence recorded
  in planning/evidence/20261004-sales-metadata.txt.

## 2026-10-04 - Read-only portrait checks and narrow editor repair

- Inspected saved historical lines and current draft in existing demo company.
- Found390px editor cart collapsed beneath fixed metadata. Added contained body
  scrolling with minimum pane height, retaining fixed Save/Cancel and tablet layout.
- Browser recheck confirms390/768px body containment and visible cart controls.
  Ten affected frontend tests pass. No record/settings writes or acceptance bypass.

## 2026-10-04 - Sales route navigation recovery guard

- Existing draft recovery now gates sidebar/programmatic and Back navigation via
  one app-shell data-router blocker. No duplicate persistence or backend changes.
- Recovery failure and in-flight/confirmed-cleanup states prevent leaving; exact
  uncertain intent remains retained, without an additional API save.
- 291 frontend tests / 55 suites pass, including real-router nested route/Back
  integration; production build passes with existing warnings. Native reload,
  multi-tab and browser appearance remain separate acceptance gates.

## 2026-10-04 - Read-only saved Sales revision lines

- Extended existing scoped draft reader; no duplicate history store or schema.
- Historical lines retain saved quantities/units/policy versions and omit current
  reservations. Catalogue labels are explicitly current; customer names are pinned.
- UI Inspect version is read-only, cancellable and rejects mismatched responses;
  current-draft mutation actions hide while history is active.
- 39 affected backend and 10 focused frontend tests pass; build passes with known
  warnings. Browser/final design acceptance remain separate gates.

## 2026-10-04 - Scoped Sales register search

- Reused Meilisearch client for reference/saved-name search with company/store scope.
- Page-bounded authoritative reads reject stale versions and foreign/malformed hits.
- Post-commit indexing and receipt status preserve confirmed-save recovery; startup
  rebuild is bounded, durable ordered projection repair stays with T22.
- 38 affected backend tests and 15 frontend tests pass; production build passes.
  Synthetic provider smoke finds three drafts. Browser acceptance remains pending.

## 2026-10-04 - T33A integration safeguards for next assignment

- Owner requested applying the cleaned-up T33A failure patterns to T21 handoff.
- Assignment revision 2 requires source-contract inspection, exact revision pairing,
  scoped resource/permission tests, retry/partial-success recovery and minimal diffs.
- Added staged implementation checkpoints and mandatory reproducible PR manifest.
- No runtime/code changes or new tests required for this documentation-only change.

## 2026-10-04 - Reconciled plan and paired GitHub UI checkpoint

- Replaced stale T14B-D next actions with current implementation, test evidence
  and remaining acceptance. Roadmap revision 4.3 and screen map now reflect
  resumed tests, integrated T33A and the approved module navigation.
- New collaborator package: bounded T21 isolated local packaging, with separate
  ports/volumes and no shared-runtime/posting/permission changes without review.
- CHECKPOINT-20261004-UI.txt pins matching repositories; historical manifests
  retain historical revisions. No merge, deployment or real posting authorised.

## 2026-10-04 - Owner-approved module navigation arrangement

- Reorganised existing sidebar without new routes or backend permission changes.
- Sales/Customers and Inventory/Counts precede Procurement, Logistics, Reports
  and Administration. Reservation reviews grouped; policy approvals disambiguated.
- Preserved Orders access on packing lists after moving its link to Logistics.
- Customer/count deep links restore their own accordions. Template Studio is an
  administration link, leaving Overview directly accessible.
- Focused menu regressions cover grouping, permissions and route restoration.
  Browser acceptance for the revised whole menu remains pending.


## 2026-10-04 - Owner-requested populated Sales and Counts demo

- Added explicit local-only workflow seed reusing customer, draft, count and case
  services inside one transaction. No duplicate business engines or direct ledger
  inserts. PostgreSQL guidance informed scoped lookups/transaction lock and moving
  search indexing outside the transaction.
- Four focused tests pass: repeatability, rollback, scope, blind sheets, unchanged
  stock and rejected database destinations. Local preview seed applied twice;
  second run created nothing. Two synthetic customers indexed successfully.
- Existing demo company only: 3 drafts (one with revision history), 3 plans,
  2 rounds and 2 pending discrepancy reviews. No real financial posting enabled.

## 2026-10-04 - Full verification resumed and build repairs

- Owner resumed full tests and read-only Sales/Counts tablet checks. Backend:
  1325 passed/2 legacy xfailed; frontend: 273 passed/52 suites; build passed with
  existing warnings. Isolated empty-database startup and replay passed, providers
  intentionally unavailable. See planning/evidence/20261004-full-build-verification.txt.
- Declared BigInt to CRA lint without changing arithmetic; aligned test mocks,
  route assertions, thumbnail contract and caller-owned transaction setup.
- Isolated _test database names supported by demo seed only in test environment;
  added negative guard cases. No production authentication or posting changes.
- Browser checked empty Sales/Counts and unsaved draft layout; populated/hardware
  gates remain. Local repairs not pushed; no whole-task acceptance claimed.

## 2026-10-04 - Owner-authorised T33A integration and repairs

- Selectively imported count implementation from backend b6f888e/frontend4b6705f;
  retained current sales/runtime work and omitted unrelated notification changes.
- Unified assignment/recount company validation; exact review retries retain the
  immutable binding and return the existing receipt without a second review row.
- Count UI uses authenticated userId, locks uncertain entries, warns on discard
  and distinguishes confirmed save from failed sheet refresh. Warehouse selectors
  use count permissions and shared catalogue projection, not Sales/PII guards.
- Wired count migrations/router/permission catalogue/menu locally. Regression
  coverage written; no tests/build/browser, push or whole-branch merge performed.

## 2026-10-04 - Sales draft revision-history metadata

- Added read-only /sales/drafts/{key}/history with existing module/read/privacy
  guards, exact company scope and bounded newest-first paging. Reuses immutable
  revisions and saved customer profile labels; exposes no operation or money data.
- PostgreSQL skill informed reuse of the org/document/version unique index and
  bounded customer projection. No schema migration or duplicate audit store.
- Existing detail pane now opens cancellable, paginated history on explicit click.
  Added API/UI regressions without execution; tests/build/browser remain deferred.

## 2026-10-04 - Compact split-view draft register

- Extracted presentation-only SalesDraftRows: full table without a selection,
  stacked compact rows beside details. Same page, data and read callback; no
  client filtering, duplicated fetch or writes on selection.
- Preserved reference/customer/version/store/status/action in both modes; added
  labelled touch targets and current selection semantics. Full table scrolls
  within its existing container instead of compressing every column.
- Tests written, not run. Responsive/browser and production build gates pending.

## 2026-10-04 - Accessible draft validation

- Shared exact quantity syntax between save validation and touch controls.
  Invalid input is retained rather than parsed, rounded or coerced.
- Field-linked errors identify missing sources/invalid quantities; failed local
  validation opens the cart and focuses its first invalid quantity before any API
  write. Server unit-policy validation remains authoritative.
- Regression cases added without execution. Tests/build/browser remain deferred.

## 2026-10-04 - Separate confirmed draft receipt from local cleanup

- Editor retains validated server receipt when local recovery deletion fails.
  Explicit cleanup retry never calls save again; mutations stay locked.
- Original recovery is retained and deletion remains revision checked. Reload
  can still replay its original idempotent operation; no new storage contract.
- Mismatched receipts remain uncertain. Added regressions, not executed; no
  tests/build/browser checks. T33A handoff records collaborator still developing.

## 2026-10-04 - Exact tablet quantity controls

- Added selected-unit +/- controls to existing cart using scaled integer arithmetic,
  preserving six-place quantities and bounds. No implicit removal or stock effect.
- Invalid partial input and pending/conflicted saves disable nudges. Functional
  updates avoid lost rapid taps; server unit validation remains authoritative.
- Added arithmetic edge coverage, not run. No build/browser verification.

## 2026-10-04 - Sales capability map and T33A remote review

- Completed T14A documentation map against routes/components; design approved.
  This is not UI implementation acceptance or an automated test claim.
- Live remote review located frontend T33A commit3260838. Backend counterpart
  remains unidentified; recorded count identity, warehouse-selector and pending
  save issues in evidence/t33a-integration-review.txt. No merge/overwrite.
- Independent sales work remains ready. No tests/build/browser or deployment.

## 2026-10-04 - Correct recovery and review actor identity

- Found login supplies username string while draft recovery consumed user.id.
  Added policy-derived user_id to access response and resolved-context userId
  to frontend, retaining legacy display user. Updated sales/customer/inventory props.
- Missing numeric identity blocks sales instead of guessing a local recovery scope.
  Server permissions unchanged. Added regression and adjusted sales auth fixture.
- No tests/build/browser run. This repairs a concrete integration gap, not a claim
  that browser recovery or self-review acceptance has passed.

## 2026-10-04 - Signed thumbnails across the sales workspace

- Reused blob signing for bounded scoped catalogue/draft reads; only product-image
  keys yield URLs. No private storage keys or external-document fallbacks.
- Added shared lazy picker/cart/detail image component with missing-image fallback.
  Recovery remains a whitelist without URLs or customer names.
- Added signer boundary tests without execution. No build/browser/provider
  verification, uploads or business changes; T14B-D acceptance remains pending.

## 2026-10-04 - Barcode entry in shared draft editor

- Reused Inventory barcode resolver and active-policy read for explicit scanned
  unit selection. No new endpoint, barcode catalogue or stock/payment writer.
- Preserved leading zeros, exact retry/recovery boundaries and disabled-cart
  guards. No legacy fallback; unresolved scans add nothing.
- Added frontend coverage without execution. No tests/build/browser or hardware
  checks run; images and T14D acceptance remain unfinished.

## 2026-10-04 - Shared product/cart draft workspace

- Embedded the existing paginated product picker into SalesDraftEditor beside
  the current cart; narrow layouts switch views while retaining mounted state.
- Reused recovery, exact save intents and locks; no second cart or fake checkout.
  Product controls respect uncertain saves, conflicts and line limits.
- Added embedded-picker coverage, not run. Images/scanning and acceptance remain;
  no build/browser checks or business records created. T14D is in progress.

## 2026-10-04 - Version-pinned customer display names

- Added bounded historical-name projection shared by sales list/detail, reusing
  customer identity/profile revisions and exact company/permission guards.
- PostgreSQL guidance informed batching and indexed identity/version probes;
  no N+1 customer reads or contact/balance data loaded for labels.
- Frontend register/detail show saved customer names without rewriting source
  versions. Added historical-name regression coverage, not run. No build/browser.

## 2026-10-04 - Scoped sales store filtering

- Added exact branch filtering before register count/page and a bounded store-name
  projection. Reused company guards and existing org/branch index; no migration.
- Frontend reuses branch picker and current client; clears page on filter changes.
  PostgreSQL guidance informed bounded reads and existing-index inspection.
- Added API filter/pagination/foreign-company coverage, not run. No tests/build,
  browser verification or real business effects. T14B remains in progress.

## 2026-10-04 - Approved sales register/detail composition

- Frontend now composes the existing paginated sales register with an extracted
  read-only detail pane, responsive focus and fixed explicit action footer.
- Reused all permission-gated allocation/reservation/edit callbacks; no new API,
  posting, mock data or inferred commercial status. Preserved exact unit details.
- Route guard preserves an opened overdue-inbox draft. Component tests added,
  not executed; tests/build/browser remain deferred. T14B/C remain in progress.

## 2026-10-04 - Full roadmap review and persistent execution boundary

- Read all phase groups and audited 44 queue IDs: no missing dependencies/cycles.
  This is a read-only planning audit, not a backend/frontend verification run.
- Clarified independent slices versus full acceptance, coordinated T06/T08 receipt
  integration, and T21 readiness. Removed remaining pending-design roadmap wording.
- Retained T33A ownership and unresolved reported remote revisions, no rebuild.
  Goal covers authorised local implementation with deferred gates, not live release.
- Documentation only; tests remain deferred, no application changes or deployment.

## 2026-10-04 - Owner approved sales visual direction

- Recorded BD-20261004-03 for all three proposed layouts. Resolved the visual
  gate in queue/roadmap/handoff and made T14B Ready; T14A mapping continues.
- Inspected existing sales routes/client and recorded available controls versus
  later payment, collection, print and copy capabilities. Register list currently
  supports page/limit, so richer filters need backend support rather than fake UI.
- Documentation only; no application change, tests, browser checks or deployment.

## 2026-10-04 - Align phase roadmap and T33A presentation

- Added versioned PHASE-ROADMAP.txt mapping historical Cxx phases to current
  Txx tasks; canonical queue remains the only status ledger. Historical workspace
  plan points to it and corrects obsolete allocation and early-pilot sequencing.
- BD-20261004-02 aligns T33A register/detail/tablet presentation without changing
  count protections, ownership or adding stock posting. Existing work is reused.
- Documentation only; designs still await approval. No tests, code changes,
  browser checks, collaborator notification, Git push or deployment performed.

## 2026-10-04 - Design-first sales queue revision (documentation only)

- Owner requested adapting the queue to three proposed inFlow-inspired screens.
  Added T14A confirmation/action mapping, T14B register, T14C desktop workspace,
  T14D tablet draft presentation and T14E integrated acceptance; T14 retains full
  backend-gated checkout. Preserved task IDs, existing work and T33A ownership.
- Recorded BD-20261004-01 and aligned collaborator handoff; reconciled T10's
  obsolete duplicate-review-next wording with its implemented unverified screens.
- Concepts are not approved UI or working features. Reuse current APIs/components,
  keep tab navigation read-only and retain business/permission/recovery contracts.
- No application edits, tests/build/browser actions, posting or push performed.
  Design approval and deferred verification remain explicit gates.

## 2026-10-04 - Restore earlier sales UI without reverting functionality

- Owner requested matching earlier sales design. Reused frontend RegisterShell
  from03678ed and restored route-based Sales sidebar including newer other-store
  reviews. Updated register/editor surfaces and Super Admin menu eligibility.
- Preserved current source, allocation, case execution and recovery contracts.
  No backend business changes, tests/build/browser run or external deployment.

## 2026-10-04 - Owner-authorised local demo entry

- Added opt-in passwordless entry for the existing demo-t05-reviewer only, with
  development environment, exact preview database, loopback host and frontend
  origin guards. User must remain non-platform and limited to one DEMO ONLY org.
- Reused normal token/refresh/session-audit issuance and all backend permissions.
  No administrator bypass or role grant. Local compose keeps API bound to loopback.
- Login offers an explicit demo button only on a development loopback frontend
  after backend capability confirmation. Production builds hide the button.
- Enabled only in the local runtime compose and recreated its API container;
  no databases deleted, no external deployment. Automated tests remain deferred.

## 2026-10-04 - Duplicate customer request and review screens

- Reused customer selection and shared ManagerCases instead of a second register
  or approval engine. Exact historical profile comparison precedes decisions.
- Added explicit assessment/reason, scoped permissions, retained receipts and
  frozen uncertain intents. No balance merging, identity retirement or execution.
- No tests/build/browser run at owner request; full T10 is not marked complete.

## 2026-10-04 - Protected duplicate assessment endpoints

- Added request, paginated list and independent review to the existing customer
  router with separate action permissions plus personal-data scope enforcement.
- Reused manager-case page/metadata and exact-profile binding; request-only users
  see their own requests. Approval has no merge, account or stock side effect.
- Customer frontend client now exposes these endpoints. Screen integration next.
  No tests/build/browser run; all new work remains verification pending.

## 2026-10-04 - Duplicate customer assessment foundation

- Added a typed exact-version pair request and scoped binding loader with stable
  lock ordering. Reused manager-case request/review and replay protection.
- Approval means agreement with an assessment, never merging or reassignment of
  identities, historical sales, contacts or money. No execution path exists.
- Public permissions, case list/API and frontend next. No tests/build/browser run;
  this internal implementation is verification pending and T10 remains in progress.

## 2026-10-04 - Customer profile API, search and UI integration

- Connected scoped profile/history endpoints, current paginated projections and
  historical reads. Sales draft creation pins the current customer version under
  lock; existing references remain immutable.
- Registered migration and shared sales reference guard; startup search repair
  uses current profiles, and replay projection avoids restoring the initial one.
- Reused customer form for versioned edits with a required reason; added paginated
  history from View details. Stale edits block resubmission until reopened.
- No tests/build/browser or explicit migration execution. Deferred checks include
  auth/tenant isolation, concurrent edits/retries, rollback, old sales snapshots,
  migration replay, UI recovery and search projection ordering. T10 not complete.

## 2026-10-04 - Customer profile revision service foundation

- Extended the existing customer identity with an internal append-only edit service,
  exact/current profile reads and paginated history. Original identity is unchanged.
- Reused operation receipts and scoped parent locks, with stale-version rejection
  and permission checks on retries. No automatic customer or balance merging.
- PostgreSQL guidance informed indexed version queries and short transactions;
  no network calls occur inside this service.
- Incomplete integration: migration startup, API/search/sales and frontend next.
  No tests/build run at owner request; no release-readiness claim.

## 2026-10-04 - Disabled-by-default central cost execution adapter

- Added explicit local central claim configuration, separate from stock branch
  runtime, with pinned company/pool/node/epoch and no automatic activation.
- Connected existing persisted-case/evidence preparation and atomic charge posting
  through protected typed APIs. Fresh permissions checked after storage I/O.
- PostgreSQL skill informed bounded indexed product-version lookup and short DB
  transactions; no schema/index migration or storage configuration change needed.
- Evidence review frontend now has separate confirmation/retry/result UI for
  version-pinned approved costs. No price, payment or final-account effects.
- No tests/build/browser checks run per owner request. Entire slice unverified:
  planning/evidence/t06-local-cost-runtime.txt. Receipt costing/reconciliation remain.

## 2026-10-04 - Approved reallocation runtime and frontend

- Reused atomic paired release/reserve with a distinct execution permission and
  exact case-derived scope. Shared reviewed-stock runtime lookup avoids duplicating
  authority selection. Settings version now binds the parent posting fingerprint.
- Reused frontend context/confirmation and retained result, including execute-only
  case access. No physical transfer or paid-hold eligibility introduced.
- No tests/build/browser checks run per owner instruction. Entire slice unverified;
  evidence: planning/evidence/t07-reallocation-runtime.txt. T33A unchanged.

## 2026-10-04 - Other-store execution adapter and control

- Added separately permitted context/execute endpoints using approved immutable
  scope and the existing reserve_stock transaction; no client authority or stock choice.
- Target-calendar resolver reuses existing date rules and locks versioned settings;
  receipt includes settings version. No real runtime configuration or data changed.
- Shared manager confirmation now handles exact other-store execution with retained
  results, company-pinned access and stable retry intent.
- Owner requested no tests: this entire slice is unverified; build/browser and
  existing other-store no-execution UI assertions need follow-up when tests resume.
  Evidence: planning/evidence/t07-other-store-runtime.txt. Continue reallocation.

## 2026-10-04 - Public approved release connection

- Reused release_stock and configured local runtime behind separate execution
  permission and exact scoped approval. Client supplies only operation identity.
- Reused ManagerCases/PolicyActivation for explicit confirmation, execute-only
  inspection and a retained release receipt; no financial or handover effect.
- Before owner stopped tests: 21 affected backend and 35 frontend tests passed.
  Subsequent receipt/default-view refinements are untested; no build run. Further
  tests are deferred by owner request, not waived for eventual completion.
- Evidence: planning/evidence/t07-release-runtime.txt. Runtime stays disabled;
  other-store execution/reallocation adapters remain next. T33A untouched.

## 2026-10-04 - Same-store allocation screen

- Added self runtime/assignment context read and usable saved-draft allocation
  screen using existing counter picker, exact strings and operation intents.
- No authority/date overrides, user-directory access or operational activation.
  Unknown retries stay identical; stale changes block replacement; dirty exit warns.
- Backend31/frontend15 focused tests and build main.dfa28a45.js pass with existing
  warnings. Browser acceptance pending. Evidence: planning/evidence/t07-store-allocation-ui.txt.
- T33A still awaits the collaborator's exact PR/branch; no unrelated branch merged.

## 2026-10-04 - Paired GitHub checkpoint

- Reviewed changed/untracked files; no private documents, runtime credentials,
  databases or generated artifacts included. Both repository webhook lists empty;
  checked-in workflows run tests/build/fresh-install only.
- Full local checkpoint: backend1298 passed, 2 known legacy xfails; frontend230
  passed across44 suites; production build succeeds with existing warnings.
- Paired revisions and unfinished UI/runtime gates: planning/CHECKPOINT-20261004.txt.
  Publish task branches and linked PRs; no direct integration overwrite/deployment.

## 2026-10-04 - Local runtime resolver and same-store allocation API

- Added fail-closed operator-configured local identity with pinned branch epochs;
  no client identity, owner discovery, auto-enrollment or active environment change.
- Added typed same-store allocation endpoint using existing calendars, settings,
  staff assignment, permission guards and atomic stock allocation. Both sales and
  inventory modules are required. No role grants seeded.
- 22 focused API/runtime tests pass, including split/replay, permissions, tenant,
  module/authentication, forged authority/date, stale settings and disabled runtime.
- Frontend allocation control remains next; no new frontend build claim.
  Evidence: planning/evidence/t07-local-runtime-allocation-api.txt.

## 2026-10-04 - Atomic approved other-store stock hold

- Extended reserve_stock rather than adding a parallel ledger or posting engine.
  Exact request/assignment/stock/history binding and independent case consumption
  are required; ordinary source validation still rejects other stores.
- Retained target-node authority, batch expiry, source caps and compatible lots.
  Existing local holds remain unchanged. No same-bucket supplement bypass.
- Replay normalizes only its unchanged committed effect. Concurrent identical
  requests return one receipt; failure after approval consumption rolls it back.
- 58 affected backend tests pass, 23 existing dependency warnings. No frontend
  changes/build rerun this slice; prior request-entry build remains the evidence.
- Public trusted-runtime adapter remains next, not enabled. Evidence:
  planning/evidence/t07-other-store-execution.txt.

## 2026-10-04 - Explicit other-store request entry

- Added self-only current working-store read with existing membership/version
  checks and no user-directory permission or exposed credentials.
- Added optional product filter before stock count/pagination, reusing existing
  location/product indexes as guided by the PostgreSQL skill; no migration.
- Sales draft detail now opens exact line/store/location/stock selection using
  the shared picker. Quantities remain strings; unknown outcomes freeze intent
  for identical retry. Stale state blocks replacement and dirty exit asks first.
- Backend22/frontend27 targeted tests and production build pass; existing build
  warnings remain. Request/review posts no stock; trusted execution is next.
  Evidence: planning/evidence/t07-other-store-request-entry.txt.

## 2026-10-04 - Other-store review API and sales queue

- Added protected typed request/list/review endpoints using the existing manager
  case engine, original requestor assignment and exact saved demand/stock binding.
- Added explicit request/review permissions without granting roles. Bounded reads
  expose only approved fields and exclude the internal hold digest.
- Sales drafts has Other-store reviews through the shared ManagerCases component;
  approval does not post and no activation control is available.
- Focused verification: 18 backend tests, 26 frontend tests and production build
  passed (existing warnings). Request-entry and trusted execution remain pending.
  Evidence: planning/evidence/t07-other-store-review-api.txt. No browser checks,
  business records, deployment or push.

## 2026-10-04 - Exact other-store fulfilment review foundation

- Added an internal authoritative binding loader for an explicitly chosen other
  store/warehouse bucket. Same-company demand, staff assignment, quantity, stock
  version and compatible existing holds are bound to the existing manager case.
- Reused the history reader with server-derived branch compatibility for review;
  ordinary reallocation still defaults to one branch. No public bypass flag.
- PostgreSQL guidance informed branch/user/document/source/stock lock ordering.
- Request and independent-review tests confirm no stock effect, stale version and
  assignment rejection, combined cap, shortage and foreign-company denial.
- Public APIs, frontend and execution remain next, not declared complete.
  Evidence: planning/evidence/t07-other-store-review-foundation.txt.

## 2026-10-04 - Reviewed supplements across compatible target locations

- Removed the target-history single-bucket restriction for same-store matching
  product/unit/tracking/batch. Actual release/reserve stays in its original bucket.
- Exact streamed history digest now binds bucket IDs, all quantities and follow-up
  versions; changed destination history invalidates approval and combined caps hold.
- Retained paired-release proof, immutable history and deferred SQL segment guard.
  No generic bypass, cross-store exception, physical transfer or paid-hold support.
- Updated request/review explanations. PostgreSQL guidance informed scoped history
  join and streaming under the existing document locks; no migration required.
- Verification evidence: planning/evidence/t07-multi-location-supplements.txt.
  No browser acceptance, real business records, deployment or external push.

## 2026-10-04 - Authorised working store separated from usual counter

- Added immutable staff/store assignment revisions, scoped foreign keys, counter
  branch guard and replayable empty migration using existing posting receipts.
- Effective company membership and branch-before-user locks protect assignment
  changes; automatic allocation requires the current assignment version on replay.
- Paginated API exposes username/assignment only, guarded by user/product viewing
  and separate user-edit/branch-settings permissions for writes. No role grants.
- Added Staff working stores from branch workspace; optional counter, explicit
  store reassignment, enabled state, version conflict and identical uncertain retry.
- PostgreSQL skill informed indexes, projected membership reads and short locks.
  Backend66/frontend36 focused tests and build passed; preview/API200, browser pending.
  Evidence: planning/evidence/t07-staff-store-assignments.txt. No real data or push.
- Continue trusted runtime/public reservation integration and explicit other-store
  exceptions. Multi-bucket reviewed supplements remain a separate unfinished slice.

## 2026-10-03 - Store-wide selling with optional picking preference

- Recorded BD-20261003-06 superseding the counter-area restriction; queue and
  collaborator handoff updated. T33A ownership unchanged; no external publication.
- Optional null preference is valid. Frontend settings/inspection distinguish
  workstation/specialism from authorised store and staff/stock permissions.
- Internal initial allocator composes existing deterministic stock children and
  atomic receipts, searches compatible store-wide stock and keeps batch identity.
  Source-linked splits enforce aggregate demand caps; no generic/supplement bypass.
- Centralised saved-demand loading rather than duplicate locking/version checks.
  PostgreSQL skill informed indexed candidate filtering, streaming, stable locking
  and transaction-only effects. No schema changes or new stock ledger.
- Backend127/frontend22 affected tests and production build pass; existing warnings.
  Evidence: planning/evidence/t07-store-wide-allocation.txt. Both previews HTTP200.
- Remaining: persisted staff/store assignment, trusted public runtime adapter,
  explicit other-store workflow, multi-bucket reviewed supplements and paid sources.
  No whole-T07 completion, browser acceptance, real posting, deployment or push.

## 2026-10-03 - Counter area boundary and read-only scope screen

- Continued on separate codex/local-area-scope task branches; T33A remains owned
  by the collaborator. No integration-branch overwrite or external push.
- Resolver rechecks exact counter/branch/version and active ancestry, retaining
  branch lock against settings changes. Added bounded active descendant read.
- Frontend Counters -> View stock area shows scope, not availability or posting;
  stale/failed reads clear data and company changes abort obsolete requests.
- PostgreSQL skill informed indexed parent probes and short scoped transactions.
- Backend48/frontend21 focused checks and production build passed; preview200.
  Evidence: planning/evidence/t07-counter-area-scope.txt. Browser checks pending.
- Next: persisted salesperson work-context assignment and automatic allocation
  composition. No new staff assignment, real records, financial or stock posting.

## 2026-10-03 - Shared GitHub checkpoint and revised collaborator assignment

- Added owner-approved AGENTS reading protocol, canonical business decisions and
  handoff; frontend points to backend records rather than duplicating the plan.
- Corrected stale T10/no-customer and no-sales-consumer statements. Collaborator
  owns new T33A count planning/blind entry/recounts/review, not T10. Stock posting,
  movement reconciliation and price labels remain gated by later dependencies.
- Documented protected interfaces, paired PRs, independent services/ports and
  contributor setup confirmation. Another machine's environment is not verified.
- Integration run exposed legacy blob-test auth module leakage at collection;
  restore original modules after isolated router loading. No production auth change.
- Checkpoint results and push/CI evidence: planning/evidence/20261003-parallel-checkpoint.txt.
  No browser checks, real business mutations, deployment or pilot activation.

## 2026-10-03 - Default local work-area allocation rule and counter setting

- Owner clarified automatic allocation within the salesperson's current area;
  alternative areas are chosen explicitly, not silently substituted on shortfall.
- Added optional location root to immutable counter JSON configuration; scoped
  server validation and missing/stale-default resolver. No data backfill/migration.
- Reused paginated picker in counter settings; no manual location ID entry needed.
- Fixed SalesIntent's missing referenced-customer model registration discovered by
  isolated counter tests. Backend20 and frontend13 focused tests pass.
- Actual work-context assignment and default-area planning/posting remain next;
  counter configuration does not activate stock posting. Browser checks pending.

## 2026-10-03 - Reviewed supplements preserve original hold segments

- Same-bucket destination demand may already have holds. Reviewed reallocation
  appends a separately attributed hold; original quantities/deadlines stay intact.
- Indexed streamed target history binds exact quantities, attribution and schedule
  versions. Combined demand cap and shared locks reject competing/stale approvals.
- Reused reserve effects with exact consumed-parent/paired-release proof, not a
  boolean exception. Replayable migration replaces obsolete uniqueness with a
  deferred paired-reallocation guard and protects historical reservation identity.
- Frontend requests explain segments; reviews show pre-request destination totals.
- Affected backend110/frontend38 tests and build pass with existing warnings;
  evidence: planning/evidence/t07-reservation-segments.txt. Browser checks pending.
- Continue explicit multi-location approval and trusted runtime integration; paid
  source adapters depend on later sales posting. T07 is not complete.

## 2026-10-03 - Atomic reviewed reallocation and review workspace

- Reused stock effects, manager cases and receipts for a same-bucket draft-demand
  reallocation. Paired immutable history requires exact destination and approval.
- Added scoped request/review API and permission-gated frontend review navigation;
  no public stock execution, real records or entitlement changes.
- PostgreSQL guidance informed indexed linkage guards and transaction boundaries.
- Focused backend73 shared-boundary tests and19 API tests pass. Request-entry UI
  reuses the paginated picker with fresh destination reads, exact uncertain retries
  and no manual document IDs. Frontend46/5 suites pass; browser checks pending.
- Evidence: planning/evidence/t07-approved-reallocation.txt. Continue remaining
  lifecycle/runtime work; T07 is not complete.

## 2026-10-03 - Company-wide overdue reservation inbox

- Consolidated per-draft and overdue queries into one scoped read projection.
  Added public stock labels, manager-only paginated due endpoint and branch filter.
- PostgreSQL guidance informed safe indexed original-date prefilter and latest
  history probes. Due checks never mutate holdings or infer approval application.
- Reused reservation UI for the inbox, with fresh access-checked draft drill-down.
  No new catalogue, manager-case store, KPI cards or automatic notifications.
- Backend19/frontend16 focused tests and build pass; evidence:
  planning/evidence/t07-due-followup-inbox.txt. Browser checks pending.
- Continue reviewed reallocation and trusted runtime integration. T07 incomplete.

## 2026-10-03 - Reviewed reservation follow-up schedules

- Added immutable deadline history and replayable migration with scope/version and
  exact approval-use guards. Reused source locking, manager cases and receipts.
- Request/review/schedule API plus frontend now keep deadline approval separate
  from application. Due flags do not release or cancel; quantities remain unchanged.
- Competing releases/deadlines invalidate stale bindings; exact replay, rollback,
  concurrency and security tests pass. PostgreSQL guidance informed indexed reads
  and short transactions. No public physical stock writer is enabled.
- Backend45/frontend33 focused checks and production build pass; evidence:
  planning/evidence/t07-reservation-deadlines.txt. Browser acceptance pending.
- Next: company-wide due inbox, approved reallocation and trusted runtime adapters.

## 2026-10-03 - Durable local sales intent and retry recovery

- Implemented whitelisted browser-local intent store scoped to company/user with
  explicit branch attribution. Browser locks and expected revisions prevent silent
  competing-tab overwrite; quota/unsupported locking fail visibly.
- Editor persists exact operation before network, restores pending retries and
  clears only after confirmed save. Local drafts and Keep locally and close reuse
  existing editor and permissions. No autonomous posting or sensitive profile copy.
- Full frontend196/40, affected backend22 and build pass with existing warnings.
  Evidence: planning/evidence/t15a-local-draft-recovery.txt. Native browser acceptance
  remains pending; T15A implemented—verification pending. Resume independent T07.

## 2026-10-03 - Linked reservation request workspace

- Added scoped paginated linked holds and release-request form from draft details,
  reusing existing stock/source indexes, cases and operation intents. PostgreSQL
  guidance informed bounded indexed reads; no migration or stock mutation.
- Exact quantity validation, unconfirmed retry locks, stale-source refresh and
  dirty-discard protection tested. Durable navigation recovery remains T15A.
- Backend17/frontend11 focused tests and production build pass (existing warnings).
  Evidence: planning/evidence/t07-release-request-ui.txt. Preview HTTP200 both services.
- No browser acceptance, real records/entitlements, deployment, messaging or push.
  Continue T07 deadline/reallocation and trusted runtime integration.

## 2026-10-03 - Reviewed reservation release checkpoint

- Reused manager cases and stock posting for exact-source release approval and
  atomic consumption. Source/permission checks also precede retry; later changes
  cannot reuse approval. No automatic release on approval or expiry.
- Added module/permission-scoped request/review APIs and reused ManagerCases in
  Sales drafts. No public stock writer or entitlement changes.
- Verified backend58, frontend23/3 suites and production build (existing warnings).
  Evidence: planning/evidence/t07-reviewed-release.txt. No browser acceptance.
- Next: linked-hold listing/request UI, deadline/reallocation, paid-order adapters
  and trusted runtime integration. T07 remains in progress.

## 2026-10-03 - Tie holds to saved sales demand

- Extended existing reserve boundary with typed source identity/version, immutable
  same-company link and locked quantity/product/store validation. Exact retries
  remain authority/permission checked and source identity is in the fingerprint.
- Draft changes share the document lock and protect remaining holds. Compatible
  increases are allowed; held ownership/removal/reclassification changes are denied.
- Added read-only reserved-demand totals to draft detail/editor. Generic release
  cannot bypass the unfinished reviewed release workflow for these linked holds.
- Focused backend55 passed, then43 passed after the release-bypass guard; frontend10
  passed and build passed with existing warnings. Real hold/edit race has one winner.
  Migration replay, rollback and immutable attribution checks pass. Evidence:
  planning/evidence/t07-source-linked-reservations.txt.
- T07 remains in progress: reviewed release/reallocation/deadline cases, protected
  paid holds, approved exceptions and trusted public runtime adapters remain.
  No real holds created, deployment/push, browser checks or auto-cancellation.


## 2026-10-03 - Sales draft editor and source selection

- Added scoped paginated source selectors over existing stores/products/policies.
  Product search reuses existing Meilisearch service with public matching fields,
  bounded IDs and DB rehydration; provider/stale/foreign hits fail closed.
- Editor reuses customer selection, operation intents and pagination. Creates or
  revises demand only; retains uncertain requests, blocks conflicts, confirms dirty
  discard, clears on identity/company changes. No durable local recovery claim.
- Existing platform configuration can enable SALES explicitly; no actual company
  subscriptions or business data changed. Current product labels are display-only.
- Focused backend41 checks and full frontend179/37 pass. Subsequent read-label/unit
  changes have affected frontend10 pass and production build pass with existing
  warnings. Full backend checkpoint is being recorded in t13a-editor-integration.txt.
- Browser/provider acceptance remains pending. T15A recovery and T07 source-linked
  reservations are next dependent work, not reasons to expand the T13A editor.


## 2026-10-03 - Durable sales drafts and read workspace

- Added stable document parent and immutable header/line revisions, scoped FKs,
  empty replayable migration and atomic versioned saves using existing receipts.
- Same-operation and competing-operation PostgreSQL tests prove one effect/one
  version winner. Rollback, history immutability and revoked retry checks pass.
- Added separately SALES-gated API and personal-data/product/draft permissions.
  Paginated frontend register can inspect latest saved lines and clears stale data.
- 32 source/persistence/API tests plus 3 concurrency tests pass; 12 frontend
  register/navigation tests and production build pass with existing warnings.
  Evidence: planning/evidence/t13a-durable-drafts.txt. Preview HTTP checks pass.
- T13A remains in progress: editor, source selectors and module configuration
  control still required. Browser acceptance pending; no real entitlements enabled,
  stock holds, financial posting, deployment, customer messaging or GitHub push.


## 2026-10-03 - Customer checkpoint and sales-intent source foundation

- Full isolated backend checkpoint: 1077 passed, 2 known legacy xfailed. Prior
  frontend integration checkpoint remains 169 tests/35 suites and build passing.
- T10A implementation is acceptance-pending, not an ever-expanding dependency on
  later durable sync. T13A starts against its tested identity/policy contracts.
- Added bounded typed draft lines and locked scoped source validation, reusing
  customer reads and reviewed unit conversions. No new catalogue or posting engine.
- Thirteen focused PostgreSQL/schema checks pass. Initial run caught inherited
  eager supplier joins conflicting with row locks; disabled unused eager loading
  and restricted product locks, then reran successfully.
- Draft persistence, API/editor and retry/rollback tests remain next. No migration,
  real data, financial effect, deployment, browser action or GitHub push this slice.


## 2026-10-03 - Frontend integration checkpoint

- Owner requested frontend implementation. Inspected current queue/screen coverage;
  inventory setup/review/cost and customer public workflows have existing screens.
- Closed customer result gap: persistent save/indexing status, direct saved-record
  opening and fresh permission-checked details above the table. No duplicate screen.
- Removed sidebar API-client dependency by extracting route constant. Full frontend
  run exposed and then verified the navigation import regression fix.
- 169 tests / 35 suites and production build passed with existing warnings. Evidence:
  planning/evidence/frontend-customer-integration.txt. Backend unchanged this slice.
- Browser acceptance remains pending. Future sales/returns/offline foundations still
  need backend implementation; no fake actions or operational activation added.

## 2026-10-03 - Confirm customer search task results

- Settings and document sync now verify matching provider task/index and succeeded
  status instead of treating queue acceptance as completion. Missing IDs, pending,
  failed, canceled and timed-out tasks remain unconfirmed without logging PII.
- Shared search client has a five-second request timeout; task polling budget is
  1500ms, not a strict wall-clock cap on in-flight requests.
- Customer creation exposes search_indexed separately from the durable receipt.
  Frontend distinguishes saved identity from unconfirmed search indexing and warns
  against creating a duplicate. Exact creation retries can repair the projection.
- 22 targeted backend tests and 16 frontend tests pass; evidence:
  planning/evidence/t10a-search-task-confirmation.txt.
- Live provider/browser acceptance and durable background repair remain open.
  No schema migration, real data, deployment or push. Full regression/build deferred.

## 2026-10-03 - Keep customer search terms out of URLs

- Replaced GET search argument with read-only POST /customers/search and strict
  bounded request schema. Browse remains GET; the former query argument is rejected.
- Reused one page implementation and the same authentication/personal-data guards.
  Added no-store to successful customer responses. No write permission/receipt is
  needed for search, because it does not create records.
- Frontend sends search only in the body. Deployment must still avoid body logging.
- Focused verification: 15 backend tests and 12 frontend tests passed. Evidence:
  planning/evidence/t10a-search-privacy.txt. No full build/regression or browser run.
- T10A provider task/recovery acceptance remains open. No real business writes.

## 2026-10-03 - Company-scoped customer search

- Extended existing search service with customer projection/settings, after-commit
  sync and streamed startup repair. No second search client or catalogue.
- Paginated search requires existing personal-data permissions, exact company
  filtering and DB rehydration. PostgreSQL guidance informed bounded indexed IDs.
- Provider outages/foreign/stale hits fail closed. Async indexing may lag; committed
  customer creation is not rolled back by projection failure. No SQL LIKE fallback.
- Customer register submits/clears search and resets pagination; selection is reused.
- 31 focused backend tests and 17 frontend tests pass; production build passes with
  existing warnings. Evidence: planning/evidence/t10a-customer-search.txt.
- Pending: real provider/browser acceptance, durable projection repair and query
  access-log redaction review before release. T10A not declared complete.

## 2026-10-03 - Reuse customer register for selection

- Added optional selection mode to CustomersPage rather than a second register.
- Detail API rechecks permission/identity/version before returning scoped selection.
  Refresh/company changes abort in-flight selections; late completions are ignored.
- No sales entitlement or document writer is introduced. Consuming documents must
  revalidate the returned customer reference at their own posting boundary.
- Focused frontend tests: 16 passed / 3 suites. Evidence:
  planning/evidence/t10a-customer-selection.txt. Full suite/build deferred for this
  component-only slice; browser gate remains pending. T10A still needs search.

## 2026-10-03 - Customer creation workspace

- Added Manage_Customer-gated creation with multiple contacts and one primary,
  explicit dirty-discard confirmation and field-level server validation feedback.
- Reused useOperationIntent and company-pinned customer API. Uncertain outcomes
  retain exact payload/key and disable editing/cancel; matching receipt confirms save.
- Aborted/unmounted requests cannot update a new company screen. No PII browser
  storage. In-memory retention and unload warning are not durable draft recovery.
- Verification: 16 focused frontend tests, 25 backend contract tests and production
  build passed (existing warnings). Evidence: planning/evidence/t10a-customer-create-ui.txt.
- T10A remains in progress: search/reusable selection and browser acceptance pending.
  No real records seeded, deployment, push or customer financial functionality.

## 2026-10-03 - Protected customer API and read workspace

- Added scoped paginated GET/detail and receipt-backed POST with customer and
  personal-data permissions. Missing PERSONAL field mapping fails closed.
- Customer permissions are cross-module master-data rights, not sales entitlements.
- Frontend Customers entry supports list/contact inspection, customer-only menu
  visibility, company-pinned requests and stale-response cancellation.
- PostgreSQL guidance retained indexed organisation filtering and bounded reads.
- Verified 29 focused backend tests, 4 frontend tests and production build.
  Evidence: planning/evidence/t10a-customer-api-verification.txt.
- T10A remains in progress: creation/select UI, search and browser acceptance pending.
  No real seed, balances, auto-merges, deployment or GitHub push.

## 2026-10-03 - Start T10A retail customer identity

- **Why:** T10A is dependency-ready on T03/T04 while T06 runtime gates remain open.
  Freight consignee records are not retail customers; no existing retail entity found.
- **Change:** Scoped UUID identity/original profile, bounded typed contacts, empty
  additive migration, creation/read service using existing atomic receipts.
- **Safety:** Explicit personal-data permission callback, exact company scope,
  stable retries, original snapshot immutability, no automatic contact/balance merge.
  PostgreSQL guidance informed same-company keys and receipt ownership.
- **Verification:** 17 focused tests passed; evidence in
  planning/evidence/t10a-customer-identity-verification.txt.
- **Limits:** Internal foundation only; protected API, paginated frontend/select,
  search and revision work remain. No real seed, credit, public customer access or
  financial posting. T10A In progress; T06 remains open.

## 2026-10-03 - Opening valuation authority parity

- **Change:** Opening valuations now require persisted central pool authority,
  exact source-pool match and authority-bound retry intent. Shared pool-before-
  product lock order aligns opening and additional-cost writers.
- **Safety:** No-op extra guards cannot bypass authority; suspended/stale/foreign
  claims and newer-epoch reuse are denied. Existing source, evidence and permission
  callbacks remain mandatory. No schema, API or frontend changes.
- **Verification:** planning/evidence/t06-opening-authority-verification.txt.
- **Tracking:** Corrected stale top-of-queue baseline to the completed GitHub
  checkpoint; no whole-task completion or new full-suite claim.
- **Limits:** Runtime authentication, receipt costs and reconciliation still open;
  public financial posting remains disabled. Changes local, not automatically pushed.

## 2026-10-03 - Central writer status in cost-pool workspace

- **Change:** Typed state/epoch fields on existing pool page; one scoped bounded
  latest-authority query. Existing React table shows read-only status, not a new
  dashboard or enrollment workflow. No node identity or private reason exposed.
- **Safety:** Existing module/permission gates; failure hides stale UI status.
  Writer assigned explicitly does not mean public posting enabled.
- **Verification:** 43 backend and 12 frontend targeted tests; see
  planning/evidence/t06-authority-status-verification.txt for build evidence.
- **Limits:** Browser acceptance remains pending; no schema, authority activation,
  real data, runtime authentication or public financial posting change.
- **Undo:** Remove status projection/column; preserve authority history.

## 2026-10-03 - Central authority bound into charge posting intent

- **Change:** Mandatory typed claim on both preparation/coordinator entry points;
  persisted authority check plus exact proposal-pool lookup. Node/pool/company/
  epoch form part of the immutable operation request digest.
- **Safety:** No-op extra callbacks cannot bypass database authority. New valid
  writers cannot relabel historical requests; old claims are fenced. Existing
  unbound internal intents fail digest comparison rather than being upgraded.
- **Verification:** 53 targeted checks, 12.41s; evidence in
  planning/evidence/t06-authority-intent-verification.txt.
- **Limits:** Runtime authentication/enrollment, storage acceptance and central
  reconciliation remain pending. No API/UI activation, schema change or deployment.
- **Undo:** Disconnect internal consumers; preserve receipts and authority history.

## 2026-10-03 - Durable central cost-pool authority foundation

- **Change:** CostPoolAuthorityEpoch reuses node identities and immutable-authority
  guards; typed pool claim and same-database writer check added to existing service.
  Empty additive startup migration; no real activation or runtime credentials.
- **Safety:** Company-scoped pool/node FKs, consecutive epochs, immutable history,
  shared pool lock held through commit versus exclusive authority-transition lock.
  PostgreSQL guidance informed indexed lookup and bounded short transactions.
- **Verification:** 43 targeted authority/coordinator tests passed; see
  planning/evidence/t06-pool-authority-verification.txt.
- **Limits:** Runtime authentication and intent binding, reviewed transitions,
  distributed recovery, receipt costing and reconciliation remain incomplete.
  No public posting or frontend changes. T06 remains In progress.
- **Undo:** Disable consumers; retain append-only authority history.

## 2026-10-03 - Persisted charge-case resolution

- **Change:** Removed the prepared-posting case-loader callback; resolve exact
  persisted case internally and reuse existing approval/current-source checks.
  Both evidence checking and preparation share the same scoped case query.
- **Safety:** Reject legacy, pending/rejected, missing, wrong-proposal and foreign
  cases before storage reads. Original-version verification is still mandatory.
- **Database:** Existing company/case unique index reused; PostgreSQL guidance
  informed exact indexed scoping. No schema, migration or new approval store.
- **Verification:** planning/evidence/t06-persisted-case-verification.txt.
- **Limits:** Central-runtime authority, storage acceptance, receipt costing and
  reconciliation remain pending; no public posting or frontend changes.
- **Undo:** Disconnect internal preparation entry point; retain immutable records.

## 2026-10-03 - Version verification connected to atomic charge posting

- **Change:** Existing coordinator gains a factory-owned preparation entry point;
  existing bounded storage verification runs after the snapshot transaction closes.
  No duplicate storage client, new schema, API route or frontend control.
- **Safety:** Exact persisted v2 company/proposal binding before I/O, original
  version reads on retries, permission/authority rechecks after I/O, fail-closed
  missing evidence and changed metadata. No approval consumed on failed preparation.
- **Verification:** 40 targeted checks passed; evidence in
  planning/evidence/t06-prepared-posting-verification.txt.
- **Limits:** Authenticated central runtime/case adapters, storage acceptance,
  receipt costs and reconciliation remain pending. Existing branch authority is
  not shared-pool central authority. Public financial posting remains disabled.
- **Undo:** Disconnect entry point consumers; preserve historical receipts/entries.

## 2026-10-03 - Atomic charge-posting coordinator

- **Change:** One internal coordinator composes existing prepared-content checks,
  independent case approval, whole-charge consumption, valuation append and receipt.
  No new schema, duplicate ledger, HTTP endpoint or frontend posting control.
- **Safety:** Full intent fingerprint; permission and central-authority callbacks
  run before replay. Exact source/content checks reject foreign or changed evidence.
  Shared transactions retain outer rollback; callbacks cannot perform external I/O.
- **Verification:** 28 focused tests passed; evidence in
  planning/evidence/t06-charge-posting-verification.txt.
- **Limits:** Authenticated central-runtime authority adapter, actual storage
  configuration, receipt costing and reconciliation remain outstanding. Public
  posting remains disabled; T06 remains in progress.
- **Undo:** Disconnect coordinator consumers; preserve immutable audit records.

## 2026-10-03 - Additional costs in the existing valuation ledger

- **Change:** OPENING/CHARGE entries, original-source links, scoped insert guards,
  replayable additive migration and caller-transaction append helper. No second
  ledger. Quantity stays unchanged; costs remain unreconciled.
- **Safety:** Expected stream versions, deterministic locks, whole-charge
  conservation, mandatory authorization, immutable history and movement rejection.
  PostgreSQL guidance informed scoped uniqueness and lock ordering.
- **UI:** Existing history distinguishes charge rows and prevents selecting them
  as new allocation sources; existing APIs and components are reused.
- **Verification:** See planning/evidence/t06-charge-valuation-verification.txt.
- **Limits:** Production coordinator, receipts/reconciliation, storage configuration
  and browser acceptance remain pending. T06 is not complete; public posting off.
- **Undo:** Disable consumers, retain immutable entries and additive schema.

## 2026-10-03 - Own-operation charge-evidence replay guard

- **Why:** Consumed approvals must reject reuse but permit the exact completed
  posting to return its existing receipt after an uncertain response.
- **Change:** Optional trusted replay identity checks same actor, case use, charge
  use/evidence and charge-domain receipt, after ordinary source/permission checks.
  Company-scoped indexed lookups reuse immutable records; no new ledger or schema.
- **Verification:** Targeted evidence, charge-use and API checks; see
  planning/evidence/t06-evidence-own-replay-verification.txt.
- **Local inspection:** Bucket versioning not enabled; capture limit absent.
  Read-only check only, no configuration changes. Storage acceptance remains open.
- **Limits:** No actual valuation effect or public financial writer. Outer request
  digest, valuation versions and atomic entries must still be composed. T06 ongoing.
- **Undo:** Omit replay identity to retain strict consumed-case rejection.

## 2026-10-03 - Public version-bound evidence workflow

- **Why:** Connect existing preparation and review contracts to usable public
  actions without I/O under posting locks or a latest-file download bypass.
- **Change:** New requests capture v2; retries/reviews re-read original versions,
  recheck locked metadata and reuse the case engine. Case-scoped downloads verify
  complete bytes before returning. Frontend chooses pinned downloads and labels v1.
- **Configuration:** Positive COST_EVIDENCE_MAX_BYTES required; no guessed default,
  bucket mutation, business seed, schema migration or financial posting enabled.
- **Verification:** 112 targeted backend / 27 frontend tests; build recorded in
  planning/evidence/t06-public-versioned-evidence-verification.txt.
- **Limits:** Real storage retention/compatibility and browser acceptance pending;
  atomic charge/case/valuation and reconciliation still required. T06 In progress.
- **Undo:** Disable public capture/pinned-download consumers; retain immutable cases.

## 2026-10-03 - Two-stage charge-content preparation

- **Why:** Storage reads must not hold posting transactions or silently use a new
  file version in place of reviewed evidence.
- **Change:** Reuses charge bindings, typed fingerprints and the strict blob reader.
  Permission/source snapshot transaction closes before network reads; exact reviewed
  versions are checked and a later locked-source comparison is mandatory.
- **Verification:** 106 targeted checks in 8.34s; evidence file linked from queue.
- **Limits:** Internal bridge only; HTTP preparation and exact-version downloads
  remain pending. No UI, schema, real records, storage settings or posting changed.
- **Undo:** Disable consumers of the additive preparation service.

## 2026-10-03 - Persist content identities in existing charge reviews

- **Why:** A metadata approval must not become financial evidence when the actual
  document content or its storage version has never been independently reviewed.
- **Change:** Typed internal fingerprints, exact linked-document coverage and locked
  key/size comparison; source_version 2 case bindings retain private content identity.
  Financial evidence loader requires matching freshly prepared fingerprints and
  rejects all historical metadata-only cases. Existing approval/receipt engine reused.
- **Verification:** Focused 98 checks; planning/evidence/t06-content-review-binding-verification.txt.
- **Limits:** Public capture and exact-version downloads still need integration;
  no I/O inside posting callbacks, schema migration, UI change or public writer.
  Retention, central authority and atomic valuation remain gates. T06 In progress.
- **Undo:** Disable content-consuming adapters; preserve immutable case history.

## 2026-10-03 - Strict version-pinned evidence fingerprint primitive

- **Why:** Metadata-only reviews and compatibility local-file fallback cannot
  establish the actual supplier-document bytes used for financial evidence.
- **Change:** Existing storage adapter gains a bounded SHA256 reader with explicit
  byte limit, non-null version requirement, exact requested-version check, length
  checks and deterministic stream closure. No fallback or storage configuration write.
- **Verification:** Focused storage and evidence regressions only, per owner testing
  cadence; planning/evidence/t06-versioned-blob-verification.txt.
- **Limits:** Internal primitive only. Persisted review/download integration, actual
  RustFS version retention and atomic valuation remain required. No UI/API change,
  schema migration, live upload or new posting authority. T06 remains In progress.
- **Undo:** Stop calling the new method; legacy readers are unchanged.

## 2026-10-03 - Permission-separated charge evidence workspace

- **Why:** Make existing invoice/FX review contracts usable without duplicating
  suppliers, documents, approvals or leaking confidential source metadata.
- **Change:** Typed paginated choices and case responses; request/review endpoints;
  exact-company authenticated document downloads through the existing blob adapter.
  Requires both modules, all source/financial permissions and field clearance.
  Frontend shares picker, pagination, operation-intent and manager-case components.
- **Migration:** None. Existing immutable case bindings retain the declarations.
- **Verification:** planning/evidence/t06-evidence-workspace-verification.txt.
- **Limits:** GENERAL/PO evidence only. File-version immutability, atomic posting,
  receipt costing, reconciliation and browser acceptance remain open. No live posting.
- **Undo:** Disable the evidence router and entry point; retain historical cases.

## 2026-10-03 - Evidence-bound invoice and FX review contract

- **Why:** Allocation approval must not be treated as verification of a supplier
  invoice, eligible expense or exchange rate.
- **Change:** Typed declaration, exact charge-fx-v1 conversion, locked existing
  supplier/document/PO snapshots, distinct verify-charge case action and approved
  current/unconsumed evidence loader. Reuses immutable manager cases; old allocation
  approvals cannot satisfy charge verification. UI clarifies the distinction.
- **Migration:** None; existing case binding stores the immutable review snapshot.
- **Verification:** planning/evidence/t06-charge-evidence-review-verification.txt.
- **Limits:** Internal adapter only. Permission-aware evidence picker/API, blob
  version immutability and atomic charge/case/valuation integration remain pending.
  No financial posting, actual evidence verification or full T06 completion claimed.
- **Undo:** Disable internal evidence adapter; retain existing immutable cases.

## 2026-10-03 - Internal whole-charge consumption guard

- **Why:** Distinct operation IDs or allocation proposals must not capitalise one
  supplier charge repeatedly. Existing purchasing attachments/references do not
  constitute verified invoices; reuse their identities without inventing a second
  invoice system or prematurely enabling posting.
- **Change:** Immutable company/supplier/invoice identity use, unique proposal and
  document use, exact evidence contract, mandatory trusted callbacks and explicit
  caller-owned transaction composition. Database ownership/amount/uniqueness guards
  and deferred receipt FK; rollback restores eligibility. No endpoint or UI action.
- **Migration:** migrate_20261003_cost_charge_uses.py, empty additive/replayable table
  with bounded lock wait; existing Supplier/OrderDocument/proposals referenced.
- **Verification:** planning/evidence/t06-charge-dedup-verification.txt.
- **Limits:** Internal guard only; verified invoice/FX source integration, binding
  that evidence to review, actual valuation/approval consumption and reconciliation
  remain pending. Partial invoice use is disabled. T06 not complete.
- **Undo:** Disable internal consumers; retain immutable history/table.

## 2026-10-03 - Independent cost-allocation review

- **Why:** Review declared costs without duplicating approval infrastructure or
  treating allocation approval as supplier-invoice verification.
- **Change:** Reused manager cases/decisions, exact source binding, locked proposal
  loader and current eligibility checks on retries. Both creator and requester
  are excluded from reviewing. Scoped financial APIs, paginated history, and
  existing React request/decision controls extended for cost allocations.
- **Migration:** None; existing immutable case/decision/operation tables reused.
- **Verification:** planning/evidence/t06-cost-review-verification.txt.
- **Limits:** No financial consumption, supplier charge deduplication or central
  reconciliation yet. T06 remains in progress; browser acceptance pending.
- **Undo:** Disable cost-review adapters/UI; preserve immutable audit records.

## 2026-10-03 - Durable unposted cost allocation proposals

- **Why:** Preserve exact calculated allocations and declared charge references
  across sessions before adding independent approval and posting.
- **Change:** Immutable company/pool-owned proposal snapshots, existing atomic
  operation receipts, source-loader/permission checks on retries, scoped typed
  save/list/detail API. Frontend evidence form, failed-save intent retention and
  paginated historical register reuse existing calculation and UI infrastructure.
- **Migration:** migrate_20261003_cost_allocation.py, empty/replayable with bounded
  lock wait and immutable guard; no business seed or financial posting.
- **Verification:** planning/evidence/t06-cost-proposals-verification.txt.
- **Limits:** Reference is declared evidence, not a verified invoice. Independent
  review, charge deduplication, receipt/FX and central reconciliation remain pending.
  Browser acceptance not performed. Saved status is PROPOSED, never APPROVED.
- **Undo:** Disable proposal adapters/UI together; retain immutable records.

## 2026-10-03 - Exact source-based freight allocation preview

- **Why:** Reuse existing costing arithmetic while purchasing receipts still lack
  physical stock-ledger integration; do not treat purchasing totals as stock costs.
- **Change:** Bounded typed preview over exact same-company/pool valuation sources,
  shared visibility query, original-value or same-unit quantity basis, exact SCR
  conservation. Frontend source selection and invalidated/abortable previews.
- **Migration:** None; immutable sources and indexed scope keys reused.
- **Verification:** planning/evidence/t06-cost-allocation-preview-verification.txt.
- **Limits:** Read-only calculation, no approval or posting. Receipt, evidence and
  central reconciliation integration remain pending; browser acceptance not run.
- **Undo:** Remove preview adapter/UI together; no data reversal needed.

## 2026-10-03 - Source-linked opening valuation and financial history screen

- **Why:** Persist existing weighted-average arithmetic without copying catalogues,
  guessing costs or exposing final values before reconciliation.
- **Change:** Immutable source-linked opening values, explicit pool derivation,
  serialized versioned snapshots, shared posting transaction and mandatory internal
  authorization/evidence callback. Financially protected paginated history and
  Cost pools UI; exact strings, explicit unreconciled status and no price mutation.
- **Migration:** migrate_20261003_inventory_valuation.py; additive/replayable empty
  table and immutable guard, registered at startup, no backfill or business seeds.
- **Verification:** planning/evidence/t06-opening-valuation-verification.txt.
- **Limits:** Internal writer only. Receipt/freight evidence, public approval and
  central runtime reconciliation remain required. Browser acceptance pending.
- **Undo:** Disable matching internal consumer/read UI; retain immutable history.

## 2026-10-03 - Proposal editor and public independent-review workflow

- **Why:** Complete the usable save/request/review path instead of leaving the
  historical register disconnected from its existing services.
- **Change:** Exact batch/serial editor with failed-save intent retention,
  policy-load retry and discard protection; proposal-scoped case pagination and
  request/approve/reject actions reuse shared case engine and React panels.
  Company/module/action guards, source-version checks and self-review restrictions
  apply to public requests, including retries. Approval cannot execute conversion.
- **Migration:** None. Existing immutable proposals and manager-case records reused.
- **Verification:** planning/evidence/t05-proposal-workflow-verification.txt.
- **Limits:** Browser acceptance pending. Physical conversion requires valuation,
  movement lineage, global identities and node authority; no such execution claimed.
  Owner approved returning physical conversion to T06/T09, restoring agreed T05
  scope. T05 implementation complete; new browser acceptance remains pending.
  No preview records, accounts or real stock altered in this slice.
- **Undo:** Remove proposal entry/review UI and HTTP adapters together, retaining
  immutable proposal/case history.

## 2026-10-03 - Read-only proposal register in location stock

- **Why:** Saved proposals need an inspectable UI before entry/review integration.
- **Change:** Each stock row opens a scoped paginated register and historical batch/
  serial manifest detail. Reuses inventory client, shared pagination and contained
  panel layout; exact decimal strings and abort/context guards. No write controls.
- **Migration/API:** None; uses existing protected proposal reads.
- **Verification:** planning/evidence/reclassification-register-verification.txt.
- **Limits:** Browser acceptance pending confirmation. Editor, review and stock
  conversion remain disabled; this is not T05 completion.
- **Undo:** Remove entry point and component/client consumers together; no data undo.

## 2026-10-03 - Protected proposal save and read API

- **Why:** The upcoming proposal editor needs a stable, permission-protected backend
  without accidentally exposing the stock conversion consumer.
- **Change:** Typed save/list/detail endpoints reuse immutable proposal persistence;
  INVENTORY module and existing Request_InventoryReview/View_Product permissions.
  Exact company/parent visibility, bounded pagination and compact list projections.
  Historical detail explicitly marks conversion disabled; no source lock on reads.
- **Migration:** None; existing proposal table/indexes and review engine retained.
- **Verification:** planning/evidence/reclassification-api-verification.txt.
- **Limits:** UI editor, public review actions and physical conversion still pending.
- **Undo:** Remove router registration/consumers together; retain saved proposals.

## 2026-10-03 - Persist exact-source reclassification proposals

- **Why:** Reconciliation manifests must survive a request and must not be approved
  after stock quantities or policies change underneath them.
- **Change:** Immutable org/balance-owned proposals, typed explicit manifests,
  existing atomic receipt/retry boundary and source-specific manager-case binding.
  Lock/check product and stock source on saves, replays and review. No stock writer.
- **Migration:** migrate_20261002_stock_reclassification.py (created before local
  midnight), empty additive table, immutable trigger, bounded wait, startup registered.
- **Verification:** planning/evidence/reclassification-proposals-verification.txt.
- **Limits:** Internal service only; no UI/API conversion path, global identity or
  valuation/posting gate completion. T05 remains In progress.
- **Undo:** Disable consumers; retain immutable proposals/receipts. No destructive
  down migration. A proposal is not a physical or accounting posting.

## 2026-10-02 - Explicit stock reclassification reconciliation contract

- **Why:** Existing-stock transitions cannot infer identities or alter condition
  quantities; quantity conservation must be checked before reviewed posting exists.
- **Change:** Pure single-balance ordinary-to-batch/serial manifest validation using
  existing quantity/unit/identity schemas. Blocks reservations, mixed manifests,
  missing metadata, duplicate identities, rescaling and rounding. No new writer.
- **Migration/UI:** None. No activation path enabled; current safe blocks remain.
- **Verification:** planning/evidence/stock-reclassification-contract-verification.txt.
- **Limits:** Persistence, approval binding, source locks, global identity checks,
  valuation and atomic conversion posting remain T05 integration work.
- **Undo:** Remove the unconnected validator/tests; no data reversal needed.

## 2026-10-02 - Preserve safe extensions after barcode correction

- **Why:** A retired code's superseded rules could incorrectly block an extension
  after a valid reviewed setup correction, even though current codes were compatible.
- **Change:** Share the scoped live-code predicate across transition routes. Validate
  only live source snapshots with an outer join and explicit missing-source blocker.
  No new workflow, table, API, frontend component or identity reassignment.
- **Verification:** Reproduced two failing cases before the fix; 44 targeted tests,
  full backend700/2 known xfails and frontend109 tests pass. See planning/evidence/
  policy-live-barcode-verification.txt. Browser not rerun; frontend source unchanged.
- **Undo:** Revert predicate consumers together; retain all historical rows.
- **Limits:** Structural stock reclassification remains unimplemented; T05 In progress.

## 2026-10-02 - Compatible unit extensions and isolated T05 demonstration

- **Why:** Products with stock need reviewed new selling units without changing
  original quantities, tracking or barcode factors; the owner requested T05 samples.
- **Change:** Shared semantic extension check, exact EXTEND_UNITS case binding and
  posting kind, scoped history validation, compatible reservation/release and
  original-version barcode resolution. Reuses existing transactions and services.
  Added opt-in atomic/idempotent demo seed; restored existing company selector and
  pinned approval execution controls after tablet inspection found clipping.
- **Migration:** None. Demo seed is never called by startup and refuses other hosts
  or databases from its CLI. No existing business rows are overwritten.
- **Verification:** 698 backend pass/2 known xfails, 109 frontend pass/24 suites,
  production build pass; evidence/t05-extension-demo-verification.txt under planning.
- **Limits:** Existing-stock reclassification and historical-code rebinding remain
  blocked. T05 remains In progress; no live/hardware/accounting acceptance claimed.
- **Undo:** Revert matching service/schema/UI changes together. Do not delete demo
  records or immutable history automatically; no destructive cleanup was run.

## 2026-10-02 - Exact before/after policy comparison

- **Why:** Changed field names alone did not let users inspect old/proposed values
  before requesting review, especially when existing history blocks activation.
- **Change:** Extend the existing typed readiness response with active and proposed
  configurations; compare them in the existing frontend with exact decimal strings.
  Abort/clear obsolete checks on product, API context and editing-state changes.
- **Migration:** None; no new queries, catalogue, posting path or permissions.
- **Verification:** docs/planning/evidence/policy-comparison-verification.txt.
- **Limits:** Advisory only; existing-stock conversion and barcode rebinding remain
  blocked. Browser acceptance pending; no whole task/phase signoff.
- **Undo:** Remove optional response fields and comparison UI together; no data undo.

## 2026-10-02 - Connect retired barcodes to no-stock policy correction

- **Why:** The history check still blocked permanently retired codes, preventing
  reviewed retirement from unblocking otherwise safe setup corrections.
- **Change:** Shared readiness/posting check excludes only committed same-company
  retirements. Live codes and every stock/batch/serial history remain blocking.
  Product locking, independent policy review and immutable identities are retained.
  Frontend explains the retire/review/new-code sequence.
- **Migration:** None; reuse existing retirement uniqueness index and history.
- **Verification:** docs/planning/evidence/retired-barcode-revision-verification.txt.
- **Limits:** No existing-stock conversion or reuse/rebinding of retired codes.
  Browser acceptance remains pending; T05 remains in progress.
- **Undo:** Restore the conservative blocker and matching guidance; retain every
  revision, retirement and operation receipt.

## 2026-10-02 - Reviewed barcode retirement (T05 slice)

- **Why:** Incorrect registered codes need controlled disabling without deleting
  identity history or allowing silent reuse.
- **Change:** Reuse manager cases, atomic posting and UI components for exact-source
  request, independent review and explicit retirement. Add immutable retirement
  record, reject retired lookups/registration replays, retain original snapshots.
  Share paginated case reads instead of duplicating filtering logic.
- **Migration:** `migrate_20261002_barcode_retirements.py`; additive, replayable,
  bounded lock wait, no business seeds or automatic role grants.
- **Verification:** docs/planning/evidence/barcode-retirement-verification.txt.
- **Limits:** Browser acceptance pending; no code reassignment, stock conversion,
  stock posting, deployment or whole-phase completion.
- **Undo:** Disable new actions/consumers together; retain audit tables and retired
  identity checks. Do not delete retirement history or re-enable retired codes.

## 2026-10-02 - Personal policy review queue (T04 slice)

- **Why:** Managers need direct access to requests awaiting their review without
  browsing historical decisions or their own unreviewable requests.
- **Change:** Extend existing paginated case API with authenticated personal views;
  filter before count/page, keep exact company/module/permission boundaries.
  Reuse case UI with filters and profile shortcut; no second approval system.
- **Migration:** None; existing org/case uniqueness indexes support existence probes.
- **Verification:** docs/planning/evidence/personal-review-queue-verification.txt.
- **Limits:** Not exclusive assignment or durable unread notification delivery.
  Stale source checks still occur on decision; no browser or live posting acceptance.
- **Undo:** Remove personal-view consumers/filters together; retain all case history.

## 2026-10-02 - Frontend navigation reform

- **Why:** Implemented inventory tools were buried among logistics and branch panels.
- **Change:** Dedicated Inventory submenu, separate Logistics heading, direct cost
  pool and Approvals routes reusing existing panels, permission-aware entries,
  detail-route highlighting and FreightLens text branding. Old routes preserved.
- **Migration/API:** None; existing backend and subscription modules unchanged.
- **Verification:** 87 frontend tests in 20 suites pass; production build passes
  with existing warnings. New URLs return HTTP200; diff check passes. Router hooks
  are mocked in component tests as in the existing suite; not browser acceptance.
  Backend unchanged, not rerun: last baseline651 passed/2 known C12 xfails.
- **Limits:** Browser checks skipped. Branch/product subpanels still use contextual
  state. No operational POS screens or legacy-writer replacement claimed.
- **Undo:** Revert navigation entries and thin route adapters together; no data changes.

## 2026-10-02 - Reviewed no-history policy revisions and readiness

- **Why:** Correct initial setup without rebuilding products or reinterpreting stock.
- **Change:** Extend the existing activation and manager-case services with exact
  predecessor binding, immutable revisions and replay-safe product locking. Shared
  eligibility powers an advisory readiness API/UI. Stock/batch/serial history and
  registered barcodes block revisions; even zero balances retain their history.
- **Migration:** None; existing revision schema and scoped constraints are reused.
- **Verification:** docs/planning/evidence/policy-revisions-verification.txt.
- **Limits:** No existing-stock conversion, barcode rebinding, valuation or checkout.
  Browser checks remain deferred; T05 remains in progress.
- **Undo:** Disable revision UI/API use together; retain every policy/case/receipt.
  Never reinterpret new revision receipts as initial activations or erase history.

## 2026-10-02 - T05 unit-aware barcode registration and lookup

- **Why:** Scanning must identify an explicit unit without guessing packaging factors.
- **Change:** Immutable product/policy-bound barcode identities, same-company
  uniqueness, atomic registration/replay, paginated register and exact lookup API;
  product policy UI supports registration and verification with shared intent keys.
- **Migration:** `migrate_20261002_unit_barcodes.py`, empty additive table and guards.
- **Verification:** See docs/planning/evidence/unit-barcodes-verification.txt.
- **Limits:** No auto-import, stock/price mutation, checkout or barcode reassignment.
  Existing-stock transitions and reviewed barcode maintenance remain T05 work.
- **Undo:** Disable routes/UI together; retain permanent identities and receipts.

## 2026-10-02 - Consolidate repeated write mechanics and task dependencies

- **Why:** Repeated frontend intent and backend revision checks risk drift; source
  records and recovery must precede their consumers rather than require later rewrites.
- **Change:** Five frontend panels share operation-intent keys; two settings routes
  share lock/retry/version checks. Queue moved into docs/planning, with customer,
  sales-intent and durable-draft prerequisite slices. Existing semantics preserved.
- **Migration:** none; no schema, permission, business data or deployed API change.
- **Verification:** See docs/planning/evidence/consolidation-verification.txt.
- **Undo:** Revert helper consumers and helpers together; no data reversal required.

## 2026-10-02 - T05 initial reviewed activation (local, uncommitted)

- **Why:** A saved/approved policy must not silently become stock rules or reinterpret history.
- **Change:** Atomic case consumption and immutable activation snapshots; no-stock
  initial gate, shared product locks, exact active-policy opening compatibility,
  catalogue/SQL protection against legacy unit or stock-total edits. Added guarded
  activation API and explicit frontend confirmation plus separate active summary.
- **Migration:** `migrate_20261002_policy_activation.py`; additive, bounded lock wait.
- **Verification:** Full backend604 passed/2 known C12 xfails; frontend64 passed,
  build passed with existing warnings. Unsent review reasons are protected on close.
  Concurrent activation/opening and shared rollback checked in isolated PostgreSQL.
- **Limits:** T05 remains in progress: stock transitions and unit barcodes pending.
  Browser skipped; no business records seeded, no deployment or pilot.
- **Undo:** Disable activation consumer/UI, retaining immutable history and guards.

## 2026-10-02 - T04 manager-case foundation

- **Why:** Inventory needs exact, independently reviewed, single-use approvals.
- **Change:** Immutable request/decision/use service, transactional receipt linkage,
  source revalidation and policy request/review API and frontend. No stock mutation.
- **Migration:** `migrate_20261002_manager_cases.py`; empty additive tables.
- **Verification:**31 targeted backend tests and59 frontend tests pass; full suite
 577 passed/2 known C12 xfails before two additional SQL guard tests. Browser skipped.
- **Remaining:** Personal manager-profile notifications and visual acceptance.
- **Undo:** Disable routes/UI; preserve immutable history.

Newest entries appear first. Every architecture change records why it changed, its commit or release tag, any migration, and how to undo it.

## 2026-10-02 - Versioned branch calendars and counter configuration (local, uncommitted)

- **Why:** T03 needs configurable settings and permissions with no inferred live operational thresholds, plus a stable business-date/counter context for later posting.
- **Change:** Added immutable branch settings, permanent counter identities and counter revisions; scoped permission-guarded APIs with expected versions/stable operation keys. Added Trading settings/Counters panels, pagination, explicit missing values, Saturday/holiday support, failed-save retention, retry-key reuse and discard confirmation. Added locked server-side branch/counter/date eligibility context.
- **Migration:** `migrate_20261002_branch_settings.py` and `migrate_20261002_branch_counters.py`; empty additive tables/immutable triggers, startup registered. No actual calendars, counters, accounts or stock seeded.
- **Evidence:** Backend548 passed/2 known C12 xfails/23 warnings (28.39s); frontend53 tests in11 suites passed (5.611s); production build passed with existing warnings. Includes access/scope rejection, immutable history, migration replay, competing writes/retries, settings versions and collection-vs-trading eligibility. Preview API healthy/locations HTTP200; diff checks pass.
- **Limits:** T03 implemented, browser/layout acceptance pending by owner request. No checkout/payment/handover enabled; runtime enrollment, bank mappings, accounting and offline gates remain. T04 backend development can proceed without waiting on visual acceptance.
- **Undo:** Disable router/panel consumers together; retain identities and configuration history. Never erase historical settings or reinterpret posted business dates.

## 2026-10-02 - Mandatory stock authority binding and business-date contract (local, uncommitted)

- **Why:** A generic guard could validate the wrong branch or omit authority on factory calls; shared Sessions could retain stale stock/hold ORM state. T03 needs explicit calendar semantics without invented operational defaults.
- **Change:** Every stock adapter requires a trusted claim plus action/source callback. Exact stock branch and active parents are checked before replay; org/node/branch/epoch enter the versioned digest. Locked stock and holds refresh cached instances. Added an unconnected business-date calculator with mandatory configuration, separate weekday/weekend cutoffs and explicit holiday overrides.
- **Migration:** none; reuses immutable authority/stock schema. No runtime enrollment, business seeds, sales posting or UI activation.
- **Evidence:** Full isolated suite510 passed/2 known C12 xfails/23 warnings (23.61s), including15 scope/retry tests,2 stale-cache tests and20 calendar cases. Frontend42 tests in9 suites passed; build passed with existing warnings. Preview API healthy and inventory HTTP200; repository diff checks pass.
- **Limits:** T02 foundation verified, not distributed offline acceptance. T03 in progress: persistence, scoped settings APIs, counter permissions and UI remain. Browser checks skipped; hardware, real configuration and pilot gates remain pending.
- **Undo:** Disable future integrations before rollback; preserve authority/operation history. Never reinterpret `.authority-v1` receipts under an older kind or bypass authority to recover a retry after an epoch change.

## 2026-10-02 - Task queue, transaction composition and local authority (local, uncommitted)

- **Why:** Future invoice/payment/stock posting needs one transaction, and replay must not bypass current authority checks. Historical planning statements needed reconciliation with implemented inventory slices.
- **Change:** Added a mandatory-guard caller-session posting boundary; existing stock adapters can join it. Added immutable tenant node identities and consecutive branch authority epochs, with shared-lock authority validation before replay. Added parent T01-T34 dependency/acceptance/status queue; retained verified inventory work.
- **Migration:** `migrate_20261002_posting_authority.py`, registered at startup; empty additive tables and replayable triggers. No node enrollment, activation or business seeds.
- **Evidence:** Full isolated PostgreSQL suite 473 passed / 2 known C12 xfails / 23 warnings (21.82s); frontend 42 tests / 9 suites passed; production build passed with existing warnings. Includes outer rollback for opening/hold/release, caught-error rollback, revoked replay, foreign ownership, immutable history, competing epoch changes, branch-lock fencing and migration replay. Preview health OK and inventory HTTP200; diff checks pass.
- **Limits:** T02 remains in progress. No public enrollment/transition UI, mandatory stock-scope claim integration, distributed recovery protocol, source-record approvals or sales posting yet. Existing internal factory compatibility is not public authorization. Browser checks skipped; hardware/fresh-install/pilot gates remain open.
- **Undo:** Disable future callers before rollback; retain additive tables and committed immutable history. Never recycle operation keys, node identities or epochs. No destructive down migration.

## 2026-10-02 - Serial identity stock and read-only register (local, uncommitted)

- **Why:** The agreed workflow needs real serial identities in stock before quantity reservation, with exact assignment deferred to handover and no duplicate registration between locations.
- **Change:** Added separate audited identity/position records, a bounded explicit serial-opening manifest, whole-unit condition-derived balances and locked serial-count reconciliation. Reused operation receipts and reservation locks. Added a tenant-scoped paginated serial read and View serials frontend with no assignment/write actions.
- **Migration:** `migrate_20261002_stock_serials.py`, empty tables and composite scope key/preflight; expands the existing tracking check, adds immutable-record and serial-position scope guards. No stock/identity backfill or business seeds.
- **Evidence:** Backend444 passed/2 known C12 xfails; frontend42 tests in9 suites passed; build succeeded with existing warnings. Includes competing tills/retries, simultaneous duplicate registrations, rollback, manifest validation, SQL scope/immutability, mismatched-count rejection, migration replay, endpoint guards and stale/error/pagination UI states.
- **Limits:** Internal opening/hold adapters only. Public import/receiving, reviewed policy activation, serial handover/movement history, approvals, valuation and offline authority remain pending. Position updates remain blocked until their audited gateway exists. Browser checks skipped per owner; no phase signoff or external deployment.
- **Undo:** Disable serial callers and reads together; retain identities, positions and operation history. Do not downgrade the tracking constraint while SERIAL balances exist or reclassify them as ordinary stock.

## 2026-10-02 - Exact unit enforcement and batch stock (local, uncommitted)

- **Why:** Stock must preserve its original unit rules, keep lots separate, and prevent silent mixed-batch allocation while the later approval workflow is unfinished.
- **Change:** Added immutable opening-policy snapshots, exact alternate-unit conversions, base-increment enforcement, per-lot stock buckets and immutable batch identities. Reservations serialize per source line and reject second-bucket allocation; expired batches require rejection using the trusted branch business date. Updated stock reads/UI with lot details and review status; product draft includes a read-only conversion tester.
- **Migrations:** `migrate_20261002_stock_unit_policy.py` and `migrate_20261002_stock_batches.py`; additive fields/table plus atomic replacement of the old bucket key with partial unique indexes. No business backfill or seeds. Old NULL-policy balances remain readable but internal posting is blocked.
- **Evidence:** Backend417 passed/2 known C12 xfails; frontend38 passed; production build passed with existing warnings. Tests cover exact conversions, required lot attributes, expiry, immutable SQL guards, rollback, real simultaneous mixed-lot requests and competing tills/retries, foreign scope, migration replay, scoped batch reads and stale/error UI states.
- **Limits:** Internal stock adapters only. No policy activation, public stock-write route, serial registry/handover, mixed-lot/multi-location approval path, valuation, offline authority or phase signoff. Browser checks remain skipped by the owner.
- **Undo:** Disable new callers and UI together; retain batch identities, snapshots, indexes and immutable posting history. Do not restore the old single-bucket key once multiple lots exist, rewrite rules on old balances or replay v1 operations as v2.

## 2026-10-02 - Product units/tracking draft configuration (local, uncommitted)

- **Why:** Prepare explicit product classification and unit factors without inferring tracking from names or changing legacy stock while tracked-ledger support is unfinished.
- **Change:** Added scoped GET/PUT preparation APIs, typed decimal/batch/serial validation, product locking and expected-version conflicts, immutable audited draft revisions and a product quick-view form. Existing catalogue identity and quantity fields are unchanged. No search fields added.
- **Migration:** `migrate_20261002_inventory_policy_drafts.py`; empty same-org revision table and immutable trigger, registered at startup and metadata creation. No business seeds or activation.
- **Evidence:** Backend379 passed/2 known C12 xfails; frontend35 passed; production build passed with existing warnings.21 new backend tests include actual concurrent differing saves, permissions, tenant/shared/deleted rejection, invalid policies, retry/conflict, immutability and migration replay. UI tests cover explicit choice, conversion strings, serial reset, failed-save retention, duplicate submit, viewer restrictions and organisation changes.
- **Limits:** Draft only. Activation, barcode identities, tracked stock posting and full unit-conversion enforcement remain pending. Browser verification skipped per owner; no phase signoff or external deployment.
- **Undo:** Disable the draft router and UI together; retain immutable revisions. No stock reversal is necessary.

## 2026-10-02 - Ledger quantities connected to the location frontend (local, uncommitted)

- **Why:** Owner requested continued phased development with the frontend kept current, rather than a separate Phase0 closure detour.
- **Change:** Added exact-location paginated stock reads and a View stock panel in branch/location setup. Reuses INVENTORY/View_Product gates, scoped parents, quantity calculation and pagination. Public product columns only; no supplier/cost fetch or legacy-stock fallback. Decimal strings remain exact in the browser.
- **Migration:** none. No stock writes, branch seeds or external deployment.
- **Evidence:** Backend358 passed/2 known C12 xfails; frontend28 passed; production build succeeds with existing warnings. Seven new API tests cover guards, parent/org isolation, exact quantities, pagination, no sensitive queries and no child-location aggregation. UI tests cover wiring, errors, stale responses, precision and pagination. API health and preview HTTP200 verified.
- **Limits:** Owner explicitly skipped browser checks. Visual acceptance remains pending; stock-changing workflows and overall phases are not complete.
- **Undo:** Remove the read endpoint/client/panel together; retain stock history and setup data.

## 2026-10-02 - Persisted physical stock and owned reservations (local, uncommitted)

- **Why:** Retry protection alone does not prevent distinct sales from overbooking stock or releasing another source line's reservation.
- **Change:** Added internal untracked stock openings, location-local projections, source-owned holds and immutable versioned movements. Reused exact quantity arithmetic and durable posting receipts. Stock/hold locks serialize competing intents; source/bucket matching protects releases. Review dates are reminders, never automatic release authority.
- **Migration:** `migrate_20261002_stock_ledger.py`; empty additive tables, product/org unique key, composite ownership FKs and immutable movement trigger. Product-key preflight precedes existing create_all paths. No legacy stock backfill or business seeds.
- **Evidence:** 30 new PostgreSQL tests; full suite 351 passed/2 known C12 xfails. Includes real competing reservations/releases, retries, rollback, inactive/foreign scope rejection, source ownership, local-only allocation, SQL guards, deferred receipt FK and migration replay. Frontend 21 tests pass; build succeeds with existing warnings. HTTP preview and API health pass.
- **Limits:** Internal service only, no new route/UI. Sales-source/approval integration, tracked inventory, valuation, handover, durable node authority and recovery remain pending. No browser checks or fresh-install recovery claimed. No phase marked complete.
- **Undo:** Disable future callers before rollback; retain stock history, receipts and additive schema. Never delete/reopen committed balances or reuse new keys to repeat historical effects.

## 2026-10-02 - Unifi reference: durable posting and quantity contracts (local, uncommitted)

- **Why:** The approved sales refinements require exact availability/fulfilment boundaries and durable duplicate protection before connecting checkout, reservations and returns.
- **Change:** Added an internal transaction-owning operation service, tenant/key deduplication, request/actor conflict checks and an immutable result/event table. Added exact physical-stock and original-invoice-line calculations separating plans, reservations, handover and returns. No Unifi implementation copied.
- **Migration:** `migrate_20261002_inventory_posting.py`; additive empty table and append-only triggers, registered at startup and fresh metadata creation. No business backfill or live posting.
- **Evidence:** 44 new tests; full PostgreSQL suite321 passed/2 known C12 xfails, frontend21 passed and build passed with existing warnings. Real separate connections cover retries, races and rollback; SQL update/delete rejection and migration replay covered. Preview health remains OK.
- **Limits:** No new HTTP route or sales UI. No domain posting calls this service yet; the stock ledger, node fencing, money authority, cloud sync and later Unifi-inspired workflows remain pending. Quantity snapshots are not trusted client balances or persisted stock. C01/C10 remain partial.
- **Undo:** Disable callers before any future rollback; retain immutable receipts/outbox and additive schema. Do not remove committed operation history or replay business effects under new keys.

## 2026-10-02 - C10 explicit cost-pool configuration (local, uncommitted)

- **Why:** Owner clarified shared main-island warehousing and separate destination-island costs within one operating company. Legal identity, licensed premises, selling branches and valuation pools must remain distinct.
- **Change:** Added same-organisation pool/binding models, composite ownership constraints, indexed pool references, paginated configuration APIs and initial-assignment-only locking/retry rules. Added Cost pools UI with confirmation and separate management permission. Pure arithmetic now uses explicit cost_pool_id and pool-wac-v2; no branch-ID substitution.
- **Migration:** `migrate_20261002_inventory_cost_pools.py`, additive empty tables only. No business seeds, stock balances or financial postings.
- **Evidence:** PostgreSQL route/constraint/migration replay tests, concurrent same/different assignment tests, costing identity test, frontend component/client tests and production build. Exact final counts and limitations are in parent planning/PROGRESS.txt.
- **Limits:** No persisted valuation, stock ledger, same-pool physical transfer posting, durable authority, approved cutover/reassignment or deployment. Shared pools need an ordered valuation authority, not independent offline writers. Fresh-install and full visual acceptance gates remain outstanding.
- **Undo:** Disable the new UI/router together if necessary; retain additive configuration tables and existing bindings. Do not reinterpret pool IDs as branch IDs or revert policy for future posted records.

## 2026-10-02 - C10 branch/location setup UI (local, uncommitted)

- **Why:** Make existing scoped branch/location APIs usable in the development preview without moving stock or inventing actual business setup.
- **Change:** Added paginated branch/location navigation and create forms, parent-row actions, management-permission visibility, pinned organisation requests, stale-response cancellation and duplicate-submit guards. Fixed protected-route premature access denial while current organisation permissions load.
- **Migration:** none. No business records were created during browser checks.
- **Evidence:** Frontend component/client/route tests and production build; local browser empty-list and unsaved form inspection at1280x800 and1024x768, plus820x614 narrow list. No body overflow in inspected states. Actual125% zoom, dark appearance and populated-table visual tests remain pending.
- **Limits:** C10 remains partial; no stock posting, ledger, durable authority, edit/inactivation or real branch/node mapping. Backend suite was not rerun for this frontend-only slice; prior253-pass/2-xfail evidence remains the latest backend run. Fresh-install probe remains policy-blocked.
- **Undo:** Remove the frontend route/nav/page and client together; retain all branch/location data. No destructive schema rollback.

## 2026-10-02 - C10 branch/location master API (local, uncommitted)

- **Why:** Branch costing and physical stock assignment need explicit scoped identities rather than free-text locations or guessed stock ownership.
- **Change:** Added audited tenant-owned branches and SITE/ZONE/BIN locations, normalized unique codes, composite ownership foreign keys and indexed parent references. Added authenticated INVENTORY-module create/list endpoints with separate management permission and server pagination.
- **Migration:** `migrate_20261002_inventory_locations.py`, registered at startup. Additive empty tables only; no automatic branch seeds, product changes or stock allocation.
- **Evidence:** 22 PostgreSQL/router tests for allowed/denied requests, tenant boundaries, parent hierarchy, database constraints, duplicate codes and migration replay; full suite253 passed with2 previously known C12 xfails. Frontend tests/build pass with prior warnings. Live preview startup succeeded. A separate fresh-database probe was blocked by execution policy and remains unverified.
- **Limits:** No UI, edit/reparent/delete, stock posting, ledger, durable authority or node enrollment. C10 remains partial.
- **Undo:** Disable the new router if needed and retain the additive tables/records; no destructive down migration. Do not erase entered branch or location identities.

## 2026-10-02 - Approved branch costing calculation foundation (local, uncommitted)

- **Why:** Owner approved branch weighted averages with separate store price lists; inter-island freight must reach the destination cost rather than be spread into a shared organisation-wide average.
- **Change:** Added immutable branch/product cost calculations, receipt/issue value conservation, partial transfer cost carry-forward and exact stable freight allocation. No existing product catalogue or stock writer is replaced yet.
- **Migration:** none; no new API or database integration. Six-place decimal contracts are validated in the calculation layer only.
- **Verification:** Unit tests exercise exact examples, partial receipts, identity/quantity/range rejection, independent decimal context and 200 deterministic value-conservation scenarios. Full suite and frontend build are recorded in the POS progress log.
- **Limits:** C10 remains partial. Ledger persistence, durable retry/fencing, transfer identities, actual locations, pricing UI and late-cost adjustments remain pending.
- **Undo:** Remove the unused calculation module and its tests; no business data reversal is needed.

## 2026-10-02 - POS C01 offline and costing contract experiment (local, uncommitted)

- **Why:** Disconnected stores cannot independently maintain an exact organisation-wide moving average; retries and network arrival order must not duplicate stock or silently set accounting policy.
- **Change:** Added an application-isolated in-memory model and pytest contracts for local interrupted posting, outbox/inbox duplicate handling, authority stream gaps, tenant/node checks and complete ordered cost replay. Numerical examples expose the policy and ordering differences.
- **Migration:** none. No production routing, database, preview UI or staging changes.
- **Limits:** Not a durable transport, customer-money protocol, finalized accounting policy or completed C01 gate. Owner/accounts cost-pool choice and close-order policy remain open.
- **Undo:** Remove the prototype and its tests; no business data or schema changes require reversal.

## 2026-10-02 - POS C02 receiving and startup prerequisites (uncommitted local development)

- **Why:** Receiving lacked action/parent/tenant checks; draft creation changed received totals, partial receipts completed orders, and default role grants drifted across startup.
- **Change:** Typed decimal inputs, read/create/submit permissions, same-parent link validation, locked atomic posting and retry no-op. Default permissions exist before roles; inventory grants follow role creation; startup seeding errors now fail startup. Default viewer personal-data access is not broadened.
- **Migration:** `migrate_20261002_receipt_posting.py` adds a version marker; existing drafts remain held for quantity reconciliation. No historical quantity backfill, inventory ledger, or staging deployment.
- **Evidence:** Full PostgreSQL suite, concurrent posting/rollback tests, isolated three-start permission-pair comparison and migration replay; logs in the parent POS planning/evidence/phase0 directory. Two C12 stock-writer regressions remain strict expected failures, not accepted behavior.
- **Undo:** Do not run the old draft-posting code against new receipts. Rollback requires disabling receipt writes and reconciling affected receipts first; preserve the additive version marker and historical quantities. No automatic data reversal is provided.

## 2026-10-01 - Phase 2B explicit organisation integrity

- **Why:** `OrgMixin` silently assigned organisation `1`, hiding missing ownership on child records and allowing parent/child tenant mismatches.
- **Change:** All tenant-owned constructors assign `org_id`; parent-owned queries are scoped; a `before_flush` guard rejects missing ownership; tenant tables have `org_id NOT NULL` with no default.
- **Migration:** `migrate_20260930_org_id_integrity.py`; local verification repaired 17 PO items, one payment, one lifecycle transition, and assigned six system report templates to root ownership. A second run made no changes.
- **Undo:** remove the flush guard and restore nullable columns only after review; database rollback is `ALTER COLUMN org_id DROP NOT NULL` per migrated table. Do not restore the silent default.

## 2026-09-30 - Phase 5 security and legacy cleanup

- **Why:** The carrier webhook and legacy credential-management routes lacked adequate sender authorization, committed configuration contained credentials, and retired MySQL/development paths remained in production code.
- **Change:** Carrier webhooks require a constant-time shared-secret check; root administration is centrally guarded; module exceptions are explicit; secret defaults and the internal probe are removed; Compose requires environment configuration; legacy MySQL dependencies and startup support are removed; manual utilities are isolated under `Utils/dev` and `Utils/archive`.
- **Migration:** none
- **Operational action:** rotate the retired MySQL credential because removing it from the current tree does not remove it from Git history.
- **Undo:** revert the Phase 5 security commit, then restore deployment secrets only through the deployment platform.

## 2026-09-30 - Phase 4 executable rulebook

- **Why:** Several development rules referenced obsolete libraries, helper names, and single-organisation query patterns.
- **Change:** Rules now reflect the current RBAC, organisation-context, explicit shared-resource, storage, frontend toast, and verification conventions; unresolved stabilization work is recorded as known deviations.
- **Migration:** none
- **Undo:** revert the Phase 4 documentation commit.

## 2026-09-30 - Phase 2A explicit supplier scope

- **Why:** The global supplier table could not distinguish group-wide suppliers from tenant-owned suppliers.
- **Change:** Every supplier is explicitly shared or tenant-specific; scoped queries return shared rows plus the active tenant's rows, and only root users may manage shared suppliers.
- **Migration:** `migrate_20260930_supplier_scope.py`; legacy suppliers become shared to preserve existing access.
- **Undo:** remove the check constraint and indexes, then remove `is_shared` and `org_id` only after confirming no dependent deployment uses supplier scope.

## 2026-09-30 - Phase 1C order-document access

- **Why:** Document download and delete endpoints previously queried records by ID without tenant or permission enforcement and physically removed blobs during soft delete.
- **Change:** Reads and deletes now require document permissions, filter by organisation, add finance checks for confidential/payment files, and retain soft-deleted blobs.
- **Migration:** none
- **Undo:** revert the Phase 1C backend commit.

## 2026-09-30 - Phase 1B signed media links

- **Why:** Browser image and video elements cannot attach the API bearer token, while stable public object URLs expose media indefinitely.
- **Change:** Product media and supplier logos use expiring HMAC-SHA256 application URLs backed by a separate `MEDIA_SIGNING_KEY`; raw object keys remain storage identifiers only.
- **Migration:** none
- **Undo:** revert the Phase 1B backend and frontend commits together.

## 2026-09-30 - Phase 1A blob-storage hotfix

- **Why:** Public mutation endpoints and raw local-path fallbacks exposed files outside their owning workflows.
- **Change:** Local fallback is confined to `BLOB/`; upload and health require authentication; direct reads are limited to approved media; generic delete is removed; pytest coverage is added.
- **Commit:** `939ca2d`
- **Migration:** none
- **Undo:** revert `939ca2d`.

## 2026-09-30 - Paired stabilization baseline

- **Why:** Establish a recoverable v2 state before security and tenant changes.
- **Change:** Both `standalone-main` branches tagged `baseline-2026-10`; local PostgreSQL backup stored outside Git.
- **Migration:** none
- **Undo:** tags are historical markers and do not change runtime behavior.

## 2026-09-30 - RBAC frontend overhaul

- **Why:** Align role permission editing with cascade behavior.
- **Frontend commit:** `cbe9354`
- **Migration:** none
- **Undo:** revert the frontend commit.

## 2026-09-26 to 2026-09-30 - Report-template system

- **Why:** Support customer-configurable print and tabular reporting.
- **Backend commits:** `5c8829f` through `02466a9`
- **Migration:** `migrate_report_templates.py`, `migrate_template_activation_and_tabular.py`, `migrate_sourcing_and_quote_templates.py`
- **Undo:** revert code; database rollback requires review because startup migrations are forward-only.

## 2026-09-26 - Coolify staging stack

- **Why:** Run v2 on managed staging infrastructure.
- **Change:** PostgreSQL, RustFS, Meilisearch, API, and frontend staging services; API port 6051 and nginx port 4005.
- **Commits:** `41ce144`, `7ba18a0`, `887208b`, `5ca5550`
- **Undo:** restore the previous deployment definition and environment configuration.

## 2026-09-24 - Multi-organisation users and financial-status split

- **Why:** Allow controlled access across organisations and separate commercial state from physical PO progress.
- **Migration:** `migrate_user_allowed_orgs.py`, `migrate_decouple_financial_status.py`
- **Undo:** requires a reviewed data migration before reverting code.

## 2026-09-22 - Sourcing, RFQ confidentiality, and template sharing

- **Why:** Add controlled procurement workflows and vendor-data protection.
- **Commit:** `eae6663`
- **Undo:** revert only after reviewing created sourcing data.

## 2026-09-19 - Organisation and consignee unification

- **Migration:** `migrate_unified_org_consignee.py`
- **Undo:** requires a reviewed data migration.

## 2026-09-18 - RustFS object storage

- **Why:** Replace host-local document storage with S3-compatible object storage.
- **Undo:** preserve object keys and files before reverting storage code.

## 2026-09-04 - FreightLens v2 starts

- **Why:** Replace the single-company container tracker with a multi-module, multi-organisation ERP.
- **Backend commit:** `4f064f6`
- **Frontend commit:** `43e52be`
- **Undo:** v1 remains on legacy branches; histories cannot be bisected across this boundary.
2026-10-05 — T13 bounded atomic retail posting
- Added immutable posting attempts/tenders, append-only external card outcomes,
  immutable invoices/lines/payments/reservation commitments and replay-safe schema.
- Reused existing draft, pricing, floor-case, payment-mapping, branch/counter,
  staff assignment, reservation and PostingOperation boundaries.
- Sale posting binds protected stock but does not hand it over; posted holds cannot
  be released. Cash and externally confirmed card are the only pilot methods.
- Focused evidence: planning/evidence/20261005-atomic-sales-posting.txt.
- Review hardening separates store-scoped external-card result authority from sale posting,
  permits declined-card retry, hides receiving-account references from ordinary
  sales reads, aligns customer-agreement lock order and independently reconciles
  posted reservation release changes to cumulative HANDOVER movement history.
