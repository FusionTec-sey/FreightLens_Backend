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
