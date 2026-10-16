import logging

from sqlalchemy import text

from Model.db import engine
import Model.containermgmt  # ensure all models are registered in Base.metadata

logger = logging.getLogger("containerMgmt.migrations")

# Procurement and Logistics are separately subscribed modules, and a packing
# list sits across both. A tenant without LOGISTICS cannot reach a container
# record, and one without ORDERS cannot reach a purchase order -- but the
# shipment is real either way, so the number is recorded as typed.
#
# These are fallbacks, never alternatives: the UI only offers them where a
# search has come back empty, so a real record is always preferred.


def ensure_packing_text_fallbacks():
    try:
        with engine.connect() as conn:
            statements = [
                """
                ALTER TABLE containermgmt.order_packing_lists
                    ADD COLUMN IF NOT EXISTS container_no_text VARCHAR(50);
                """,
                """
                ALTER TABLE containermgmt.order_packing_list_items
                    ADD COLUMN IF NOT EXISTS po_number_text VARCHAR(100);
                """,
            ]
            for stmt in statements:
                try:
                    conn.execute(text(stmt))
                except Exception as stmt_err:
                    logger.debug("Packing fallback column notice: %s", stmt_err)
            conn.commit()
        logger.info("Packing list text fallbacks are ready.")
    except Exception as exc:
        logger.error("Failed to add packing list text fallbacks: %s", exc)


if __name__ == "__main__":
    ensure_packing_text_fallbacks()
