import logging
from sqlalchemy import text
from Model.db import engine
import Model.containermgmt  # ensure all models are registered in Base.metadata

logger = logging.getLogger("containerMgmt.migrations")

# Schema for packing lists built from a container rather than from a single PO.
#
# 1. order_packing_lists gains container_id and source, and loses the NOT NULL
#    on po_id: a container-first list covers several POs, so no single one owns
#    the header. The POs it covers are derived from its lines.
# 2. order_packing_list_items gains po_id, denormalised so a line still knows
#    its order when po_item_id is null (a hand-added product) or when the PO
#    item is later removed.
#
# The PONo backfill is deliberately exact-match only. PONo is free text, so it
# holds typos, several numbers in one field and references to orders that never
# existed; a fuzzy match would invent links nobody can audit. What does not
# match is logged and left in PONo, which the UI still shows.


def ensure_container_po_link_schema():
    try:
        with engine.connect() as conn:
            is_pg = engine.dialect.name == "postgresql"

            statements = [
                """
                ALTER TABLE containermgmt.order_packing_lists
                    ADD COLUMN IF NOT EXISTS container_id INTEGER
                        REFERENCES containermgmt.container_details("Container_ID");
                """,
                """
                ALTER TABLE containermgmt.order_packing_lists
                    ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'PO';
                """,
                """
                CREATE INDEX IF NOT EXISTS ix_order_packing_lists_container_id
                    ON containermgmt.order_packing_lists (container_id);
                """,
                """
                ALTER TABLE containermgmt.order_packing_lists
                    ALTER COLUMN po_id DROP NOT NULL;
                """,
                """
                ALTER TABLE containermgmt.order_packing_list_items
                    ADD COLUMN IF NOT EXISTS po_id INTEGER
                        REFERENCES containermgmt.purchase_orders(id);
                """,
                """
                CREATE INDEX IF NOT EXISTS ix_order_packing_list_items_po_id
                    ON containermgmt.order_packing_list_items (po_id);
                """,
            ]

            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except Exception as stmt_err:
                    logger.debug("Container/PO link schema notice: %s", stmt_err)
            conn.commit()

            # Existing lines: take the order from the PO item they point at,
            # then from the header they belong to.
            conn.execute(text("""
                UPDATE containermgmt.order_packing_list_items AS li
                SET po_id = pi.po_id
                FROM containermgmt.po_items AS pi
                WHERE li.po_item_id = pi.id AND li.po_id IS NULL;
            """))
            conn.execute(text("""
                UPDATE containermgmt.order_packing_list_items AS li
                SET po_id = pl.po_id
                FROM containermgmt.order_packing_lists AS pl
                WHERE li.packing_list_id = pl.id AND li.po_id IS NULL AND pl.po_id IS NOT NULL;
            """))

            # Every list that exists today was built from one PO.
            conn.execute(text("""
                UPDATE containermgmt.order_packing_lists
                SET source = 'PO'
                WHERE source IS NULL;
            """))
            conn.commit()

            # Backfill the links from the free-text PONo into order_shipments,
            # which is where this app has always recorded "this order rode in
            # this container". Exact match only.
            backfilled = conn.execute(text("""
                INSERT INTO containermgmt.order_shipments
                    (org_id, po_id, container_id, bill_of_lading_no, shipment_status, is_deleted)
                SELECT p.org_id, p.id, c."Container_ID",
                       COALESCE(c."BillOfLanding", ''),
                       CASE WHEN c.in_bound IS NULL THEN 'IN_TRANSIT' ELSE 'ARRIVED' END,
                       false
                FROM containermgmt.container_details AS c
                JOIN containermgmt.purchase_orders AS p
                  ON UPPER(TRIM(c."PONo")) = UPPER(TRIM(p.po_number))
                WHERE c."PONo" IS NOT NULL
                  AND TRIM(c."PONo") <> ''
                  AND p.is_deleted = false
                  AND NOT EXISTS (
                      SELECT 1 FROM containermgmt.order_shipments AS s
                      WHERE s.container_id = c."Container_ID" AND s.po_id = p.id
                  );
            """)).rowcount
            conn.commit()

            unmatched = conn.execute(text("""
                SELECT COUNT(*) FROM containermgmt.container_details AS c
                WHERE c."PONo" IS NOT NULL
                  AND TRIM(c."PONo") <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM containermgmt.order_shipments AS s
                      WHERE s.container_id = c."Container_ID"
                  );
            """)).scalar()

            logger.info(
                "Packing list schema ready. Linked %s container-order pairs from PONo; "
                "%s containers still carry a PONo that matched no purchase order.",
                backfilled, unmatched
            )
    except Exception as e:
        logger.error("Failed to run container/PO link migration: %s", e)


if __name__ == "__main__":
    ensure_container_po_link_schema()
