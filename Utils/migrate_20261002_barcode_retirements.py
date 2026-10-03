from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.UnitBarcode import (
    UnitBarcodeRetirement, FUNCTION, RETIREMENT_GUARD, RETIREMENT_CHECK, RETIREMENT_IMMUTABLE,
)


def ensure_barcode_retirements_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        UnitBarcodeRetirement.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        conn.execute(text(RETIREMENT_GUARD))
        for name, statement in (("barcode_retirement_scope", RETIREMENT_CHECK), ("barcode_retirement_immutable", RETIREMENT_IMMUTABLE)):
            if not conn.execute(text("""SELECT 1 FROM pg_trigger WHERE
                tgrelid=to_regclass('containermgmt.inventory_unit_barcode_retirements')
                AND tgname=:name AND NOT tgisinternal"""), {"name": name}).scalar():
                conn.execute(text(statement))
