# Tenant Ownership Audit

Verified 1 October 2026 as part of stabilization Phase 2B.

## Tenant-Owned Models

The 21 `OrgMixin` tables below require a non-null, explicitly assigned `org_id` and
are protected by the SQLAlchemy `before_flush` guard:

`bill_of_landing`, `container_details`, `defect_reports`, `goods_receipts`,
`notifications`, `order_documents`, `order_packing_lists`, `order_payments`,
`order_shipments`, `order_status_history`, `order_templates`, `po_items`,
`po_stage_transitions`, `product_categories`, `product_links`, `product_suppliers`,
`products`, `purchase_orders`, `report_templates`, `store_requests`, and
`vendor_quotes`.

An AST audit of all active Python code confirmed that each explicit `OrgMixin`
construction assigns `org_id`; the two reviewed `**kwargs` constructors populate it
before construction.

## Parent-Owned Tables

These rows do not duplicate `org_id`; access must always be scoped through the named
parent:

| Table/model | Tenant-owning parent |
| --- | --- |
| `container_docs`, legacy `packing_list` | `container_details` |
| `defect_items`, `defect_images` | `defect_reports` |
| `po_version_snapshots` | `purchase_orders` |
| report template versions/render children | `report_templates` |

## Explicit Shared Scope

| Table/model | Rule |
| --- | --- |
| `supplier` | `is_shared=true` requires null `org_id`; tenant suppliers require `org_id` |
| `currency_exchange_rates` | null `org_id` is a global base rate; non-null is a tenant override |
| `payment_terms`, `master_document_types` | group-wide reference masters |
| currencies and logistics reference tables | group-wide reference masters |

`consignee.org_id` is explicit tenant ownership even though the legacy model does not
yet use `OrgMixin`; current data has no null owner. `audit_logs` is an internal ledger
identified by table and record rather than a directly exposed business resource. Any
future audit-log endpoint must resolve tenant scope through the referenced record or add
an explicit `org_id` first.

## Local Migration Verification

- Repaired parent mismatch counts: `po_items=17`, `order_payments=1`,
  `po_stage_transitions=1`.
- Assigned six existing system report templates to root organisation `1`; their
  `active_org_ids` continue to control where they are available.
- Post-migration parent mismatch count for those repaired tables: zero.
- All 21 tenant-owned columns: `NOT NULL`, no database default.
- Second migration run: no changes (idempotent).
