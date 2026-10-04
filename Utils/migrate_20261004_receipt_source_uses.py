"""Add empty receipt source-use history; never backfill or consume receipts."""
from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.ReceiptSourceUse import InventoryReceiptSourceUse, FUNCTION, TRIGGER


def ensure_receipt_source_uses_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        InventoryReceiptSourceUse.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
            tgrelid='containermgmt.inventory_receipt_source_uses'::regclass
            AND tgname='receipt_source_use_guard' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
