# Stabilization Implementation Plan

This file tracks implementation of the approved FreightLens stabilization plan without replacing the unrelated root-level `implementation_plan.md`.

## Increment 1: Phase 1A blob-storage hotfix

### Scope

- Add isolated pytest coverage for blob path validation and HTTP routes.
- Restrict local fallback access to the repository's `BLOB/` directory.
- Require authentication for blob upload and storage health checks.
- Restrict direct blob reads to product images, product videos, and supplier logos.
- Restrict upload to product images and videos with extension, MIME, and size validation.
- Remove the generic public blob-delete route.

### Compatibility

- Existing product image, product video, and supplier logo URLs remain readable.
- Order, payment, RFQ, defect, and container files must use their owning authenticated endpoints.
- Image uploads are limited to 10 MiB and video uploads to 200 MiB.

### Verification

- `pytest tests/test_blob_storage.py tests/test_blobs.py -q`
- Confirm the complete backend test suite passes once the test database harness exists.
- Confirm product media upload and playback in staging before production rollout.

### Rollback

Revert the Phase 1A commit. This increment has no database migration.

## Increment 2: Phase 1B signed media links

### Scope

- Sign approved media paths with HMAC-SHA256 and an expiry timestamp.
- Require a valid signature for every product-media and supplier-logo GET or HEAD request.
- Return signed product media for 24 hours and supplier logos for 15 minutes.
- Keep raw object keys as storage identifiers; React renders only signed or external URLs.
- Configure a separate `MEDIA_SIGNING_KEY` in every environment.

### Verification

- `pytest -q`
- `npm test -- --watchAll=false --runInBand src/utils/mediaUrl.test.js`
- `npm run build`
- Manual check: product thumbnails, image preview, video seeking, supplier logos, and product upload.

### Rollback

Revert the paired Phase 1B backend and frontend commits. This increment has no database migration.

## Increment 3: Phase 1C order-document access

### Scope

- Require backend view/delete document permissions.
- Apply organisation filtering before reading order documents or defect images.
- Require financial clearance for confidential and payment documents.
- Keep blobs when records are soft-deleted.

### Verification

- Cross-organisation records resolve as 404 before blob access.
- Non-financial users receive 403 for payment documents.
- Soft delete marks the record and does not call blob deletion.
- `pytest -q`

### Rollback

Revert the Phase 1C backend commit. This increment has no database migration and retained blobs need no recovery.

## Increment 4: Phase 2A explicit supplier scope

### Scope

- Add an explicit `is_shared` plus `org_id` supplier classification.
- Preserve existing global suppliers by classifying them as shared during migration.
- Default new suppliers to the active tenant; only root users may create or manage shared suppliers.
- Scope supplier master and legacy option endpoints to shared plus active/allowed tenant rows.
- Reject product-supplier links to suppliers outside the product organisation's scope.

### Verification

- Shared-or-tenant query tests cover selected and allowed organisation contexts.
- Backend `pytest -q` and frontend `npm run build` pass.
- Before staging, review the migrated shared supplier list and reclassify tenant-owned rows.

### Rollback

Code can be reverted. Database rollback drops `ck_supplier_scope`, `ix_supplier_org_id`, and `ix_supplier_is_shared`, then drops `org_id` and `is_shared` only after a backup and dependency review.
