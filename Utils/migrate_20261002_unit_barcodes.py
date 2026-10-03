from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.UnitBarcode import UnitBarcode, FUNCTION, TRIGGER


def ensure_unit_barcodes_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        UnitBarcode.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("""SELECT 1 FROM pg_trigger
            WHERE tgrelid=to_regclass('containermgmt.inventory_unit_barcodes')
            AND tgname='unit_barcode_immutable' AND NOT tgisinternal""")).scalar():
            conn.execute(text(TRIGGER))
