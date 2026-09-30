# FreightLens Architecture Log

Newest entries appear first. Every architecture change records why it changed, its commit or release tag, any migration, and how to undo it.

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
