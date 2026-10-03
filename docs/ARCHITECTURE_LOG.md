# FreightLens Architecture Log

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
