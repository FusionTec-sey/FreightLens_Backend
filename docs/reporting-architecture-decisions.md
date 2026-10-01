# Reporting Architecture Decisions

Approved on 2026-10-01 for the Print, Reports, and Dashboard Template Studio roadmap.

## Issued documents

Formally issued purchase orders and RFQs retain both the immutable PDF in RustFS and a
render snapshot containing the template version, resolver context, render options,
organisation profile version, renderer version, SHA-256 output hash, issuer, and issue
time. Previews and ordinary register exports are audited but are not retained as files.

The default retention boundary is until the order is finalised and fully paid. The schema
must permit a longer organisation-specific retention policy later.

## Cross-organisation reports

A requested organisation set must always be a subset of the organisations assigned to
the user. Reports spanning more than one organisation also require
`Cross_Org_Report`. An all-organisation report is permitted only when the user is assigned
every active organisation and has that permission. Tenant hierarchy never expands data
scope implicitly.

## Preview isolation

Template previews execute no JavaScript and receive neither `allow-scripts` nor
`allow-same-origin`. Rendered fragments are sanitised, and resource URLs are restricted
to inline `data:` URLs or tenant-authorised `asset:` keys. The final preview implementation
will display the generated PDF through pdf.js.

## Phase 2 delivery

Phase 2 remains one roadmap phase with three separately reviewable deliveries:

1. Phase 2A: access policy, catalog, query compiler, validated configuration, read-only
   reporting session, and database isolation.
2. Phase 2B: migrate dashboard, registers, and document resolvers in that order while
   retaining existing API contracts.
3. Phase 2C: render worker, limits, audit records, RustFS outputs, issued-document
   snapshots, and real-PDF preview.

## Database reset policy

Current data is disposable test data. Schema work may reset and reseed the database.
Use one clean Alembic baseline and a deterministic, idempotent demo-data reset script;
do not add compatibility code solely to preserve the current test dataset.
