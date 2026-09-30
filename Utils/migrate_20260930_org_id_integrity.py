import logging

from sqlalchemy import inspect, text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrations.org_id_integrity")

TENANT_TABLES = (
    "bill_of_landing",
    "container_details",
    "defect_reports",
    "goods_receipts",
    "notifications",
    "order_documents",
    "order_packing_lists",
    "order_payments",
    "order_shipments",
    "order_status_history",
    "order_templates",
    "po_items",
    "po_stage_transitions",
    "product_categories",
    "product_links",
    "product_suppliers",
    "products",
    "purchase_orders",
    "report_templates",
    "store_requests",
    "vendor_quotes",
)

PARENT_REPAIRS = {
    "defect_reports": ("po_id", "purchase_orders", "id"),
    "goods_receipts": ("po_id", "purchase_orders", "id"),
    "order_packing_lists": ("po_id", "purchase_orders", "id"),
    "order_payments": ("po_id", "purchase_orders", "id"),
    "order_shipments": ("po_id", "purchase_orders", "id"),
    "order_status_history": ("po_id", "purchase_orders", "id"),
    "po_items": ("po_id", "purchase_orders", "id"),
    "po_stage_transitions": ("po_id", "purchase_orders", "id"),
    "vendor_quotes": ("po_id", "purchase_orders", "id"),
    "product_suppliers": ("product_id", "products", "id"),
}


def ensure_org_id_integrity() -> None:
    """Repair parent-derived tenant IDs, then remove nullable/default org ownership."""
    if engine.dialect.name != "postgresql":
        logger.info("Skipping PostgreSQL org_id integrity migration on %s", engine.dialect.name)
        return

    existing_tables = set(inspect(engine).get_table_names(schema="containermgmt"))
    tables = [table for table in TENANT_TABLES if table in existing_tables]

    with engine.begin() as conn:
        for child, (child_fk, parent, parent_pk) in PARENT_REPAIRS.items():
            if child not in existing_tables or parent not in existing_tables:
                continue
            result = conn.execute(text(f"""
                UPDATE containermgmt.{child} AS child
                SET org_id = parent.org_id
                FROM containermgmt.{parent} AS parent
                WHERE child.{child_fk} = parent.{parent_pk}
                  AND child.org_id IS DISTINCT FROM parent.org_id
            """))
            if result.rowcount:
                logger.warning("Repaired %s org_id values in %s", result.rowcount, child)

        if "container_details" in existing_tables and "bill_of_landing" in existing_tables:
            result = conn.execute(text("""
                UPDATE containermgmt.container_details AS child
                SET org_id = parent.org_id
                FROM containermgmt.bill_of_landing AS parent
                WHERE child."BillOfLanding" = parent."BillOfLanding"
                  AND child.org_id IS DISTINCT FROM parent.org_id
            """))
            if result.rowcount:
                logger.warning("Repaired %s container org_id values from bills of lading", result.rowcount)

        if "report_templates" in existing_tables:
            result = conn.execute(text("""
                UPDATE containermgmt.report_templates
                SET org_id = 1
                WHERE org_id IS NULL AND is_system IS TRUE
            """))
            if result.rowcount:
                logger.warning("Assigned %s system report templates to the root tenant", result.rowcount)

        for table in tables:
            null_count = conn.execute(
                text(f"SELECT count(*) FROM containermgmt.{table} WHERE org_id IS NULL")
            ).scalar_one()
            if null_count:
                raise RuntimeError(
                    f"Cannot enforce org_id on containermgmt.{table}: {null_count} rows are unclassified"
                )

        for table in tables:
            conn.execute(text(f"""
                ALTER TABLE containermgmt.{table}
                ALTER COLUMN org_id DROP DEFAULT,
                ALTER COLUMN org_id SET NOT NULL
            """))

    logger.info("Organisation ownership is explicit on %s tenant tables", len(tables))
