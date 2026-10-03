from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource, FUNCTION, TRIGGER


def ensure_sales_reservation_sources_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        SalesReservationSource.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid = 'containermgmt.sales_reservation_sources'::regclass "
            "AND tgname = 'sales_reservation_source_immutable' AND NOT tgisinternal")).scalar():
            conn.execute(text(TRIGGER))
