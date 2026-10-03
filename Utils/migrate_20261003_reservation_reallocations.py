from sqlalchemy import text
from Model.db import engine
from Model.containermgmt.Inventory.ReservationReallocation import ReservationReallocation, FUNCTION, TRIGGER


def ensure_reservation_reallocations_schema():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        ReservationReallocation.__table__.create(conn, checkfirst=True)
        conn.execute(text(FUNCTION))
        if not conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgrelid = 'containermgmt.reservation_reallocations'::regclass "
            "AND tgname = 'reservation_reallocation_guard' AND NOT tgisinternal")).scalar():
            conn.execute(text(TRIGGER))
